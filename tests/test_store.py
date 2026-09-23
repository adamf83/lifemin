"""Tests for store.py: dedup index, content-hash merge, persistence."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.util import dt as dt_util

from custom_components.admin_inbox.models import ItemState, MessageRef
from custom_components.admin_inbox.store import AdminInboxStore, content_hash, normalize_text


async def test_reserve_pending_fetch_creates_item(hass):
    store = AdminInboxStore(hass, "entry1")
    await store.async_load()

    item = store.reserve_pending_fetch("uid-1")

    assert item.state == ItemState.PENDING_FETCH
    assert store.is_uid_known("uid-1")


async def test_reserve_pending_fetch_is_idempotent(hass):
    store = AdminInboxStore(hass, "entry1")
    await store.async_load()

    item1 = store.reserve_pending_fetch("uid-1")
    item2 = store.reserve_pending_fetch("uid-1")

    assert item1.id == item2.id


async def test_duplicate_uid_dropped_at_dedup_gate(hass):
    store = AdminInboxStore(hass, "entry1")
    await store.async_load()

    item = store.reserve_pending_fetch("uid-1")
    item.state = ItemState.CONFIRMED
    store.save_item(item)

    assert store.is_uid_known("uid-1") is True


async def test_content_hash_merge_across_different_uids(hass):
    store = AdminInboxStore(hass, "entry1")
    await store.async_load()

    text = "Same email body, byte-identical"
    chash = content_hash(text)

    item1 = store.reserve_pending_fetch("uid-1")
    store.mark_pending_review(
        item1,
        kind="bill",
        title="t",
        counterparty="c",
        amount=None,
        currency=None,
        due_date=None,
        event_date=dt_util.now().date(),
        confidence=0.9,
        source_quote="q",
        message_ref=MessageRef(
            entry_id="entry1", uid="uid-1", message_id=None, subject="s", sender="a@b.com", date="d"
        ),
        chash=chash,
    )

    found = store.find_by_content_hash(chash)
    assert found is not None
    assert found.id == item1.id

    item2 = store.reserve_pending_fetch("uid-2")
    existing = store.find_by_content_hash(content_hash(text))
    assert existing.id == item1.id

    store.merge_uid_into(existing, "uid-2")
    store.delete_item(item2.id)

    assert "uid-2" in existing.known_uids
    assert store.get_by_uid("uid-2").id == item1.id


async def test_normalize_text_collapses_whitespace():
    assert normalize_text("a\n\n  b\t c") == "a b c"


async def test_prune_dedup_only_older_than(hass):
    store = AdminInboxStore(hass, "entry1")
    await store.async_load()

    item = store.reserve_pending_fetch("uid-old")
    store.mark_terminal_dedup_only(item, ItemState.VALIDATION_REJECTED, "source_quote:not_verbatim_in_source")
    # Backdate without going through save_item, which always stamps
    # updated_at to now -- a real stale item is stale precisely because
    # nothing has saved over it since.
    store.get(item.id).updated_at = dt_util.utcnow() - timedelta(days=500)

    pruned = store.prune_dedup_only_older_than(400)

    assert pruned == 1
    assert store.get(item.id) is None


async def test_stuck_items_returns_old_pending_fetch(hass):
    store = AdminInboxStore(hass, "entry1")
    await store.async_load()

    item = store.reserve_pending_fetch("uid-stuck")
    store.get(item.id).updated_at = dt_util.utcnow() - timedelta(hours=2)

    stuck = store.stuck_items(timedelta(hours=1))

    assert len(stuck) == 1
    assert stuck[0].id == item.id


async def test_save_and_reload_round_trips(hass):
    store = AdminInboxStore(hass, "entry1")
    await store.async_load()
    item = store.reserve_pending_fetch("uid-1")
    store.mark_pending_review(
        item,
        kind="bill",
        title="Energy bill",
        counterparty="British Gas",
        amount=None,
        currency=None,
        due_date=dt_util.now().date(),
        event_date=None,
        confidence=0.9,
        source_quote="q",
        message_ref=MessageRef(
            entry_id="entry1", uid="uid-1", message_id="m1", subject="s", sender="a@b.com", date="d"
        ),
        chash="abc",
    )
    await store.async_save_now()

    store2 = AdminInboxStore(hass, "entry1")
    await store2.async_load()

    reloaded = store2.get(item.id)
    assert reloaded is not None
    assert reloaded.title == "Energy bill"
    assert reloaded.state == ItemState.PENDING
