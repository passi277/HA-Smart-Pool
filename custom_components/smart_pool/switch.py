"""Switches for Smart Pool."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    """Set up Smart Pool switches."""
    async_add_entities(
        [
            SmartPoolFollowRecommendation(entry.runtime_data, "follow_recommendation"),
            SmartPoolCatchup(entry.runtime_data, "catchup"),
        ]
    )


class SmartPoolFollowRecommendation(SmartPoolEntity, SwitchEntity):
    """When on, the target runtime follows the recommended runtime."""

    _attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self) -> bool:
        """Return true if the target follows the recommendation."""
        return self.controller.follow_recommendation

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Follow the recommendation."""
        await self.controller.async_set_follow_recommendation(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Keep the target fixed."""
        await self.controller.async_set_follow_recommendation(False)


class SmartPoolCatchup(SmartPoolEntity, SwitchEntity):
    """Solar mode: run on grid power from the catch-up time if needed."""

    @property
    def is_on(self) -> bool:
        """Return true if catching up on grid power is allowed."""
        return self.controller.catchup_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Allow catching up."""
        await self.controller.async_set_catchup(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Run on solar power only."""
        await self.controller.async_set_catchup(False)
