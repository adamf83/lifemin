"""Constants for the admin_inbox integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "admin_inbox"

PLATFORMS = ["todo", "calendar", "sensor"]

STORE_VERSION = 1
STORE_KEY_FMT = "admin_inbox.{entry_id}"

# Mail source: one admin_inbox entry watches exactly one source, either an
# IMAP config entry (classic mailboxes) or a webhook fed by an external
# automation (e.g. Power Automate's Outlook trigger, for mailboxes like
# Microsoft 365 that no longer allow Basic Auth IMAP). See PLAN.md section 1a.
CONF_SOURCE_TYPE = "source_type"
SOURCE_TYPE_IMAP = "imap"
SOURCE_TYPE_WEBHOOK = "webhook"
SOURCE_TYPES = [SOURCE_TYPE_IMAP, SOURCE_TYPE_WEBHOOK]

# Config / options keys
CONF_IMAP_ENTRY_ID = "imap_entry_id"
CONF_WEBHOOK_ID = "webhook_id"
CONF_AI_TASK_ENTITY_ID = "ai_task_entity_id"
CONF_SENDER_ALLOWLIST = "sender_allowlist"
CONF_KEYWORDS = "keywords"
CONF_RETENTION_DAYS = "retention_days"
CONF_DEDUP_PRUNE_DAYS = "dedup_prune_days"
CONF_RECONCILE_INTERVAL_MINUTES = "reconcile_interval_minutes"
CONF_FETCH_FAILURE_THRESHOLD = "fetch_failure_threshold"
CONF_DUE_DATE_PAST_YEARS = "due_date_past_years"
CONF_DUE_DATE_FUTURE_YEARS = "due_date_future_years"

DEFAULT_RETENTION_DAYS = 400
DEFAULT_DEDUP_PRUNE_DAYS = 400
DEFAULT_RECONCILE_INTERVAL_MINUTES = 60
DEFAULT_FETCH_FAILURE_THRESHOLD = 5
DEFAULT_DUE_DATE_PAST_YEARS = 2
DEFAULT_DUE_DATE_FUTURE_YEARS = 5

RECONCILE_INTERVAL = timedelta(hours=1)

# Item kinds
KIND_BILL = "bill"
KIND_RENEWAL = "renewal"
KIND_APPOINTMENT = "appointment"
KIND_EXPIRY = "expiry"
KIND_STATEMENT = "statement"
KIND_OTHER = "other"

ITEM_KINDS = [
    KIND_BILL,
    KIND_RENEWAL,
    KIND_APPOINTMENT,
    KIND_EXPIRY,
    KIND_STATEMENT,
    KIND_OTHER,
]

# Kinds that expect a due_date rather than an event_date.
DUE_DATE_KINDS = {KIND_BILL, KIND_RENEWAL, KIND_EXPIRY, KIND_STATEMENT, KIND_OTHER}
EVENT_DATE_KINDS = {KIND_APPOINTMENT}

# Field length caps
TITLE_MAX_LEN = 200
COUNTERPARTY_MAX_LEN = 200
SOURCE_QUOTE_MAX_LEN = 500

# Events
EVENT_ITEM_DUE = "admin_inbox_item_due"

# Services
SERVICE_CONFIRM_ITEM = "confirm_item"
SERVICE_REJECT_ITEM = "reject_item"
SERVICE_RECONCILE = "reconcile"

ATTR_ITEM_ID = "item_id"
ATTR_ENTRY_ID = "entry_id"

# Repair issue ids
ISSUE_STORE_UNAVAILABLE = "store_unavailable"
ISSUE_IMAP_FETCH_DEGRADED = "imap_fetch_degraded"
ISSUE_AI_TASK_ENTITY_MISSING = "ai_task_entity_missing"
ISSUE_STORE_SCHEMA_UNSUPPORTED = "store_schema_unsupported"
ISSUE_IMAP_ENTRY_REMOVED = "imap_entry_removed"

# imap_content event
IMAP_CONTENT_EVENT = "imap_content"

SIGNAL_ITEMS_UPDATED = f"{DOMAIN}_items_updated"
