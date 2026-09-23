"""End-to-end tests for the webhook mail source (e.g. Power Automate -> HA).

Mirrors test_pipeline.py's IMAP-source coverage but posts directly to the
registered webhook instead of firing an imap_content event -- there is no
separate fetch step for this source, since the payload already carries the
full body (see webhook_listener.py / pipeline.async_handle_pushed_email).
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.admin_inbox.const import CONF_WEBHOOK_ID
from custom_components.admin_inbox.models import ItemState

from .conftest import async_setup_fake_ai_task
from .helpers import async_setup_admin_inbox_webhook


async def test_happy_path_bill_via_webhook_reaches_todo(
    hass: HomeAssistant, hass_client_no_auth
):
    ai_task_entity_id = await async_setup_fake_ai_task(
        hass,
        [
            {
                "kind": "bill",
                "title": "Energy bill",
                "counterparty": "British Gas",
                "amount": 87.42,
                "currency": "GBP",
                "due_date": "2026-10-15",
                "confidence": 0.95,
                "source_quote": "Amount due: 87.42 GBP, due 2026-10-15.",
            }
        ],
    )
    entry = await async_setup_admin_inbox_webhook(hass, ai_task_entity_id=ai_task_entity_id)
    webhook_id = entry.data[CONF_WEBHOOK_ID]

    client = await hass_client_no_auth()
    resp = await client.post(
        f"/api/webhook/{webhook_id}",
        json={
            "message_id": "outlook-msg-1",
            "sender": "billing@britishgas.co.uk",
            "subject": "Your energy bill",
            "date": "2026-09-01T00:00:00Z",
            "text": "Amount due: 87.42 GBP, due 2026-10-15.",
        },
    )
    assert resp.status == 200
    await hass.async_block_till_done()

    store = entry.runtime_data.store
    items = store.items_in_state(ItemState.PENDING)
    assert len(items) == 1
    assert items[0].title == "Energy bill"
    assert items[0].uid == "outlook-msg-1"


async def test_missing_message_id_rejected(hass: HomeAssistant, hass_client_no_auth):
    ai_task_entity_id = await async_setup_fake_ai_task(hass, [])
    entry = await async_setup_admin_inbox_webhook(hass, ai_task_entity_id=ai_task_entity_id)
    webhook_id = entry.data[CONF_WEBHOOK_ID]

    client = await hass_client_no_auth()
    resp = await client.post(
        f"/api/webhook/{webhook_id}",
        json={"sender": "a@b.com", "subject": "s", "text": "body"},
    )
    assert resp.status == 400

    store = entry.runtime_data.store
    assert store.all_items() == []


async def test_duplicate_message_id_only_creates_one_item(
    hass: HomeAssistant, hass_client_no_auth
):
    ai_task_entity_id = await async_setup_fake_ai_task(
        hass,
        [
            {
                "kind": "other",
                "title": "t",
                "counterparty": "c",
                "confidence": 0.1,
                "source_quote": "hello",
                "due_date": "2026-10-01",
            }
        ],
    )
    entry = await async_setup_admin_inbox_webhook(hass, ai_task_entity_id=ai_task_entity_id)
    webhook_id = entry.data[CONF_WEBHOOK_ID]

    client = await hass_client_no_auth()
    payload = {
        "message_id": "outlook-msg-dup",
        "sender": "a@b.com",
        "subject": "s",
        "text": "hello",
    }
    await client.post(f"/api/webhook/{webhook_id}", json=payload)
    await hass.async_block_till_done()
    await client.post(f"/api/webhook/{webhook_id}", json=payload)
    await hass.async_block_till_done()

    store = entry.runtime_data.store
    matching = [i for i in store.all_items() if i.uid == "outlook-msg-dup"]
    assert len(matching) == 1


async def test_non_json_body_rejected(hass: HomeAssistant, hass_client_no_auth):
    ai_task_entity_id = await async_setup_fake_ai_task(hass, [])
    entry = await async_setup_admin_inbox_webhook(hass, ai_task_entity_id=ai_task_entity_id)
    webhook_id = entry.data[CONF_WEBHOOK_ID]

    client = await hass_client_no_auth()
    resp = await client.post(f"/api/webhook/{webhook_id}", data="not json")
    assert resp.status == 400
