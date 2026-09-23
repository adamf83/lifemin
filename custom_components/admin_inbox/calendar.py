"""Household obligations calendar: confirmed items only, backed by the coordinator.

No I/O in any property or method here — every event is built from
coordinator.data, which the pipeline refreshes on state changes. This is
the constraint called out in PLAN.md section 6.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import AdminInboxCoordinator
from .models import StoredItem
from .runtime_data import AdminInboxConfigEntry


async def async_setup_entry(
    hass: HomeAssistant, entry: AdminInboxConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([AdminInboxCalendarEntity(entry)])


def _event_from_stored(item: StoredItem) -> CalendarEvent | None:
    the_date = item.due_date or item.event_date
    if the_date is None:
        return None
    summary = f"{item.title} — {item.counterparty}"
    description = item.source_quote or ""
    if item.amount is not None:
        description = f"{item.amount} {item.currency}\n{description}"
    return CalendarEvent(
        start=the_date,
        end=the_date + timedelta(days=1),
        summary=summary,
        description=description,
        uid=item.id,
    )


class AdminInboxCalendarEntity(CoordinatorEntity[AdminInboxCoordinator], CalendarEntity):
    """One all-day event per confirmed StoredItem with a due_date/event_date."""

    _attr_has_entity_name = True
    _attr_translation_key = "household_obligations"

    def __init__(self, entry: AdminInboxConfigEntry) -> None:
        super().__init__(entry.runtime_data.coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_calendar"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="admin_inbox",
        )

    def _all_events(self) -> list[CalendarEvent]:
        if self.coordinator.data is None:
            return []
        events = [_event_from_stored(item) for item in self.coordinator.data.confirmed]
        return [e for e in events if e is not None]

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now().date()
        upcoming = sorted(
            (e for e in self._all_events() if _event_end_date(e) >= now),
            key=lambda e: _event_start_date(e),
        )
        return upcoming[0] if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        start = start_date.date() if isinstance(start_date, datetime) else start_date
        end = end_date.date() if isinstance(end_date, datetime) else end_date
        return [
            e
            for e in self._all_events()
            if _event_start_date(e) < end and _event_end_date(e) > start
        ]


def _event_start_date(event: CalendarEvent) -> date:
    start = event.start
    return start.date() if isinstance(start, datetime) else start


def _event_end_date(event: CalendarEvent) -> date:
    end = event.end
    return end.date() if isinstance(end, datetime) else end
