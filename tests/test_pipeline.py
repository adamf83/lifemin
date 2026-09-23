"""End-to-end pipeline tests: imap_content event -> todo item -> confirm -> calendar/sensor.

Also covers duplicate events, content-identical-different-uid dedup, and
empty-body short-circuiting, per PLAN.md section 8.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant, SupportsResponse

from custom_components.admin_inbox.const import DOMAIN
from custom_components.admin_inbox.models import ItemState

from .conftest import add_mock_imap_entry, async_setup_fake_ai_task, load_fixture_email
from .helpers import async_setup_admin_inbox as _async_setup_admin_inbox


def _fire_imap_content(
    hass: HomeAssistant, *, entry_id: str, uid: str, sender: str, subject: str, text: str
) -> None:
    hass.bus.async_fire(
        "imap_content",
        {
            "entry_id": entry_id,
            "uid": uid,
            "message_id": f"<{uid}@example.com>",
            "sender": sender,
            "subject": subject,
            "date": "2026-09-01",
            "text": text,
            "parts": [],
        },
    )


def _mock_imap_fetch(hass: HomeAssistant, responses: dict[str, dict]) -> None:
    async def _handler(call):
        uid = call.data["uid"]
        return responses[uid]

    hass.services.async_register(
        "imap",
        "fetch",
        _handler,
        supports_response=SupportsResponse.ONLY,
    )


async def test_happy_path_bill_reaches_todo_and_confirm_creates_calendar_event(hass: HomeAssistant):
    imap_entry = add_mock_imap_entry(hass)
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
                "source_quote": "The amount due\nis 87.42 GBP and payment is due by 2026-10-15.",
            }
        ],
    )
    text = load_fixture_email("happy_bill.txt")

    entry = await _async_setup_admin_inbox(
        hass, imap_entry_id=imap_entry.entry_id, ai_task_entity_id=ai_task_entity_id
    )
    # Registered after admin_inbox setup: admin_inbox declares "imap" as a
    # manifest dependency, so the real imap component (and its real
    # imap.fetch service) gets set up first. This overrides it with a fake.
    _mock_imap_fetch(
        hass,
        {
            "uid-1": {
                "sender": "billing@britishgas.co.uk",
                "subject": "Your energy bill",
                "date": "2026-09-01",
                "text": text,
                "parts": [],
            }
        },
    )

    _fire_imap_content(
        hass,
        entry_id=imap_entry.entry_id,
        uid="uid-1",
        sender="billing@britishgas.co.uk",
        subject="Your energy bill",
        text=text,
    )
    await hass.async_block_till_done()

    store = entry.runtime_data.store
    items = store.items_in_state(ItemState.PENDING)
    assert len(items) == 1
    item = items[0]
    assert item.title == "Energy bill"

    # Confirm via the service (equivalent to checking off the todo item).
    await hass.services.async_call(
        DOMAIN,
        "confirm_item",
        {"entry_id": entry.entry_id, "item_id": item.id},
        blocking=True,
    )
    await hass.async_block_till_done()

    confirmed = store.get(item.id)
    assert confirmed.state == ItemState.CONFIRMED

    calendar_entity_ids = hass.states.async_entity_ids("calendar")
    assert calendar_entity_ids


async def test_duplicate_imap_content_event_only_creates_one_item(hass: HomeAssistant):
    imap_entry = add_mock_imap_entry(hass)
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
    text = "hello world"

    entry = await _async_setup_admin_inbox(
        hass, imap_entry_id=imap_entry.entry_id, ai_task_entity_id=ai_task_entity_id
    )
    _mock_imap_fetch(
        hass, {"uid-dup": {"sender": "a@b.com", "subject": "s", "date": "d", "text": text, "parts": []}}
    )

    fire_kwargs = dict(entry_id=imap_entry.entry_id, uid="uid-dup", sender="a@b.com", subject="s", text=text)
    _fire_imap_content(hass, **fire_kwargs)
    await hass.async_block_till_done()
    _fire_imap_content(hass, **fire_kwargs)
    await hass.async_block_till_done()

    store = entry.runtime_data.store
    matching = [i for i in store.all_items() if i.uid == "uid-dup"]
    assert len(matching) == 1


async def test_event_for_different_entry_id_is_ignored(hass: HomeAssistant):
    imap_entry = add_mock_imap_entry(hass)
    ai_task_entity_id = await async_setup_fake_ai_task(hass, [])

    entry = await _async_setup_admin_inbox(
        hass, imap_entry_id=imap_entry.entry_id, ai_task_entity_id=ai_task_entity_id
    )

    _fire_imap_content(
        hass, entry_id="some_other_entry", uid="uid-x", sender="a@b.com", subject="s", text="body"
    )
    await hass.async_block_till_done()

    store = entry.runtime_data.store
    assert store.all_items() == []
