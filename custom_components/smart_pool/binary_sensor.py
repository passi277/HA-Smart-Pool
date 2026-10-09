"""Binary sensors for Smart Pool."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SmartPoolConfigEntry
from .controller import SmartPoolController
from .entity import SmartPoolEntity


@dataclass(frozen=True, kw_only=True)
class SmartPoolBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a Smart Pool binary sensor."""

    value_fn: Callable[[SmartPoolController], bool | None]
    attrs_fn: Callable[[SmartPoolController], dict[str, Any]] | None = None


BINARY_SENSORS: tuple[SmartPoolBinarySensorDescription, ...] = (
    SmartPoolBinarySensorDescription(
        key="backwash_due",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda c: c.data.backwash_due,
    ),
    SmartPoolBinarySensorDescription(
        key="measurement_stale",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda c: c.data.measurement_stale,
    ),
    SmartPoolBinarySensorDescription(
        key="pump_fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda c: c.fault,
    ),
    SmartPoolBinarySensorDescription(
        key="heavy_rain",
        device_class=BinarySensorDeviceClass.MOISTURE,
        value_fn=lambda c: c.data.heavy_rain,
    ),
    SmartPoolBinarySensorDescription(
        key="metal_ex_active",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda c: c.data.metal_ex_hours_left > 0,
    ),
    SmartPoolBinarySensorDescription(
        key="probe_check",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda c: c.data.probe_suspect,
        attrs_fn=lambda c: {
            "failed_checks": c.chem.probe_failures,
            "last_redox_rise_mv": c.chem.last_rise_mv,
            "check_pending": c.chem.pending_check is not None,
        },
    ),
    SmartPoolBinarySensorDescription(
        key="stock_low",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda c: bool(c.data.low_stock),
        attrs_fn=lambda c: {
            "products": c.data.low_stock,
            "stock": c.chem.stock,
            "thresholds": c.stock_thresholds(),
        },
    ),
    SmartPoolBinarySensorDescription(
        key="maintenance_due",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda c: bool(c.data.maintenance_due),
        attrs_fn=lambda c: {
            "tasks": c.data.maintenance_due,
            "last_done": c.season.maintenance,
        },
    ),
    SmartPoolBinarySensorDescription(
        key="visual_finding",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda c: bool(c.data.visual),
        attrs_fn=lambda c: {"findings": c.data.visual, "text": c.data.visual_text},
    ),
    SmartPoolBinarySensorDescription(
        key="motion_while_away",
        device_class=BinarySensorDeviceClass.MOTION,
        value_fn=lambda c: c.data.motion_away,
    ),
    SmartPoolBinarySensorDescription(
        key="connection_unstable",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda c: c.data.connection_unstable,
        attrs_fn=lambda c: {"outages_today": c.data.outages_today},
    ),
    SmartPoolBinarySensorDescription(
        key="frost_risk",
        device_class=BinarySensorDeviceClass.COLD,
        value_fn=lambda c: c.data.frost_risk,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartPoolConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Smart Pool binary sensors."""
    controller = entry.runtime_data
    async_add_entities(SmartPoolBinarySensor(controller, desc) for desc in BINARY_SENSORS)


class SmartPoolBinarySensor(SmartPoolEntity, BinarySensorEntity):
    """A pool problem / state flag."""

    entity_description: SmartPoolBinarySensorDescription

    def __init__(
        self,
        controller: SmartPoolController,
        description: SmartPoolBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(controller, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return true if the flag is set."""
        return self.entity_description.value_fn(self.controller)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.controller)
