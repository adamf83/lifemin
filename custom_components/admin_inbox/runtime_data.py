"""Typed runtime_data carried on the admin_inbox ConfigEntry."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry

from .coordinator import AdminInboxCoordinator
from .listener import AdminInboxListener
from .pipeline import AdminInboxPipeline
from .store import AdminInboxStore


@dataclass
class AdminInboxRuntimeData:
    store: AdminInboxStore
    coordinator: AdminInboxCoordinator
    pipeline: AdminInboxPipeline
    listener: AdminInboxListener


type AdminInboxConfigEntry = ConfigEntry[AdminInboxRuntimeData]
