"""Next due date, amount due (30 days), and pending review count sensors."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import AdminInboxCoordinator
from .runtime_data import AdminInboxConfigEntry


async def async_setup_entry(
    hass: HomeAssistant, entry: AdminInboxConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            NextDueDateSensor(entry, coordinator),
            AmountDue30dSensor(entry, coordinator),
            PendingReviewCountSensor(entry, coordinator),
        ]
    )


def _device_info(entry: AdminInboxConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="admin_inbox",
    )


class _AdminInboxSensorBase(CoordinatorEntity[AdminInboxCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, entry: AdminInboxConfigEntry, coordinator: AdminInboxCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = _device_info(entry)


class NextDueDateSensor(_AdminInboxSensorBase):
    """Earliest due_date/event_date among confirmed, not-yet-passed items."""

    _attr_translation_key = "next_due"
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(self, entry: AdminInboxConfigEntry, coordinator: AdminInboxCoordinator) -> None:
        super().__init__(entry, coordinator, "next_due")

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        dates = [
            item.due_date or item.event_date
            for item in self.coordinator.data.confirmed
            if (item.due_date or item.event_date) is not None
        ]
        if not dates:
            return None
        return min(dates)


class AmountDue30dSensor(_AdminInboxSensorBase):
    """Sum of confirmed items' amounts due within 30 days.

    Multi-currency limitation, documented in PLAN.md section 6: if more
    than one currency is present among the items summed, the state is the
    dominant currency's total and every currency's total is broken out in
    extra_state_attributes rather than silently mixed into one number.
    """

    _attr_translation_key = "amount_due_30d"
    _attr_native_unit_of_measurement = None

    def __init__(self, entry: AdminInboxConfigEntry, coordinator: AdminInboxCoordinator) -> None:
        super().__init__(entry, coordinator, "amount_due_30d")
        self._dominant_currency: str | None = None
        self._breakdown: dict[str, Decimal] = {}

    def _compute(self) -> dict[str, Decimal]:
        if self.coordinator.data is None:
            return {}
        today = dt_util.now().date()
        horizon = today + timedelta(days=30)
        totals: dict[str, Decimal] = defaultdict(Decimal)
        for item in self.coordinator.data.confirmed:
            the_date = item.due_date or item.event_date
            if the_date is None or item.amount is None:
                continue
            if not (today <= the_date <= horizon):
                continue
            currency = item.currency or "UNKNOWN"
            totals[currency] += item.amount
        return dict(totals)

    @property
    def native_value(self):
        totals = self._compute()
        if not totals:
            return None
        dominant = max(totals, key=lambda c: totals[c])
        self._dominant_currency = dominant
        self._breakdown = totals
        return float(totals[dominant])

    @property
    def native_unit_of_measurement(self) -> str | None:
        return self._dominant_currency

    @property
    def extra_state_attributes(self) -> dict:
        totals = self._compute()
        return {
            "breakdown_by_currency": {k: float(v) for k, v in totals.items()},
            "multi_currency": len(totals) > 1,
        }


class PendingReviewCountSensor(_AdminInboxSensorBase):
    """Count of items currently awaiting human review."""

    _attr_translation_key = "pending_review"
    _attr_native_unit_of_measurement = "items"
    _attr_state_class = "measurement"

    def __init__(self, entry: AdminInboxConfigEntry, coordinator: AdminInboxCoordinator) -> None:
        super().__init__(entry, coordinator, "pending_review")

    @property
    def native_value(self) -> int:
        if self.coordinator.data is None:
            return 0
        return len(self.coordinator.data.pending)
