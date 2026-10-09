"""Integration tests running against a local test Home Assistant."""

from __future__ import annotations

from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.smart_pool.const import (
    CONF_AIR_TEMP_ENTITY,
    CONF_DRY_RUN_POWER,
    CONF_ORP_ENTITY,
    CONF_PH_ENTITY,
    CONF_PUMP_ENERGY_ENTITY,
    CONF_PUMP_ENTITY,
    CONF_PUMP_POWER_ENTITY,
    CONF_SOLAR_POWER_ENTITY,
    CONF_VOLUME,
    CONF_WATER_TEMP_ENTITY,
    DOMAIN,
    EVENT_SMART_POOL,
)

PUMP = "input_boolean.pump"


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


def _entry(**options) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Pool",
        unique_id=PUMP,
        data={
            CONF_VOLUME: 40,
            CONF_PH_ENTITY: "sensor.ph",
            CONF_ORP_ENTITY: "sensor.orp",
            CONF_WATER_TEMP_ENTITY: "sensor.water_temp",
            CONF_PUMP_ENTITY: PUMP,
        },
        options={
            CONF_PUMP_POWER_ENTITY: "sensor.pump_power",
            CONF_PUMP_ENERGY_ENTITY: "sensor.pump_energy",
            CONF_SOLAR_POWER_ENTITY: "sensor.solar",
            CONF_AIR_TEMP_ENTITY: "sensor.air_temp",
            **options,
        },
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _select_mode(hass: HomeAssistant, mode: str) -> None:
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.pool_mode", "option": mode},
        blocking=True,
    )
    await hass.async_block_till_done()


async def _advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta):
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_setup_is_passive_and_calculates(hass: HomeAssistant, sources) -> None:
    """Installing must not switch anything; values are derived correctly."""
    entry = _entry()
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED

    assert hass.states.get("select.pool_mode").state == "manual"
    assert hass.states.get("sensor.pool_pump_status").state == "manual"
    assert hass.states.get(PUMP).state == "off"

    quality = hass.states.get("sensor.pool_water_quality")
    assert quality.state == "check"
    assert quality.attributes["orp"] == 535
    assert hass.states.get("sensor.pool_redox_status").state == "check"
    assert hass.states.get("sensor.pool_ph_status").state == "ok"
    assert float(hass.states.get("sensor.pool_chlorine_dose").state) == 70
    # 15 °C / 2 = 7.5 h, +1 h because redox is low
    assert float(hass.states.get("sensor.pool_recommended_runtime").state) == 8.5
    assert float(hass.states.get("sensor.pool_energy_today").state) == 0

    # Turning the pump on manually is never undone in manual mode.
    await hass.services.async_call("input_boolean", "turn_on", {"entity_id": PUMP}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(PUMP).state == "on"

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_auto_mode_runs_until_target(
    hass: HomeAssistant, sources, freezer: FrozenDateTimeFactory
) -> None:
    """Auto mode starts at the start time and stops when the target is reached."""
    freezer.move_to(dt_util.start_of_local_day() + timedelta(hours=9))
    hass.states.async_set("sensor.orp", "700")  # good redox -> 7.5 h target
    await _setup(hass, _entry())
    events = async_capture_events(hass, EVENT_SMART_POOL)

    await _select_mode(hass, "auto")
    assert hass.states.get("sensor.pool_pump_status").state == "waiting_schedule"
    assert hass.states.get(PUMP).state == "off"

    await _advance(hass, freezer, timedelta(hours=1, minutes=1))
    assert hass.states.get(PUMP).state == "on"
    assert hass.states.get("sensor.pool_pump_status").state == "running_schedule"

    for _ in range(16):
        await _advance(hass, freezer, timedelta(minutes=30))
    assert hass.states.get(PUMP).state == "off"
    assert hass.states.get("sensor.pool_pump_status").state == "target_reached"
    assert float(hass.states.get("sensor.pool_runtime_today").state) >= 7.5
    assert float(hass.states.get("sensor.pool_pump_hours_since_backwash").state) >= 7.5

    types = [e.data["type"] for e in events]
    assert "pump_started" in types
    assert "pump_stopped" in types


async def test_dry_run_protection(
    hass: HomeAssistant, sources, freezer: FrozenDateTimeFactory
) -> None:
    """Pump is stopped and a fault raised if power stays too low."""
    freezer.move_to(dt_util.start_of_local_day() + timedelta(hours=12))
    await _setup(hass, _entry(**{CONF_DRY_RUN_POWER: 100}))
    events = async_capture_events(hass, EVENT_SMART_POOL)

    await _select_mode(hass, "continuous")
    assert hass.states.get(PUMP).state == "on"

    for _ in range(8):
        await _advance(hass, freezer, timedelta(seconds=30))
    assert hass.states.get("binary_sensor.pool_pump_fault").state == "on"
    assert hass.states.get(PUMP).state == "off"
    assert hass.states.get("sensor.pool_pump_status").state == "fault"
    assert any(e.data["type"] == "pump_fault" for e in events)

    hass.states.async_set("sensor.pump_power", "500")
    await hass.async_block_till_done()
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.pool_reset_fault"}, blocking=True
    )
    await _advance(hass, freezer, timedelta(minutes=3))
    assert hass.states.get("binary_sensor.pool_pump_fault").state == "off"
    assert hass.states.get(PUMP).state == "on"


async def test_solar_mode(hass: HomeAssistant, sources, freezer: FrozenDateTimeFactory) -> None:
    """Solar mode waits for a sustained surplus."""
    freezer.move_to(dt_util.start_of_local_day() + timedelta(hours=11))
    await _setup(hass, _entry())
    await _select_mode(hass, "solar")
    assert hass.states.get("sensor.pool_pump_status").state == "waiting_sun"

    hass.states.async_set("sensor.solar", "800")
    await hass.async_block_till_done()
    await _advance(hass, freezer, timedelta(minutes=5))
    assert hass.states.get(PUMP).state == "off"
    await _advance(hass, freezer, timedelta(minutes=6))
    assert hass.states.get(PUMP).state == "on"
    assert hass.states.get("sensor.pool_pump_status").state == "running_solar"


async def test_backwash_and_energy(
    hass: HomeAssistant, sources, freezer: FrozenDateTimeFactory
) -> None:
    """Backwash button resets the counter, energy and cost are tracked."""
    freezer.move_to(dt_util.start_of_local_day() + timedelta(hours=12))
    await _setup(hass, _entry())
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.pool_electricity_price", "value": 0.4},
        blocking=True,
    )
    hass.states.async_set("sensor.pump_energy", "102.5")
    await hass.async_block_till_done()
    assert float(hass.states.get("sensor.pool_energy_today").state) == 2.5
    assert float(hass.states.get("sensor.pool_cost_today").state) == 1.0

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.pool_backwash_done"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get("sensor.pool_last_backwash").state not in ("unknown", None)
    assert float(hass.states.get("sensor.pool_pump_hours_since_backwash").state) == 0


async def test_state_survives_restart(
    hass: HomeAssistant, sources, freezer: FrozenDateTimeFactory
) -> None:
    """Mode and start time are persisted across a reload."""
    entry = _entry()
    await _setup(hass, entry)
    await _select_mode(hass, "off")
    await hass.services.async_call(
        "time",
        "set_value",
        {"entity_id": "time.pool_start_time", "time": "14:30:00"},
        blocking=True,
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("select.pool_mode").state == "off"
    assert hass.states.get("time.pool_start_time").state == "14:30:00"
