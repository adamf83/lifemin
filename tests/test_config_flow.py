"""Tests for config_flow.py: config flow and options flow."""
from __future__ import annotations

from homeassistant import config_entries
from homeassistant.components import webhook
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.admin_inbox.const import (
    CONF_AI_TASK_ENTITY_ID,
    CONF_IMAP_ENTRY_ID,
    CONF_KEYWORDS,
    CONF_SENDER_ALLOWLIST,
    CONF_SOURCE_TYPE,
    CONF_WEBHOOK_ID,
    DOMAIN,
    SOURCE_TYPE_IMAP,
    SOURCE_TYPE_WEBHOOK,
)

from .conftest import add_mock_imap_entry, async_setup_fake_ai_task
from .helpers import async_setup_admin_inbox_webhook


async def _start_flow(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return result


async def test_full_config_flow_happy_path_imap(hass: HomeAssistant):
    imap_entry = add_mock_imap_entry(hass)
    ai_task_entity_id = await async_setup_fake_ai_task(hass, [])

    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SOURCE_TYPE: SOURCE_TYPE_IMAP}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "imap"

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
    assert result["data"][CONF_SOURCE_TYPE] == SOURCE_TYPE_IMAP
    assert result["data"][CONF_IMAP_ENTRY_ID] == imap_entry.entry_id
    assert result["data"][CONF_AI_TASK_ENTITY_ID] == ai_task_entity_id
    assert result["options"][CONF_SENDER_ALLOWLIST] == ["billing@britishgas.co.uk", "@acme.com"]
    assert result["options"][CONF_KEYWORDS] == ["bill", "renewal"]


async def test_full_config_flow_happy_path_webhook(hass: HomeAssistant):
    ai_task_entity_id = await async_setup_fake_ai_task(hass, [])

    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SOURCE_TYPE: SOURCE_TYPE_WEBHOOK}
    )
    # Webhook path skips the IMAP-picker step entirely.
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "ai_task"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_AI_TASK_ENTITY_ID: ai_task_entity_id}
    )
    assert result["step_id"] == "filters"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SENDER_ALLOWLIST: "", CONF_KEYWORDS: ""}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "webhook_confirm"
    assert "webhook_url" in result["description_placeholders"]

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SOURCE_TYPE] == SOURCE_TYPE_WEBHOOK
    assert result["data"][CONF_AI_TASK_ENTITY_ID] == ai_task_entity_id
    webhook_id = result["data"][CONF_WEBHOOK_ID]
    assert webhook_id
    # The webhook is actually registered once the entry is set up, not by
    # the flow itself -- confirm the id round-trips into a real URL.
    assert webhook.async_generate_url(hass, webhook_id)


async def test_cannot_configure_same_imap_entry_twice(hass: HomeAssistant):
    imap_entry = add_mock_imap_entry(hass)
    ai_task_entity_id = await async_setup_fake_ai_task(hass, [])

    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SOURCE_TYPE: SOURCE_TYPE_IMAP}
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

    result2 = await _start_flow(hass)
    result2 = await hass.config_entries.flow.async_configure(
        result2["flow_id"], {CONF_SOURCE_TYPE: SOURCE_TYPE_IMAP}
    )
    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "no_imap_entries_available"


async def test_options_flow_updates_allowlist(hass: HomeAssistant):
    imap_entry = add_mock_imap_entry(hass)
    ai_task_entity_id = await async_setup_fake_ai_task(hass, [])

    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SOURCE_TYPE: SOURCE_TYPE_IMAP}
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


async def test_options_flow_shows_webhook_url_for_webhook_source(hass: HomeAssistant):
    ai_task_entity_id = await async_setup_fake_ai_task(hass, [])
    entry = await async_setup_admin_inbox_webhook(hass, ai_task_entity_id=ai_task_entity_id)

    options_result = await hass.config_entries.options.async_init(entry.entry_id)

    assert options_result["type"] is FlowResultType.FORM
    webhook_id = entry.data[CONF_WEBHOOK_ID]
    expected_url = webhook.async_generate_url(hass, webhook_id)
    assert options_result["description_placeholders"]["webhook_url"] == expected_url


async def test_options_flow_webhook_url_not_applicable_for_imap_source(hass: HomeAssistant):
    imap_entry = add_mock_imap_entry(hass)
    ai_task_entity_id = await async_setup_fake_ai_task(hass, [])

    result = await _start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SOURCE_TYPE: SOURCE_TYPE_IMAP}
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

    assert "Not applicable" in options_result["description_placeholders"]["webhook_url"]
