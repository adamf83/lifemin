"""Repair issue helpers for admin_inbox.

Most repair issues (store_unavailable, store_schema_unsupported,
ai_task_entity_missing, imap_fetch_degraded) are raised inline at the
point they're detected (__init__.py's async_setup_entry, pipeline.py's
extraction/fetch stages) since that's where the relevant context already
lives. This module owns the one check that has no natural home in either:
whether the IMAP config entry this admin_inbox entry depends on has been
removed entirely.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import CONF_IMAP_ENTRY_ID, DOMAIN, ISSUE_IMAP_ENTRY_REMOVED


def async_check_imap_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Raise/clear the imap_entry_removed issue. Returns True if the IMAP entry is missing."""
    imap_entry_id = entry.data.get(CONF_IMAP_ENTRY_ID)
    imap_entry = hass.config_entries.async_get_entry(imap_entry_id) if imap_entry_id else None

    issue_id = f"{ISSUE_IMAP_ENTRY_REMOVED}_{entry.entry_id}"
    if imap_entry is None:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_IMAP_ENTRY_REMOVED,
            translation_placeholders={"imap_entry_id": imap_entry_id or "none"},
        )
        return True

    ir.async_delete_issue(hass, DOMAIN, issue_id)
    return False
