"""Schedule start time for Smart Pool."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SmartPoolConfigEntry
from .entity import SmartPoolEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartPoolConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the start time entity."""
    async_add_entities([SmartPoolStartTime(entry.runtime_data, "start_time")])


class SmartPoolStartTime(SmartPoolEntity, TimeEntity):
    """Daily start time used by the automatic mode."""

    _attr_entity_category = EntityCategory.CONFIG

    @property
    def native_value(self) -> time:
        """Return the start time."""
        return self.controller.start_time

    async def async_set_value(self, value: time) -> None:
        """Set the start time."""
        await self.controller.async_set_start_time(value)
