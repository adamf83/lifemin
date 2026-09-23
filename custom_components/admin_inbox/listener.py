"""Subscribes to imap_content events and hands matching ones to the pipeline."""
from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback

from .const import IMAP_CONTENT_EVENT
from .models import FetchRequest

_LOGGER = logging.getLogger(__name__)

FetchRequestHandler = Callable[[FetchRequest], Coroutine[Any, Any, None]]


class AdminInboxListener:
    """Listens for imap_content events for one IMAP config entry."""

    def __init__(
        self,
        hass: HomeAssistant,
        imap_entry_id: str,
        on_fetch_request: FetchRequestHandler,
    ) -> None:
        self.hass = hass
        self._imap_entry_id = imap_entry_id
        self._on_fetch_request = on_fetch_request
        self._unsub: Callable[[], None] | None = None
        self.dropped_wrong_entry = 0
        self.dropped_malformed = 0

    @callback
    def async_start(self) -> None:
        if self._unsub is not None:
            return
        self._unsub = self.hass.bus.async_listen(IMAP_CONTENT_EVENT, self._async_handle_event)

    @callback
    def async_stop(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    @callback
    def _async_handle_event(self, event: Event) -> None:
        data = event.data
        entry_id = data.get("entry_id")
        if entry_id != self._imap_entry_id:
            # Routine: this fires for every other IMAP integration user on
            # this HA instance too. Not logged, per the listener's design.
            self.dropped_wrong_entry += 1
            return

        uid = data.get("uid")
        if uid is None:
            _LOGGER.warning(
                "admin_inbox: imap_content event for entry %s missing 'uid'; skipping",
                entry_id,
            )
            self.dropped_malformed += 1
            return

        request = FetchRequest(
            entry_id=entry_id,
            uid=str(uid),
            message_id=data.get("message_id"),
        )
        self.hass.async_create_task(self._on_fetch_request(request))
