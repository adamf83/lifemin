"""Wraps the imap.fetch action to retrieve a full email body for a FetchRequest."""
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .models import FetchRequest, RawEmail

_LOGGER = logging.getLogger(__name__)


class FetchError(Exception):
    """Raised when imap.fetch fails or returns an unusable response."""


async def async_fetch_email(hass: HomeAssistant, request: FetchRequest) -> RawEmail:
    """Fetch the full body of one email via the imap.fetch action.

    Uses BODY.PEEK[] semantics (the imap integration's default for this
    action), so this does not mark the message as read.
    """
    try:
        response = await hass.services.async_call(
            "imap",
            "fetch",
            {"entry": request.entry_id, "uid": request.uid},
            blocking=True,
            return_response=True,
        )
    except HomeAssistantError as err:
        raise FetchError(f"imap.fetch failed for uid {request.uid}: {err}") from err

    if not response:
        raise FetchError(f"imap.fetch returned no response for uid {request.uid}")

    raw_parts = response.get("parts")
    parts = [str(part) for part in raw_parts] if isinstance(raw_parts, list) else []

    return RawEmail(
        uid=request.uid,
        sender=str(response.get("sender") or ""),
        subject=str(response.get("subject") or ""),
        date=str(response.get("date") or ""),
        text=str(response.get("text") or ""),
        parts=parts,
    )
