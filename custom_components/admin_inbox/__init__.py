"""The admin_inbox integration."""
from __future__ import annotations

import logging
from datetime import timedelta

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_change, async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_ENTRY_ID,
    ATTR_ITEM_ID,
    CONF_IMAP_ENTRY_ID,
    CONF_RECONCILE_INTERVAL_MINUTES,
    DEFAULT_RECONCILE_INTERVAL_MINUTES,
    DOMAIN,
    ISSUE_STORE_SCHEMA_UNSUPPORTED,
    ISSUE_STORE_UNAVAILABLE,
    PLATFORMS,
    SERVICE_CONFIRM_ITEM,
    SERVICE_RECONCILE,
    SERVICE_REJECT_ITEM,
)
from .coordinator import AdminInboxCoordinator
from .listener import AdminInboxListener
from .models import ItemState
from .pipeline import AdminInboxPipeline
from .repairs import async_check_imap_entry
from .runtime_data import AdminInboxConfigEntry, AdminInboxRuntimeData
from .store import AdminInboxStore, StoreSchemaUnsupportedError

_LOGGER = logging.getLogger(__name__)

CONFIRM_ITEM_SCHEMA = vol.Schema(
    {vol.Required(ATTR_ENTRY_ID): cv.string, vol.Required(ATTR_ITEM_ID): cv.string}
)
REJECT_ITEM_SCHEMA = CONFIRM_ITEM_SCHEMA
RECONCILE_SCHEMA = vol.Schema({vol.Required(ATTR_ENTRY_ID): cv.string})


async def async_setup_entry(hass: HomeAssistant, entry: AdminInboxConfigEntry) -> bool:
    """Set up admin_inbox from a config entry."""
    store = AdminInboxStore(hass, entry.entry_id)
    try:
        await store.async_load()
    except StoreSchemaUnsupportedError as err:
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"{ISSUE_STORE_SCHEMA_UNSUPPORTED}_{entry.entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_STORE_SCHEMA_UNSUPPORTED,
        )
        raise ConfigEntryNotReady(str(err)) from err
    except Exception as err:  # noqa: BLE001 - disk full, corrupted file, etc.
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"{ISSUE_STORE_UNAVAILABLE}_{entry.entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_STORE_UNAVAILABLE,
        )
        raise ConfigEntryNotReady(str(err)) from err

    async_check_imap_entry(hass, entry)

    coordinator = AdminInboxCoordinator(hass, entry, store)
    await coordinator.async_refresh()

    pipeline = AdminInboxPipeline(hass, entry, store, coordinator.signal_update)

    imap_entry_id = entry.data[CONF_IMAP_ENTRY_ID]
    listener = AdminInboxListener(hass, imap_entry_id, pipeline.async_handle_fetch_request)
    listener.async_start()

    entry.runtime_data = AdminInboxRuntimeData(
        store=store, coordinator=coordinator, pipeline=pipeline, listener=listener
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    interval_minutes = entry.options.get(
        CONF_RECONCILE_INTERVAL_MINUTES, DEFAULT_RECONCILE_INTERVAL_MINUTES
    )

    async def _async_reconcile_tick(_now) -> None:
        async_check_imap_entry(hass, entry)
        await pipeline.async_reconcile()
        pipeline.async_prune()

    entry.async_on_unload(
        async_track_time_interval(
            hass, _async_reconcile_tick, timedelta(minutes=interval_minutes)
        )
    )

    async def _async_daily_due_check(_now) -> None:
        coordinator.async_check_due_items()

    entry.async_on_unload(
        async_track_time_change(hass, _async_daily_due_check, hour=0, minute=5, second=0)
    )
    entry.async_on_unload(listener.async_stop)

    _async_register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: AdminInboxConfigEntry) -> bool:
    """Unload an admin_inbox config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.store.async_save_now()
    return unload_ok


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_CONFIRM_ITEM):
        return

    async def _async_confirm_item(call: ServiceCall) -> None:
        await _async_set_item_state(hass, call, ItemState.CONFIRMED)

    async def _async_reject_item(call: ServiceCall) -> None:
        await _async_set_item_state(hass, call, ItemState.REJECTED)

    async def _async_reconcile_service(call: ServiceCall) -> None:
        entry_id = call.data[ATTR_ENTRY_ID]
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise vol.Invalid(f"Unknown admin_inbox entry_id: {entry_id}")
        await entry.runtime_data.pipeline.async_reconcile()

    hass.services.async_register(
        DOMAIN, SERVICE_CONFIRM_ITEM, _async_confirm_item, schema=CONFIRM_ITEM_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REJECT_ITEM, _async_reject_item, schema=REJECT_ITEM_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RECONCILE, _async_reconcile_service, schema=RECONCILE_SCHEMA
    )


async def _async_set_item_state(hass: HomeAssistant, call: ServiceCall, state: ItemState) -> None:
    entry_id = call.data[ATTR_ENTRY_ID]
    item_id = call.data[ATTR_ITEM_ID]
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise vol.Invalid(f"Unknown admin_inbox entry_id: {entry_id}")

    runtime: AdminInboxRuntimeData = entry.runtime_data
    item = runtime.store.get(item_id)
    if item is None or item.state != ItemState.PENDING:
        raise vol.Invalid(f"Item {item_id} is not pending review")

    item.state = state
    item.reviewed_at = dt_util.utcnow()
    runtime.store.save_item(item)
    runtime.coordinator.signal_update()
