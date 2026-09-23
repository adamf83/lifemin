"""Persistent storage for admin_inbox: items, dedup index, content-hash index."""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util.ulid import ulid_now

from .const import STORE_KEY_FMT, STORE_VERSION
from .models import DEDUP_BLOCKED_STATES, ItemState, MessageRef, StoredItem

_LOGGER = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")


class StoreSchemaUnsupportedError(Exception):
    """Raised when the persisted schema version is newer than this code understands."""


def normalize_text(text: str) -> str:
    """Collapse all whitespace runs to a single space and strip ends."""
    return _WHITESPACE_RE.sub(" ", text).strip()


def content_hash(text: str) -> str:
    """sha256 of normalized email text, used as the secondary dedup key."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


class _AdminInboxJSONStore(Store):
    """Store subclass carrying the migration function.

    Only version 1 exists at launch. This is wired up now, following the
    standard HA (old_major, old_minor) -> new_version dict pattern, so a
    future schema bump only needs an entry added here. A stored version
    newer than what this code understands (e.g. after a downgrade) raises
    rather than silently guessing at a migration.
    """

    async def _async_migrate_func(
        self, old_major_version: int, old_minor_version: int, old_data: dict
    ) -> dict:
        if old_major_version > STORE_VERSION:
            raise StoreSchemaUnsupportedError(
                f"admin_inbox store schema version {old_major_version} is newer than "
                f"this integration's supported version {STORE_VERSION}"
            )
        # No migrations defined yet; version 1 is the only version.
        return old_data


class AdminInboxStore:
    """Wraps a single HA Store file for one admin_inbox config entry."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self._store: Store = _AdminInboxJSONStore(
            hass,
            STORE_VERSION,
            STORE_KEY_FMT.format(entry_id=entry_id),
            minor_version=1,
        )
        # id -> StoredItem
        self._items: dict[str, StoredItem] = {}
        # uid -> item id
        self._uid_index: dict[str, str] = {}
        # content_hash -> item id
        self._hash_index: dict[str, str] = {}
        self._loaded = False

    async def async_load(self) -> None:
        """Load from disk, running migrations as needed."""
        try:
            raw = await self._store.async_load()
        except Exception as err:  # noqa: BLE001 - corrupted/unreadable store file
            _LOGGER.error("admin_inbox store failed to load for %s: %s", self.entry_id, err)
            raise

        if raw is None:
            self._loaded = True
            return

        for item_data in raw.get("items", []):
            item = StoredItem.from_dict(item_data)
            self._items[item.id] = item
            self._uid_index[item.uid] = item.id
            for uid in item.known_uids:
                self._uid_index[uid] = item.id
            if item.content_hash:
                self._hash_index.setdefault(item.content_hash, item.id)

        self._loaded = True

    def _async_persist(self) -> None:
        self._store.async_delay_save(self._as_storage_dict, 1.0)

    def _as_storage_dict(self) -> dict[str, Any]:
        return {"items": [item.as_dict() for item in self._items.values()]}

    async def async_save_now(self) -> None:
        """Force an immediate save (used by tests and on unload)."""
        await self._store.async_save(self._as_storage_dict())

    # -- dedup ---------------------------------------------------------

    def is_uid_known(self, uid: str) -> bool:
        """True if this uid maps to an item in a dedup-blocked state."""
        item_id = self._uid_index.get(uid)
        if item_id is None:
            return False
        item = self._items.get(item_id)
        return item is not None and item.state in DEDUP_BLOCKED_STATES

    def find_by_content_hash(self, chash: str) -> StoredItem | None:
        item_id = self._hash_index.get(chash)
        return self._items.get(item_id) if item_id else None

    def reserve_pending_fetch(self, uid: str) -> StoredItem:
        """Create (or return existing) placeholder item for a uid about to be fetched."""
        existing_id = self._uid_index.get(uid)
        if existing_id and existing_id in self._items:
            return self._items[existing_id]

        now = dt_util.utcnow()
        item = StoredItem(
            id=ulid_now(),
            entry_id=self.entry_id,
            uid=uid,
            content_hash="",
            state=ItemState.PENDING_FETCH,
            created_at=now,
            updated_at=now,
            known_uids=[uid],
        )
        self._items[item.id] = item
        self._uid_index[uid] = item.id
        self._async_persist()
        return item

    def merge_uid_into(self, item: StoredItem, uid: str) -> None:
        """Record an additional known uid against an existing item (content-hash merge)."""
        if uid not in item.known_uids:
            item.known_uids.append(uid)
        self._uid_index[uid] = item.id
        item.updated_at = dt_util.utcnow()
        self._async_persist()

    # -- CRUD ------------------------------------------------------------

    def get(self, item_id: str) -> StoredItem | None:
        return self._items.get(item_id)

    def get_by_uid(self, uid: str) -> StoredItem | None:
        item_id = self._uid_index.get(uid)
        return self._items.get(item_id) if item_id else None

    def all_items(self) -> list[StoredItem]:
        return list(self._items.values())

    def items_in_state(self, *states: ItemState) -> list[StoredItem]:
        state_set = set(states)
        return [item for item in self._items.values() if item.state in state_set]

    def save_item(self, item: StoredItem) -> None:
        item.updated_at = dt_util.utcnow()
        self._items[item.id] = item
        self._uid_index[item.uid] = item.id
        for uid in item.known_uids:
            self._uid_index[uid] = item.id
        if item.content_hash:
            self._hash_index.setdefault(item.content_hash, item.id)
        self._async_persist()

    def delete_item(self, item_id: str) -> None:
        item = self._items.pop(item_id, None)
        if item is None:
            return
        for uid in [item.uid, *item.known_uids]:
            # Only remove a uid mapping that still points at this item: a
            # uid can have been reassigned to another item via
            # merge_uid_into (content-hash merge) before this delete runs,
            # e.g. when a dedup placeholder is dropped after its uid was
            # folded into an existing item.
            if self._uid_index.get(uid) == item_id:
                self._uid_index.pop(uid, None)
        if item.content_hash and self._hash_index.get(item.content_hash) == item_id:
            self._hash_index.pop(item.content_hash, None)
        self._async_persist()

    def mark_fetch_failed(self, item: StoredItem) -> None:
        item.state = ItemState.FETCH_FAILED
        item.fetch_failure_count += 1
        self.save_item(item)

    def mark_terminal_dedup_only(self, item: StoredItem, state: ItemState, reason: str) -> None:
        """Transition to a terminal state that retains only dedup keys + reason."""
        item.state = state
        item.reason = reason
        item.kind = None
        item.title = None
        item.counterparty = None
        item.amount = None
        item.currency = None
        item.due_date = None
        item.event_date = None
        item.confidence = None
        item.source_quote = None
        item.message_ref = None
        self.save_item(item)

    def mark_pending_review(
        self,
        item: StoredItem,
        *,
        kind: str,
        title: str,
        counterparty: str,
        amount,
        currency: str | None,
        due_date,
        event_date,
        confidence: float,
        source_quote: str,
        message_ref: MessageRef,
        chash: str,
    ) -> None:
        item.state = ItemState.PENDING
        item.kind = kind
        item.title = title
        item.counterparty = counterparty
        item.amount = amount
        item.currency = currency
        item.due_date = due_date
        item.event_date = event_date
        item.confidence = confidence
        item.source_quote = source_quote
        item.message_ref = message_ref
        item.content_hash = chash
        self._hash_index.setdefault(chash, item.id)
        self.save_item(item)

    # -- reconciliation / pruning ----------------------------------------

    def stuck_items(self, older_than: timedelta) -> list[StoredItem]:
        cutoff = dt_util.utcnow() - older_than
        return [
            item
            for item in self._items.values()
            if item.state in (ItemState.PENDING_FETCH, ItemState.FETCH_FAILED)
            and item.updated_at < cutoff
        ]

    def prune_dedup_only_older_than(self, days: int) -> int:
        """Remove terminal dedup-only records (extraction_failed/validation_rejected) past retention."""
        cutoff = dt_util.utcnow() - timedelta(days=days)
        to_delete = [
            item.id
            for item in self._items.values()
            if item.state in (ItemState.EXTRACTION_FAILED, ItemState.VALIDATION_REJECTED)
            and item.updated_at < cutoff
        ]
        for item_id in to_delete:
            self.delete_item(item_id)
        return len(to_delete)
