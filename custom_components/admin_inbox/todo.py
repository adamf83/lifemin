"""The 'Needs review' todo list: the human review gate for extracted items."""
from __future__ import annotations

import logging

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from homeassistant.util.ulid import ulid_now

from .const import DOMAIN
from .coordinator import AdminInboxCoordinator
from .models import ItemState, StoredItem
from .runtime_data import AdminInboxConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: AdminInboxConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([AdminInboxTodoListEntity(entry)])


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="admin_inbox",
    )


def _todo_item_from_stored(item: StoredItem) -> TodoItem:
    the_date = item.due_date or item.event_date
    summary = f"{item.title} — {item.counterparty}"
    description_lines = [
        f"Kind: {item.kind}",
        f"Amount: {item.amount} {item.currency}" if item.amount is not None else "Amount: —",
        f"Date: {the_date.isoformat() if the_date else '—'}",
        f"Confidence: {item.confidence:.2f}" if item.confidence is not None else "",
        f"Source quote: {item.source_quote}",
        # Included so admin_inbox.confirm_item/reject_item are usable from
        # a script without first hunting for the item's id elsewhere --
        # checking the box or deleting it in this list still does the same
        # thing without needing it.
        f"Item ID: {item.id}",
    ]
    return TodoItem(
        uid=item.id,
        summary=summary,
        status=TodoItemStatus.NEEDS_ACTION,
        description="\n".join(line for line in description_lines if line),
        due=the_date,
    )


class AdminInboxTodoListEntity(CoordinatorEntity[AdminInboxCoordinator], TodoListEntity):
    """Needs review list: one TodoItem per pending StoredItem."""

    _attr_has_entity_name = True
    _attr_translation_key = "needs_review"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )

    def __init__(self, entry: AdminInboxConfigEntry) -> None:
        super().__init__(entry.runtime_data.coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_review"
        self._attr_device_info = _device_info(entry)

    @property
    def todo_items(self) -> list[TodoItem]:
        if self.coordinator.data is None:
            return []
        return [_todo_item_from_stored(item) for item in self.coordinator.data.pending]

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Manually add an item to the review queue (not extracted from email)."""
        store = self._entry.runtime_data.store
        now = dt_util.utcnow()
        uid = f"manual-{ulid_now()}"
        stored = StoredItem(
            id=ulid_now(),
            entry_id=self._entry.entry_id,
            uid=uid,
            content_hash="",
            state=ItemState.PENDING,
            created_at=now,
            updated_at=now,
            kind="other",
            title=item.summary or "Manually added item",
            counterparty="",
            confidence=1.0,
            source_quote="",
            known_uids=[uid],
        )
        store.save_item(stored)
        self.coordinator.signal_update()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        if item.uid is None:
            return
        store = self._entry.runtime_data.store
        stored = store.get(item.uid)
        if stored is None:
            return

        if item.status == TodoItemStatus.COMPLETED:
            stored.state = ItemState.CONFIRMED
            stored.reviewed_at = dt_util.utcnow()
        else:
            stored.state = ItemState.PENDING

        store.save_item(stored)
        self.coordinator.signal_update()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Deleting a review item is treated as an explicit rejection."""
        store = self._entry.runtime_data.store
        for uid in uids:
            stored = store.get(uid)
            if stored is None:
                continue
            stored.state = ItemState.REJECTED
            stored.reviewed_at = dt_util.utcnow()
            store.save_item(stored)
        self.coordinator.signal_update()
