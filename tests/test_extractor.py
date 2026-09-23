"""Tests for extractor.py: the real async_generate_data call path.

Uses a FakeAITaskEntity wired in as a genuine ai_task platform entity
(conftest.async_setup_fake_ai_task), not a monkeypatch of
async_generate_data, specifically to prove the STRUCTURE schema this
integration builds is accepted by the real ai_task entity/task machinery
end-to-end -- this is the class of surprise PLAN.md section 10 risk 5
flags as unverified from source reading alone.
"""
from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError

from custom_components.admin_inbox.extractor import async_extract
from custom_components.admin_inbox.models import ExtractionFailure, RawEmail

from .conftest import async_setup_fake_ai_task, load_fixture_email


async def test_extract_happy_path(hass):
    email = RawEmail(
        uid="1",
        sender="billing@britishgas.co.uk",
        subject="Your energy bill",
        date="2026-09-01",
        text=load_fixture_email("happy_bill.txt"),
    )
    response = {
        "kind": "bill",
        "title": "Energy bill",
        "counterparty": "British Gas",
        "amount": 87.42,
        "currency": "GBP",
        "due_date": "2026-10-15",
        "confidence": 0.95,
        "source_quote": "The amount due\nis 87.42 GBP and payment is due by 2026-10-15.",
    }
    entity_id = await async_setup_fake_ai_task(hass, [response])

    result = await async_extract(hass, email, ai_task_entity_id=entity_id)

    assert result == response


async def test_extract_retries_once_then_fails(hass):
    email = RawEmail(uid="1", sender="a@b.com", subject="s", date="d", text="body")
    entity_id = await async_setup_fake_ai_task(
        hass, [HomeAssistantError("boom"), HomeAssistantError("boom again")]
    )

    result = await async_extract(hass, email, ai_task_entity_id=entity_id)

    assert isinstance(result, ExtractionFailure)


async def test_extract_recovers_on_second_attempt(hass):
    email = RawEmail(uid="1", sender="a@b.com", subject="s", date="d", text="body")
    good_response = {
        "kind": "other",
        "title": "t",
        "counterparty": "c",
        "confidence": 0.1,
        "source_quote": "q",
    }
    entity_id = await async_setup_fake_ai_task(
        hass, [HomeAssistantError("boom"), good_response]
    )

    result = await async_extract(hass, email, ai_task_entity_id=entity_id)

    assert result == good_response
