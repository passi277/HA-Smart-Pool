"""Adjustable numbers for Smart Pool."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfLength, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SmartPoolConfigEntry
from .controller import SmartPoolController
from .entity import SmartPoolEntity


@dataclass(frozen=True, kw_only=True)
class SmartPoolNumberDescription(NumberEntityDescription):
    """Describes a Smart Pool number."""

    value_fn: Callable[[SmartPoolController], float]
    set_fn: Callable[[SmartPoolController, float], Awaitable[None]]


NUMBERS: tuple[SmartPoolNumberDescription, ...] = (
    SmartPoolNumberDescription(
        key="target_runtime",
        native_min_value=0,
        native_max_value=24,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTime.HOURS,
        mode=NumberMode.BOX,
        value_fn=lambda c: c.data.target_runtime,
        set_fn=lambda c, v: c.async_set_target_runtime(v),
    ),
    SmartPoolNumberDescription(
        key="refill_cm",
        entity_category=EntityCategory.CONFIG,
        native_min_value=0.5,
        native_max_value=30,
        native_step=0.5,
        native_unit_of_measurement=UnitOfLength.CENTIMETERS,
        mode=NumberMode.BOX,
        value_fn=lambda c: c.refill_cm,
        set_fn=lambda c, v: c.async_set_refill_cm(v),
    ),
    SmartPoolNumberDescription(
        key="electricity_price",
        entity_category=EntityCategory.CONFIG,
        native_min_value=0,
        native_max_value=2,
        native_step=0.01,
        native_unit_of_measurement="EUR/kWh",
        mode=NumberMode.BOX,
        value_fn=lambda c: c.electricity_price,
        set_fn=lambda c, v: c.async_set_electricity_price(v),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartPoolConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Smart Pool numbers."""
    controller = entry.runtime_data
    async_add_entities(SmartPoolNumber(controller, desc) for desc in NUMBERS)


class SmartPoolNumber(SmartPoolEntity, NumberEntity):
    """A runtime adjustable value."""

    entity_description: SmartPoolNumberDescription

    def __init__(
        self, controller: SmartPoolController, description: SmartPoolNumberDescription
    ) -> None:
        """Initialize the number."""
        super().__init__(controller, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float:
        """Return the current value."""
        return self.entity_description.value_fn(self.controller)

    async def async_set_native_value(self, value: float) -> None:
        """Update the value."""
        await self.entity_description.set_fn(self.controller, value)
