"""Tests for config_flow.py: config flow and options flow."""
from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.admin_inbox.const import (
    CONF_AI_TASK_ENTITY_ID,
    CONF_IMAP_ENTRY_ID,
    CONF_KEYWORDS,
    CONF_SENDER_ALLOWLIST,
    DOMAIN,
)

from .conftest import add_mock_imap_entry, async_setup_fake_ai_task


async def test_full_config_flow_happy_path(hass: HomeAssistant):
    imap_entry = add_mock_imap_entry(hass)
    ai_task_entity_id = await async_setup_fake_ai_task(hass, [])

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_IMAP_ENTRY_ID: imap_entry.entry_id}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "ai_task"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_AI_TASK_ENTITY_ID: ai_task_entity_id}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "filters"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_SENDER_ALLOWLIST: "billing@britishgas.co.uk\n@acme.com", CONF_KEYWORDS: "bill\nrenewal"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_IMAP_ENTRY_ID] == imap_entry.entry_id
    assert result["data"][CONF_AI_TASK_ENTITY_ID] == ai_task_entity_id
    assert result["options"][CONF_SENDER_ALLOWLIST] == ["billing@britishgas.co.uk", "@acme.com"]
    assert result["options"][CONF_KEYWORDS] == ["bill", "renewal"]


async def test_cannot_configure_same_imap_entry_twice(hass: HomeAssistant):
    imap_entry = add_mock_imap_entry(hass)
    ai_task_entity_id = await async_setup_fake_ai_task(hass, [])

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_IMAP_ENTRY_ID: imap_entry.entry_id}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_AI_TASK_ENTITY_ID: ai_task_entity_id}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SENDER_ALLOWLIST: "", CONF_KEYWORDS: ""}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    result2 = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "no_imap_entries_available"


async def test_options_flow_updates_allowlist(hass: HomeAssistant):
    imap_entry = add_mock_imap_entry(hass)
    ai_task_entity_id = await async_setup_fake_ai_task(hass, [])

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_IMAP_ENTRY_ID: imap_entry.entry_id}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_AI_TASK_ENTITY_ID: ai_task_entity_id}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SENDER_ALLOWLIST: "", CONF_KEYWORDS: ""}
    )
    entry = hass.config_entries.async_get_entry(result["result"].entry_id)

    options_result = await hass.config_entries.options.async_init(entry.entry_id)
    assert options_result["type"] is FlowResultType.FORM

    options_result = await hass.config_entries.options.async_configure(
        options_result["flow_id"],
        {
            CONF_AI_TASK_ENTITY_ID: ai_task_entity_id,
            CONF_SENDER_ALLOWLIST: "new@sender.com",
            CONF_KEYWORDS: "",
            "retention_days": 400,
            "dedup_prune_days": 400,
            "reconcile_interval_minutes": 60,
            "fetch_failure_threshold": 5,
            "due_date_past_years": 2,
            "due_date_future_years": 5,
        },
    )
    assert options_result["type"] is FlowResultType.CREATE_ENTRY
    assert options_result["data"][CONF_SENDER_ALLOWLIST] == ["new@sender.com"]
