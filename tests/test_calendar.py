"""Entity rendering tests for calendar.py, against a pre-seeded store."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.admin_inbox.models import ItemState

from .conftest import add_mock_imap_entry, async_setup_fake_ai_task
from .helpers import async_setup_admin_inbox, make_confirmed_item


async def test_confirmed_item_with_due_date_appears_as_calendar_event(hass: HomeAssistant):
    imap_entry = add_mock_imap_entry(hass)
    ai_task_entity_id = await async_setup_fake_ai_task(hass, [])
    entry = await async_setup_admin_inbox(
        hass, imap_entry_id=imap_entry.entry_id, ai_task_entity_id=ai_task_entity_id
    )

    store = entry.runtime_data.store
    tomorrow = dt_util.now().date() + timedelta(days=1)
    item = make_confirmed_item(entry_id=entry.entry_id, uid="uid-1", due_date=tomorrow)
    store.save_item(item)
    entry.runtime_data.coordinator.signal_update()
    await hass.async_block_till_done()

    calendar_entity_id = hass.states.async_entity_ids("calendar")[0]
    calendar_entity = hass.data["calendar"].get_entity(calendar_entity_id)

    events = await calendar_entity.async_get_events(
        hass, dt_util.now(), dt_util.now() + timedelta(days=30)
    )
    assert len(events) == 1
    assert "British Gas" in events[0].summary


async def test_pending_item_does_not_appear_on_calendar(hass: HomeAssistant):
    imap_entry = add_mock_imap_entry(hass)
    ai_task_entity_id = await async_setup_fake_ai_task(hass, [])
    entry = await async_setup_admin_inbox(
        hass, imap_entry_id=imap_entry.entry_id, ai_task_entity_id=ai_task_entity_id
    )

    store = entry.runtime_data.store
    item = make_confirmed_item(
        entry_id=entry.entry_id, uid="uid-2", due_date=dt_util.now().date()
    )
    item.state = ItemState.PENDING
    store.save_item(item)
    entry.runtime_data.coordinator.signal_update()
    await hass.async_block_till_done()

    calendar_entity_id = hass.states.async_entity_ids("calendar")[0]
    calendar_entity = hass.data["calendar"].get_entity(calendar_entity_id)

    events = await calendar_entity.async_get_events(
        hass, dt_util.now() - timedelta(days=1), dt_util.now() + timedelta(days=30)
    )
    assert events == []
