"""Config flow and options flow for admin_inbox."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback

from .const import (
    CONF_AI_TASK_ENTITY_ID,
    CONF_DEDUP_PRUNE_DAYS,
    CONF_DUE_DATE_FUTURE_YEARS,
    CONF_DUE_DATE_PAST_YEARS,
    CONF_FETCH_FAILURE_THRESHOLD,
    CONF_IMAP_ENTRY_ID,
    CONF_KEYWORDS,
    CONF_RECONCILE_INTERVAL_MINUTES,
    CONF_RETENTION_DAYS,
    CONF_SENDER_ALLOWLIST,
    DEFAULT_DEDUP_PRUNE_DAYS,
    DEFAULT_DUE_DATE_FUTURE_YEARS,
    DEFAULT_DUE_DATE_PAST_YEARS,
    DEFAULT_FETCH_FAILURE_THRESHOLD,
    DEFAULT_RECONCILE_INTERVAL_MINUTES,
    DEFAULT_RETENTION_DAYS,
    DOMAIN,
)


def _parse_list(raw: str) -> list[str]:
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _format_list(values: list[str]) -> str:
    return "\n".join(values)


def _available_imap_entries(hass, exclude_configured: bool) -> dict[str, str]:
    imap_entries = [
        e
        for e in hass.config_entries.async_entries("imap")
        if e.state == ConfigEntryState.LOADED
    ]
    if exclude_configured:
        already_used = {
            e.data[CONF_IMAP_ENTRY_ID] for e in hass.config_entries.async_entries(DOMAIN)
        }
        imap_entries = [e for e in imap_entries if e.entry_id not in already_used]
    return {e.entry_id: e.title for e in imap_entries}


def _available_ai_task_entities(hass) -> list[str]:
    return sorted(hass.states.async_entity_ids("ai_task"))


class AdminInboxConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for admin_inbox."""

    VERSION = 1

    def __init__(self) -> None:
        self._imap_entry_id: str | None = None
        self._ai_task_entity_id: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        available = _available_imap_entries(self.hass, exclude_configured=True)
        if not available:
            return self.async_abort(reason="no_imap_entries_available")

        if user_input is not None:
            imap_entry_id = user_input[CONF_IMAP_ENTRY_ID]
            await self.async_set_unique_id(imap_entry_id)
            self._abort_if_unique_id_configured()
            self._imap_entry_id = imap_entry_id
            return await self.async_step_ai_task()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_IMAP_ENTRY_ID): vol.In(available)}),
            errors=errors,
        )

    async def async_step_ai_task(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entities = _available_ai_task_entities(self.hass)
        if not entities:
            return self.async_abort(reason="no_ai_task_entities_available")

        if user_input is not None:
            self._ai_task_entity_id = user_input[CONF_AI_TASK_ENTITY_ID]
            return await self.async_step_filters()

        return self.async_show_form(
            step_id="ai_task",
            data_schema=vol.Schema({vol.Required(CONF_AI_TASK_ENTITY_ID): vol.In(entities)}),
        )

    async def async_step_filters(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            assert self._imap_entry_id is not None
            imap_entry = self.hass.config_entries.async_get_entry(self._imap_entry_id)
            title = f"Admin Inbox ({imap_entry.title if imap_entry else self._imap_entry_id})"
            return self.async_create_entry(
                title=title,
                data={
                    CONF_IMAP_ENTRY_ID: self._imap_entry_id,
                    CONF_AI_TASK_ENTITY_ID: self._ai_task_entity_id,
                },
                options={
                    CONF_SENDER_ALLOWLIST: _parse_list(user_input.get(CONF_SENDER_ALLOWLIST, "")),
                    CONF_KEYWORDS: _parse_list(user_input.get(CONF_KEYWORDS, "")),
                },
            )

        return self.async_show_form(
            step_id="filters",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_SENDER_ALLOWLIST, default=""): str,
                    vol.Optional(CONF_KEYWORDS, default=""): str,
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AdminInboxOptionsFlow:
        return AdminInboxOptionsFlow()


class AdminInboxOptionsFlow(OptionsFlow):
    """Options flow: edit AI Task entity, allowlist, keywords, and advanced tuning."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entities = _available_ai_task_entities(self.hass)
        current = self.config_entry.options

        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_SENDER_ALLOWLIST: _parse_list(user_input.get(CONF_SENDER_ALLOWLIST, "")),
                    CONF_KEYWORDS: _parse_list(user_input.get(CONF_KEYWORDS, "")),
                    CONF_AI_TASK_ENTITY_ID: user_input.get(
                        CONF_AI_TASK_ENTITY_ID,
                        self.config_entry.data.get(CONF_AI_TASK_ENTITY_ID),
                    ),
                    CONF_RETENTION_DAYS: user_input.get(
                        CONF_RETENTION_DAYS, DEFAULT_RETENTION_DAYS
                    ),
                    CONF_DEDUP_PRUNE_DAYS: user_input.get(
                        CONF_DEDUP_PRUNE_DAYS, DEFAULT_DEDUP_PRUNE_DAYS
                    ),
                    CONF_RECONCILE_INTERVAL_MINUTES: user_input.get(
                        CONF_RECONCILE_INTERVAL_MINUTES, DEFAULT_RECONCILE_INTERVAL_MINUTES
                    ),
                    CONF_FETCH_FAILURE_THRESHOLD: user_input.get(
                        CONF_FETCH_FAILURE_THRESHOLD, DEFAULT_FETCH_FAILURE_THRESHOLD
                    ),
                    CONF_DUE_DATE_PAST_YEARS: user_input.get(
                        CONF_DUE_DATE_PAST_YEARS, DEFAULT_DUE_DATE_PAST_YEARS
                    ),
                    CONF_DUE_DATE_FUTURE_YEARS: user_input.get(
                        CONF_DUE_DATE_FUTURE_YEARS, DEFAULT_DUE_DATE_FUTURE_YEARS
                    ),
                },
            )

        default_ai_task = current.get(
            CONF_AI_TASK_ENTITY_ID, self.config_entry.data.get(CONF_AI_TASK_ENTITY_ID)
        )
        ai_task_schema = (
            vol.In(entities) if entities else str
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_AI_TASK_ENTITY_ID, default=default_ai_task
                    ): ai_task_schema,
                    vol.Optional(
                        CONF_SENDER_ALLOWLIST,
                        default=_format_list(current.get(CONF_SENDER_ALLOWLIST, [])),
                    ): str,
                    vol.Optional(
                        CONF_KEYWORDS,
                        default=_format_list(current.get(CONF_KEYWORDS, [])),
                    ): str,
                    vol.Optional(
                        CONF_RETENTION_DAYS,
                        default=current.get(CONF_RETENTION_DAYS, DEFAULT_RETENTION_DAYS),
                    ): vol.Coerce(int),
                    vol.Optional(
                        CONF_DEDUP_PRUNE_DAYS,
                        default=current.get(CONF_DEDUP_PRUNE_DAYS, DEFAULT_DEDUP_PRUNE_DAYS),
                    ): vol.Coerce(int),
                    vol.Optional(
                        CONF_RECONCILE_INTERVAL_MINUTES,
                        default=current.get(
                            CONF_RECONCILE_INTERVAL_MINUTES, DEFAULT_RECONCILE_INTERVAL_MINUTES
                        ),
                    ): vol.Coerce(int),
                    vol.Optional(
                        CONF_FETCH_FAILURE_THRESHOLD,
                        default=current.get(
                            CONF_FETCH_FAILURE_THRESHOLD, DEFAULT_FETCH_FAILURE_THRESHOLD
                        ),
                    ): vol.Coerce(int),
                    vol.Optional(
                        CONF_DUE_DATE_PAST_YEARS,
                        default=current.get(
                            CONF_DUE_DATE_PAST_YEARS, DEFAULT_DUE_DATE_PAST_YEARS
                        ),
                    ): vol.Coerce(int),
                    vol.Optional(
                        CONF_DUE_DATE_FUTURE_YEARS,
                        default=current.get(
                            CONF_DUE_DATE_FUTURE_YEARS, DEFAULT_DUE_DATE_FUTURE_YEARS
                        ),
                    ): vol.Coerce(int),
                }
            ),
        )
