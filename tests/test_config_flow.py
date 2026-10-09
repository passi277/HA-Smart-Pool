"""Config and options flow tests."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component

from custom_components.smart_pool.const import (
    CONF_AIR_TEMP_ENTITY,
    CONF_DRY_RUN_POWER,
    CONF_PUMP_POWER_ENTITY,
    DOMAIN,
)

USER_INPUT = {
    "name": "Pool",
    "volume": 40,
    "ph_entity": "sensor.ph",
    "orp_entity": "sensor.orp",
    "water_temp_entity": "sensor.water_temp",
    "pump_entity": "input_boolean.pump",
}


async def _prepare(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {"pump": {}}})
    for entity_id, value in (
        ("sensor.ph", "7.2"),
        ("sensor.orp", "650"),
        ("sensor.water_temp", "20"),
        ("sensor.pump_power", "400"),
        ("sensor.air_temp", "12"),
    ):
        hass.states.async_set(entity_id, value)


async def test_full_flow_and_options(hass: HomeAssistant) -> None:
    """Create an entry, then change options."""
    await _prepare(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["step_id"] == "optional"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PUMP_POWER_ENTITY: "sensor.pump_power"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Pool"
    assert "name" not in result["data"]
    assert result["options"] == {CONF_PUMP_POWER_ENTITY: "sensor.pump_power"}
    await hass.async_block_till_done()

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    core = {k: v for k, v in USER_INPUT.items() if k != "name"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], core)
    assert result["step_id"] == "settings"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_AIR_TEMP_ENTITY: "sensor.air_temp", CONF_DRY_RUN_POWER: 80},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_AIR_TEMP_ENTITY] == "sensor.air_temp"
    assert entry.options[CONF_DRY_RUN_POWER] == 80
    # Power sensor was cleared in the form, so it is removed.
    assert CONF_PUMP_POWER_ENTITY not in entry.options


async def test_duplicate_pump_aborts(hass: HomeAssistant) -> None:
    """The same pump cannot be configured twice."""
    await _prepare(hass)
    for expected in (FlowResultType.FORM, FlowResultType.ABORT):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
        assert result["type"] is expected
        if expected is FlowResultType.FORM:
            await hass.config_entries.flow.async_configure(result["flow_id"], {})
            await hass.async_block_till_done()
    assert result["reason"] == "already_configured"
