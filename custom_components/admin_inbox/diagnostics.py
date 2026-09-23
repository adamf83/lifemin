"""Diagnostics for admin_inbox.

Deliberately excludes anything that could leak email content: no
source_quote, no message_ref subject/sender. Only counts and state
distribution, per PLAN.md section 9 (M6 DoD).
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from homeassistant.core import HomeAssistant

from .const import CONF_AI_TASK_ENTITY_ID, CONF_IMAP_ENTRY_ID, CONF_KEYWORDS, CONF_SENDER_ALLOWLIST
from .runtime_data import AdminInboxConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AdminInboxConfigEntry
) -> dict[str, Any]:
    runtime = entry.runtime_data
    items = runtime.store.all_items()
    state_counts = Counter(item.state.value for item in items)
    diagnostics = runtime.pipeline.diagnostics

    return {
        "config": {
            "imap_entry_id_configured": bool(entry.data.get(CONF_IMAP_ENTRY_ID)),
            "ai_task_entity_id_configured": bool(entry.data.get(CONF_AI_TASK_ENTITY_ID)),
            "sender_allowlist_count": len(entry.options.get(CONF_SENDER_ALLOWLIST, [])),
            "keyword_count": len(entry.options.get(CONF_KEYWORDS, [])),
        },
        "item_state_distribution": dict(state_counts),
        "total_items": len(items),
        "pipeline_counters": {
            "dedup_dropped": diagnostics.dedup_dropped,
            "prefiltered": diagnostics.prefiltered,
            "extraction_failed": diagnostics.extraction_failed,
            "validation_rejected": diagnostics.validation_rejected,
            "fetch_failed": diagnostics.fetch_failed,
        },
    }
