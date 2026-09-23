"""Entity rendering tests for sensor.py."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.admin_inbox.models import ItemState

from .conftest import add_mock_imap_entry, async_setup_fake_ai_task
from .helpers import async_setup_admin_inbox, make_confirmed_item


def _entity_id(hass: HomeAssistant, entry, key: str) -> str:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", "admin_inbox", f"{entry.entry_id}_{key}")
    assert entity_id is not None
    return entity_id


async def test_next_due_date_is_earliest_confirmed_date(hass: HomeAssistant):
    imap_entry = add_mock_imap_entry(hass)
    ai_task_entity_id = await async_setup_fake_ai_task(hass, [])
    entry = await async_setup_admin_inbox(
        hass, imap_entry_id=imap_entry.entry_id, ai_task_entity_id=ai_task_entity_id
    )

    today = dt_util.now().date()
    store = entry.runtime_data.store
    store.save_item(
        make_confirmed_item(entry_id=entry.entry_id, uid="uid-1", due_date=today + timedelta(days=10))
    )
    store.save_item(
        make_confirmed_item(entry_id=entry.entry_id, uid="uid-2", due_date=today + timedelta(days=2))
    )
    entry.runtime_data.coordinator.signal_update()
    await hass.async_block_till_done()

    state = hass.states.get(_entity_id(hass, entry, "next_due"))
    assert state.state == (today + timedelta(days=2)).isoformat()


async def test_amount_due_30d_sums_within_window(hass: HomeAssistant):
    imap_entry = add_mock_imap_entry(hass)
    ai_task_entity_id = await async_setup_fake_ai_task(hass, [])
    entry = await async_setup_admin_inbox(
        hass, imap_entry_id=imap_entry.entry_id, ai_task_entity_id=ai_task_entity_id
    )

    today = dt_util.now().date()
    store = entry.runtime_data.store
    store.save_item(
        make_confirmed_item(
            entry_id=entry.entry_id, uid="uid-1", due_date=today + timedelta(days=5), amount=Decimal("50")
        )
    )
    store.save_item(
        make_confirmed_item(
            entry_id=entry.entry_id, uid="uid-2", due_date=today + timedelta(days=60), amount=Decimal("999")
        )
    )
    entry.runtime_data.coordinator.signal_update()
    await hass.async_block_till_done()

    state = hass.states.get(_entity_id(hass, entry, "amount_due_30d"))
    assert float(state.state) == 50.0


async def test_amount_due_30d_multi_currency_breakdown(hass: HomeAssistant):
    imap_entry = add_mock_imap_entry(hass)
    ai_task_entity_id = await async_setup_fake_ai_task(hass, [])
    entry = await async_setup_admin_inbox(
        hass, imap_entry_id=imap_entry.entry_id, ai_task_entity_id=ai_task_entity_id
    )

    today = dt_util.now().date()
    store = entry.runtime_data.store
    store.save_item(
        make_confirmed_item(
            entry_id=entry.entry_id,
            uid="uid-1",
            due_date=today + timedelta(days=5),
            amount=Decimal("50"),
            currency="GBP",
        )
    )
    store.save_item(
        make_confirmed_item(
            entry_id=entry.entry_id,
            uid="uid-2",
            due_date=today + timedelta(days=6),
            amount=Decimal("30"),
            currency="USD",
        )
    )
    entry.runtime_data.coordinator.signal_update()
    await hass.async_block_till_done()

    state = hass.states.get(_entity_id(hass, entry, "amount_due_30d"))
    assert state.attributes["multi_currency"] is True
    assert state.attributes["breakdown_by_currency"] == {"GBP": 50.0, "USD": 30.0}


async def test_pending_review_count(hass: HomeAssistant):
    imap_entry = add_mock_imap_entry(hass)
    ai_task_entity_id = await async_setup_fake_ai_task(hass, [])
    entry = await async_setup_admin_inbox(
        hass, imap_entry_id=imap_entry.entry_id, ai_task_entity_id=ai_task_entity_id
    )

    store = entry.runtime_data.store
    item = make_confirmed_item(entry_id=entry.entry_id, uid="uid-1")
    item.state = ItemState.PENDING
    store.save_item(item)
    entry.runtime_data.coordinator.signal_update()
    await hass.async_block_till_done()

    state = hass.states.get(_entity_id(hass, entry, "pending_review"))
    assert state.state == "1"
