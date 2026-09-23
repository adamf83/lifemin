"""Shared test helpers for entity-rendering tests (calendar/todo/sensor)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from homeassistant.components import webhook
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util.ulid import ulid_now
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.admin_inbox.const import (
    CONF_AI_TASK_ENTITY_ID,
    CONF_IMAP_ENTRY_ID,
    CONF_SOURCE_TYPE,
    CONF_WEBHOOK_ID,
    DOMAIN,
    SOURCE_TYPE_IMAP,
    SOURCE_TYPE_WEBHOOK,
)
from custom_components.admin_inbox.models import ItemState, MessageRef, StoredItem


async def async_setup_admin_inbox(
    hass: HomeAssistant, *, imap_entry_id: str, ai_task_entity_id: str, options: dict | None = None
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Admin Inbox (Mail Test)",
        data={
            CONF_SOURCE_TYPE: SOURCE_TYPE_IMAP,
            CONF_IMAP_ENTRY_ID: imap_entry_id,
            CONF_AI_TASK_ENTITY_ID: ai_task_entity_id,
        },
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def async_setup_admin_inbox_webhook(
    hass: HomeAssistant, *, ai_task_entity_id: str, options: dict | None = None
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Admin Inbox (Webhook)",
        data={
            CONF_SOURCE_TYPE: SOURCE_TYPE_WEBHOOK,
            CONF_WEBHOOK_ID: webhook.async_generate_id(),
            CONF_AI_TASK_ENTITY_ID: ai_task_entity_id,
        },
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def make_confirmed_item(
    *,
    entry_id: str,
    uid: str,
    due_date: date | None = None,
    event_date: date | None = None,
    amount: Decimal | None = Decimal("87.42"),
    currency: str | None = "GBP",
    title: str = "Energy bill",
    counterparty: str = "British Gas",
    kind: str = "bill",
) -> StoredItem:
    now = dt_util.utcnow()
    return StoredItem(
        id=ulid_now(),
        entry_id=entry_id,
        uid=uid,
        content_hash=f"hash-{uid}",
        state=ItemState.CONFIRMED,
        created_at=now,
        updated_at=now,
        kind=kind,
        title=title,
        counterparty=counterparty,
        amount=amount,
        currency=currency,
        due_date=due_date,
        event_date=event_date,
        confidence=0.9,
        source_quote="quote",
        message_ref=MessageRef(
            entry_id=entry_id, uid=uid, message_id=None, subject="s", sender="a@b.com", date="d"
        ),
        known_uids=[uid],
    )
