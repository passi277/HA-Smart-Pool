"""Shared fixtures."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom_components in every test."""
    return


@pytest.fixture
async def sources(hass: HomeAssistant) -> None:
    """Create the source entities a real installation would have."""
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {"pump": {}}})
    hass.states.async_set("sensor.ph", "7.2")
    hass.states.async_set("sensor.orp", "535")
    hass.states.async_set("sensor.water_temp", "15")
    hass.states.async_set("sensor.pump_power", "0")
    hass.states.async_set("sensor.pump_energy", "100.0")
    hass.states.async_set("sensor.solar", "0")
    hass.states.async_set("sensor.air_temp", "10")
    await hass.async_block_till_done()
