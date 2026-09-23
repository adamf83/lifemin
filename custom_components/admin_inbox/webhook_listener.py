"""Webhook mail source: for mailboxes the imap integration can't reach.

Microsoft 365 (and any Exchange Online mailbox) retired Basic Auth for
IMAP, which is all the core `imap` integration supports -- so a mailbox
like that has no imap_content events to listen for. This module is the
alternative entry point: an external automation with its own OAuth access
to the mailbox (e.g. a Power Automate flow triggered on "When a new email
arrives") POSTs the message here instead. Since the payload already
contains the full body, there is no separate fetch step -- see
pipeline.async_handle_pushed_email.
"""
from __future__ import annotations

import logging
from typing import Any

from aiohttp import web
from aiohttp.web import Request, Response
from homeassistant.components import webhook
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .models import FetchRequest, RawEmail
from .pipeline import AdminInboxPipeline

_LOGGER = logging.getLogger(__name__)

# Required in every POST body: without a stable per-message id, duplicate
# deliveries (a flow re-run, a retried HTTP call) can't be deduplicated.
_REQUIRED_FIELDS = ("message_id",)


def async_register(
    hass: HomeAssistant, entry_id: str, admin_inbox_webhook_id: str, pipeline: AdminInboxPipeline
) -> None:
    """Register the webhook for one admin_inbox entry."""

    async def _handle(hass: HomeAssistant, webhook_id: str, request: Request) -> Response | None:
        return await _async_handle_webhook(hass, entry_id, pipeline, request)

    webhook.async_register(
        hass,
        DOMAIN,
        "Admin Inbox mail source",
        admin_inbox_webhook_id,
        _handle,
        local_only=False,
        allowed_methods=["POST"],
    )


def async_unregister(hass: HomeAssistant, webhook_id: str) -> None:
    webhook.async_unregister(hass, webhook_id)


async def _async_handle_webhook(
    hass: HomeAssistant, entry_id: str, pipeline: AdminInboxPipeline, request: Request
) -> Response:
    try:
        payload: Any = await request.json()
    except ValueError:
        _LOGGER.warning("admin_inbox: webhook received a non-JSON body; ignoring")
        return web.json_response({"error": "invalid_json"}, status=400)

    if not isinstance(payload, dict):
        return web.json_response({"error": "expected_json_object"}, status=400)

    missing = [field for field in _REQUIRED_FIELDS if not payload.get(field)]
    if missing:
        _LOGGER.warning("admin_inbox: webhook payload missing required field(s): %s", missing)
        return web.json_response({"error": "missing_fields", "fields": missing}, status=400)

    message_id = str(payload["message_id"])
    raw_email = RawEmail(
        uid=message_id,
        sender=str(payload.get("sender") or ""),
        subject=str(payload.get("subject") or ""),
        date=str(payload.get("date") or ""),
        text=str(payload.get("text") or ""),
    )
    fetch_request = FetchRequest(entry_id=entry_id, uid=message_id, message_id=message_id)

    await pipeline.async_handle_pushed_email(fetch_request, raw_email)

    return web.json_response({"status": "accepted"}, status=200)
