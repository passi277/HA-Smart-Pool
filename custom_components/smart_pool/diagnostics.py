"""Diagnostics for Smart Pool."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from . import SmartPoolConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SmartPoolConfigEntry
) -> dict[str, Any]:
    """Return everything useful for troubleshooting (no secrets involved)."""
    controller = entry.runtime_data
    return {
        "config": controller.config,
        "status": controller.status,
        "mode": controller.mode,
        "pump_on": controller.pump_on,
        "data": asdict(controller.data),
        "stored": controller._data_to_save(),
    }
