"""End-to-end tests for the admin_inbox.upload_document service.

The manual-upload path for mailboxes reachable by neither IMAP nor a
webhook automation (e.g. no Power Automate license) -- see PLAN.md
section 1b. Posts a real file through HA's file_upload HTTP endpoint
(mirroring how the frontend's FileSelector widget works), then calls the
service with the returned file_id.
"""
from __future__ import annotations

from aiohttp import FormData
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.admin_inbox.const import ATTR_ENTRY_ID, ATTR_FILE, DOMAIN
from custom_components.admin_inbox.models import ItemState

from .conftest import add_mock_imap_entry, async_setup_fake_ai_task
from .helpers import async_setup_admin_inbox


async def _upload_file(hass_client, *, filename: str, content: bytes) -> str:
    client = await hass_client()
    data = FormData()
    data.add_field("file", content, filename=filename, content_type="application/octet-stream")
    resp = await client.post("/api/file_upload", data=data)
    assert resp.status == 200
    return (await resp.json())["file_id"]


async def test_upload_document_happy_path(hass: HomeAssistant, hass_client):
    imap_entry = add_mock_imap_entry(hass)
    ai_task_entity_id = await async_setup_fake_ai_task(
        hass,
        [
            {
                "kind": "bill",
                "title": "Electric bill",
                "counterparty": "Acme Energy",
                "amount": 42.0,
                "currency": "GBP",
                "due_date": "2026-10-01",
                "confidence": 0.9,
                "source_quote": "Amount due 42.00 GBP by 2026-10-01",
            }
        ],
        supports_attachments=True,
    )
    entry = await async_setup_admin_inbox(
        hass, imap_entry_id=imap_entry.entry_id, ai_task_entity_id=ai_task_entity_id
    )

    file_id = await _upload_file(hass_client, filename="bill.jpg", content=b"\xff\xd8\xff fake jpeg")

    await hass.services.async_call(
        DOMAIN,
        "upload_document",
        {
            ATTR_ENTRY_ID: entry.entry_id,
            ATTR_FILE: file_id,
            "sender": "Acme Energy",
            "subject": "Electric bill",
            "notes": "found in the post",
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    store = entry.runtime_data.store
    items = store.items_in_state(ItemState.PENDING)
    assert len(items) == 1
    assert items[0].title == "Electric bill"
    assert items[0].uid.startswith("upload-")


async def test_upload_document_rejects_disallowed_content_type(
    hass: HomeAssistant, hass_client
):
    imap_entry = add_mock_imap_entry(hass)
    ai_task_entity_id = await async_setup_fake_ai_task(hass, [], supports_attachments=True)
    entry = await async_setup_admin_inbox(
        hass, imap_entry_id=imap_entry.entry_id, ai_task_entity_id=ai_task_entity_id
    )

    file_id = await _upload_file(hass_client, filename="malware.exe", content=b"MZ\x90\x00")

    try:
        await hass.services.async_call(
            DOMAIN,
            "upload_document",
            {ATTR_ENTRY_ID: entry.entry_id, ATTR_FILE: file_id},
            blocking=True,
        )
        raised = False
    except ServiceValidationError:
        raised = True

    assert raised
    store = entry.runtime_data.store
    assert store.all_items() == []


async def test_upload_document_two_uploads_are_not_merged(hass: HomeAssistant, hass_client):
    """Regression: without notes text, content_hash("") would be identical
    for two different uploads -- must not be treated as a duplicate."""
    imap_entry = add_mock_imap_entry(hass)
    ai_task_entity_id = await async_setup_fake_ai_task(
        hass,
        [
            {
                "kind": "bill",
                "title": "Bill one",
                "counterparty": "c",
                "confidence": 0.9,
                "source_quote": "q1",
                "due_date": "2026-10-01",
            },
            {
                "kind": "bill",
                "title": "Bill two",
                "counterparty": "c",
                "confidence": 0.9,
                "source_quote": "q2",
                "due_date": "2026-10-02",
            },
        ],
        supports_attachments=True,
    )
    entry = await async_setup_admin_inbox(
        hass, imap_entry_id=imap_entry.entry_id, ai_task_entity_id=ai_task_entity_id
    )

    for name in ("a.jpg", "b.jpg"):
        file_id = await _upload_file(hass_client, filename=name, content=b"\xff\xd8\xff fake")
        await hass.services.async_call(
            DOMAIN,
            "upload_document",
            {ATTR_ENTRY_ID: entry.entry_id, ATTR_FILE: file_id},
            blocking=True,
        )
    await hass.async_block_till_done()

    store = entry.runtime_data.store
    titles = {item.title for item in store.items_in_state(ItemState.PENDING)}
    assert titles == {"Bill one", "Bill two"}
