"""Binary sensors for Smart Pool."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

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
