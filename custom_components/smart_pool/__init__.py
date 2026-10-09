"""The Smart Pool integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .controller import SmartPoolController
from .services import async_setup_services

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
    Platform.TODO,
]

type SmartPoolConfigEntry = ConfigEntry[SmartPoolController]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services once for all pools."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SmartPoolConfigEntry) -> bool:
    """Set up Smart Pool from a config entry."""
    controller = SmartPoolController(hass, entry)
    await controller.async_setup()
    entry.runtime_data = controller

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Refresh once all entities exist so the card mapping is complete.
    await controller.async_update()
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SmartPoolConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: SmartPoolConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
