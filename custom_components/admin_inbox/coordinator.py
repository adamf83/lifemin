"""DataUpdateCoordinator wrapping the in-memory Store cache.

_async_update_data is cheap by design: it only reads from AdminInboxStore's
in-memory cache, never touches IMAP or AI Task. The pipeline pushes fresh
data in via signal_update() whenever an item's state changes. This is what
lets calendar.py satisfy the "no I/O in property getters" constraint: the
calendar entity only ever reads coordinator.data.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import DOMAIN, EVENT_ITEM_DUE
from .models import ItemState, StoredItem
from .store import AdminInboxStore

_LOGGER = logging.getLogger(__name__)


@dataclass
class AdminInboxData:
    items: list[StoredItem] = field(default_factory=list)

    @property
    def confirmed(self) -> list[StoredItem]:
        return [i for i in self.items if i.state == ItemState.CONFIRMED]

    @property
    def pending(self) -> list[StoredItem]:
        return [i for i in self.items if i.state == ItemState.PENDING]


class AdminInboxCoordinator(DataUpdateCoordinator[AdminInboxData]):
    """Owns the in-memory item cache that drives every entity."""

    def __init__(self, hass: HomeAssistant, entry, store: AdminInboxStore) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.entry = entry
        self.store = store
        self._fired_due_item_ids: set[str] = set()

    async def _async_update_data(self) -> AdminInboxData:
        return AdminInboxData(items=self.store.all_items())

    def signal_update(self) -> None:
        """Push a fresh snapshot to every listening entity, no I/O."""
        self.async_set_updated_data(AdminInboxData(items=self.store.all_items()))
        self.async_check_due_items()

    def async_check_due_items(self) -> None:
        """Fire admin_inbox_item_due once per confirmed item whose date has arrived.

        Called on every coordinator refresh and on a fixed daily schedule
        (set up in __init__.py), per PLAN.md section 6, so a due date isn't
        missed just because nothing else triggered a refresh that day.
        """
        if self.data is None:
            return
        today = dt_util.now().date()
        for item in self.data.confirmed:
            the_date = item.due_date or item.event_date
            if the_date is None or the_date > today:
                continue
            if item.id in self._fired_due_item_ids:
                continue
            self._fired_due_item_ids.add(item.id)
            self.hass.bus.async_fire(
                EVENT_ITEM_DUE,
                {
                    "item_id": item.id,
                    "kind": item.kind,
                    "title": item.title,
                    "counterparty": item.counterparty,
                    "due_date": item.due_date.isoformat() if item.due_date else None,
                    "event_date": item.event_date.isoformat() if item.event_date else None,
                    "amount": str(item.amount) if item.amount is not None else None,
                    "currency": item.currency,
                },
            )
