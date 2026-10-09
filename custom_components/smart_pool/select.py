"""Operating mode select for Smart Pool."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SmartPoolConfigEntry
from .const import MODES
from .controller import SmartPoolController
from .entity import SmartPoolEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartPoolConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the mode select."""
    async_add_entities([SmartPoolModeSelect(entry.runtime_data, "mode")])


class SmartPoolModeSelect(SmartPoolEntity, SelectEntity):
    """Selects how the pump is controlled."""

    def __init__(self, controller: SmartPoolController, key: str) -> None:
        """Initialize the select."""
        super().__init__(controller, key)
        self._attr_options = list(MODES)

    @property
    def current_option(self) -> str:
        """Return the active mode."""
        return self.controller.mode

    async def async_select_option(self, option: str) -> None:
        """Change the mode."""
        await self.controller.async_set_mode(option)
