"""Base entity for Smart Pool."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .controller import SmartPoolController


class SmartPoolEntity(Entity):
    """Common base: device info, unique id and controller updates."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller: SmartPoolController, key: str) -> None:
        """Initialize the entity."""
        self.controller = controller
        entry_id = controller.entry.entry_id
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=controller.name,
            manufacturer="Smart Pool",
            model="Pool-Steuerung",
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to controller updates."""
        self.async_on_remove(self.controller.async_add_listener(self.async_write_ha_state))
