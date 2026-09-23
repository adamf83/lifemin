"""Entity rendering + interaction tests for todo.py."""
from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.admin_inbox.models import ItemState

from .conftest import add_mock_imap_entry, async_setup_fake_ai_task
from .helpers import async_setup_admin_inbox, make_confirmed_item


async def test_pending_item_appears_in_todo_list(hass: HomeAssistant):
    imap_entry = add_mock_imap_entry(hass)
    ai_task_entity_id = await async_setup_fake_ai_task(hass, [])
    entry = await async_setup_admin_inbox(
        hass, imap_entry_id=imap_entry.entry_id, ai_task_entity_id=ai_task_entity_id
    )

    item = make_confirmed_item(entry_id=entry.entry_id, uid="uid-1")
    item.state = ItemState.PENDING
    entry.runtime_data.store.save_item(item)
    entry.runtime_data.coordinator.signal_update()
    await hass.async_block_till_done()

    todo_entity_id = hass.states.async_entity_ids("todo")[0]
    todo_entity = hass.data["todo"].get_entity(todo_entity_id)

    items = todo_entity.todo_items
    assert len(items) == 1
    assert items[0].uid == item.id
    assert "British Gas" in items[0].summary


async def test_completing_todo_item_confirms_it(hass: HomeAssistant):
    imap_entry = add_mock_imap_entry(hass)
    ai_task_entity_id = await async_setup_fake_ai_task(hass, [])
    entry = await async_setup_admin_inbox(
        hass, imap_entry_id=imap_entry.entry_id, ai_task_entity_id=ai_task_entity_id
    )

    item = make_confirmed_item(entry_id=entry.entry_id, uid="uid-2")
    item.state = ItemState.PENDING
    entry.runtime_data.store.save_item(item)
    entry.runtime_data.coordinator.signal_update()
    await hass.async_block_till_done()

    todo_entity_id = hass.states.async_entity_ids("todo")[0]
    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": todo_entity_id, "item": item.id, "status": "completed"},
        blocking=True,
    )
    await hass.async_block_till_done()

    stored = entry.runtime_data.store.get(item.id)
    assert stored.state == ItemState.CONFIRMED


async def test_deleting_todo_item_rejects_it(hass: HomeAssistant):
    imap_entry = add_mock_imap_entry(hass)
    ai_task_entity_id = await async_setup_fake_ai_task(hass, [])
    entry = await async_setup_admin_inbox(
        hass, imap_entry_id=imap_entry.entry_id, ai_task_entity_id=ai_task_entity_id
    )

    item = make_confirmed_item(entry_id=entry.entry_id, uid="uid-3")
    item.state = ItemState.PENDING
    entry.runtime_data.store.save_item(item)
    entry.runtime_data.coordinator.signal_update()
    await hass.async_block_till_done()

    todo_entity_id = hass.states.async_entity_ids("todo")[0]
    await hass.services.async_call(
        "todo",
        "remove_item",
        {"entity_id": todo_entity_id, "item": item.id},
        blocking=True,
    )
    await hass.async_block_till_done()

    stored = entry.runtime_data.store.get(item.id)
    assert stored.state == ItemState.REJECTED
