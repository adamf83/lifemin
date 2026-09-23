"""Tests for repair issues: store failure, AI Task entity missing, sustained
fetch failure, IMAP entry removed -- the four conditions from PLAN.md section 4."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir

from custom_components.admin_inbox.const import (
    CONF_FETCH_FAILURE_THRESHOLD,
    DOMAIN,
    ISSUE_AI_TASK_ENTITY_MISSING,
    ISSUE_IMAP_ENTRY_REMOVED,
    ISSUE_IMAP_FETCH_DEGRADED,
)
from custom_components.admin_inbox.repairs import async_check_imap_entry
from custom_components.admin_inbox.store import StoreSchemaUnsupportedError

from .conftest import add_mock_imap_entry, async_setup_fake_ai_task
from .helpers import async_setup_admin_inbox


async def test_imap_entry_removed_raises_and_clears_issue(hass: HomeAssistant):
    imap_entry = add_mock_imap_entry(hass)
    ai_task_entity_id = await async_setup_fake_ai_task(hass, [])
    entry = await async_setup_admin_inbox(
        hass, imap_entry_id=imap_entry.entry_id, ai_task_entity_id=ai_task_entity_id
    )

    registry = ir.async_get(hass)
    issue_id = f"{ISSUE_IMAP_ENTRY_REMOVED}_{entry.entry_id}"
    assert registry.async_get_issue(DOMAIN, issue_id) is None

    hass.config_entries._entries.pop(imap_entry.entry_id)
    missing = async_check_imap_entry(hass, entry)
    assert missing is True
    assert registry.async_get_issue(DOMAIN, issue_id) is not None


async def test_ai_task_entity_missing_raises_issue(hass: HomeAssistant):
    from homeassistant.setup import async_setup_component

    imap_entry = add_mock_imap_entry(hass)
    assert await async_setup_component(hass, "homeassistant", {})
    entry = await async_setup_admin_inbox(
        hass, imap_entry_id=imap_entry.entry_id, ai_task_entity_id="ai_task.does_not_exist"
    )

    async def _handler(call):
        return {"sender": "a@b.com", "subject": "s", "date": "d", "text": "some body content", "parts": []}

    hass.services.async_register("imap", "fetch", _handler, supports_response=SupportsResponse.ONLY)

    hass.bus.async_fire(
        "imap_content",
        {"entry_id": imap_entry.entry_id, "uid": "uid-1", "message_id": "m1"},
    )
    await hass.async_block_till_done()

    registry = ir.async_get(hass)
    issue_id = f"{ISSUE_AI_TASK_ENTITY_MISSING}_{entry.entry_id}"
    assert registry.async_get_issue(DOMAIN, issue_id) is not None


async def test_sustained_fetch_failures_raise_issue(hass: HomeAssistant):
    imap_entry = add_mock_imap_entry(hass)
    ai_task_entity_id = await async_setup_fake_ai_task(hass, [])
    entry = await async_setup_admin_inbox(
        hass,
        imap_entry_id=imap_entry.entry_id,
        ai_task_entity_id=ai_task_entity_id,
        options={CONF_FETCH_FAILURE_THRESHOLD: 3},
    )

    async def _failing_handler(call):
        raise HomeAssistantError("IMAP connection dropped")

    hass.services.async_register(
        "imap", "fetch", _failing_handler, supports_response=SupportsResponse.ONLY
    )

    for i in range(3):
        hass.bus.async_fire(
            "imap_content",
            {"entry_id": imap_entry.entry_id, "uid": f"uid-{i}", "message_id": f"m{i}"},
        )
        await hass.async_block_till_done()

    registry = ir.async_get(hass)
    issue_id = f"{ISSUE_IMAP_FETCH_DEGRADED}_{entry.entry_id}"
    assert registry.async_get_issue(DOMAIN, issue_id) is not None


async def test_store_schema_unsupported_raises_issue(hass: HomeAssistant):
    imap_entry = add_mock_imap_entry(hass)
    ai_task_entity_id = await async_setup_fake_ai_task(hass, [])

    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.admin_inbox.const import (
        CONF_AI_TASK_ENTITY_ID,
        CONF_IMAP_ENTRY_ID,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Admin Inbox (Mail Test)",
        data={CONF_IMAP_ENTRY_ID: imap_entry.entry_id, CONF_AI_TASK_ENTITY_ID: ai_task_entity_id},
        options={},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.admin_inbox.store.AdminInboxStore.async_load",
        new=AsyncMock(side_effect=StoreSchemaUnsupportedError("too new")),
    ):
        result = await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert result is False

    registry = ir.async_get(hass)
    from custom_components.admin_inbox.const import ISSUE_STORE_SCHEMA_UNSUPPORTED

    issue_id = f"{ISSUE_STORE_SCHEMA_UNSUPPORTED}_{entry.entry_id}"
    assert registry.async_get_issue(DOMAIN, issue_id) is not None
