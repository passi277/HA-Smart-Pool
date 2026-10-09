"""Integration tests running against a local test Home Assistant."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
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
    CONF_RAIN_ENTITY,
    CONF_SOLAR_POWER_ENTITY,
    CONF_SURFACE,
    CONF_VOLUME,
    CONF_WATER_TEMP_ENTITY,
    CONF_WEATHER_ENTITY,
    DOMAIN,
    EVENT_SMART_POOL,
)

PUMP = "input_boolean.pump"


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


async def _press(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)
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
    assert hass.states.get("sensor.pool_guidance").state == (
        "Redox too low: add about 70 g chlorine"
    )
    assert (
        hass.states.get("sensor.pool_pump_hours_since_backwash").attributes["interval_hours"] == 50
    )

    card = quality.attributes["card_entities"]
    assert card["pump"] == PUMP
    assert card["mode"] == "select.pool_mode"
    assert card["target_mode"] == "auto"
    assert card["target_runtime"] == "number.pool_target_runtime"
    assert card["guidance"] == "sensor.pool_guidance"
    assert card["temperature"] == "sensor.water_temp"
    assert card["backwash"]["done_button"] == "button.pool_backwash_done"

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


async def test_target_runtime(hass: HomeAssistant, sources) -> None:
    """Target follows the recommendation until a fixed value is set."""
    await _setup(hass, _entry())
    target = "number.pool_target_runtime"
    follow = "switch.pool_follow_recommendation"
    assert float(hass.states.get(target).state) == 8.5
    assert hass.states.get(follow).state == "on"

    async def set_target(value: float) -> None:
        await hass.services.async_call(
            "number", "set_value", {"entity_id": target, "value": value}, blocking=True
        )
        await hass.async_block_till_done()

    await set_target(4)
    assert float(hass.states.get(target).state) == 4
    assert hass.states.get(follow).state == "off"
    assert float(hass.states.get("sensor.pool_remaining_runtime").state) == 4

    # A colder pool changes the recommendation but not the fixed target.
    hass.states.async_set("sensor.water_temp", "10")
    await hass.async_block_till_done()
    assert float(hass.states.get(target).state) == 4

    # Choosing the recommendation (card button) follows it again.
    await set_target(6)
    assert hass.states.get(follow).state == "on"
    hass.states.async_set("sensor.water_temp", "16")
    await hass.async_block_till_done()
    assert float(hass.states.get(target).state) == 9

    await hass.services.async_call("switch", "turn_off", {"entity_id": follow}, blocking=True)
    hass.states.async_set("sensor.water_temp", "20")
    await hass.async_block_till_done()
    assert float(hass.states.get(target).state) == 9


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


async def test_refill_and_metal_ex_treatment(
    hass: HomeAssistant, sources, freezer: FrozenDateTimeFactory
) -> None:
    """Refill -> metal remover dose -> 48 h pump run -> backwash."""
    freezer.move_to(dt_util.start_of_local_day() + timedelta(hours=8))
    hass.states.async_set("sensor.orp", "700")
    await _setup(hass, _entry(**{CONF_SURFACE: 15}))
    events = async_capture_events(hass, EVENT_SMART_POOL)
    await _select_mode(hass, "auto")
    assert hass.states.get(PUMP).state == "off"

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.pool_refill_amount", "value": 2},
        blocking=True,
    )
    await _press(hass, "button.pool_refilled")
    dose = hass.states.get("sensor.pool_metal_remover_dose")
    assert float(dose.state) == 20  # 300 l * 60 ml/m³
    assert dose.attributes["fresh_water_liters"] == 300
    assert dose.attributes["whole_pool_preventive_ml"] == 1200  # 40 m³ * 30 ml
    guidance = hass.states.get("sensor.pool_guidance").state
    assert guidance.startswith("Add 20 ml metal remover")

    await _press(hass, "button.pool_metal_remover_added")
    assert hass.states.get(PUMP).state == "on"
    assert hass.states.get("sensor.pool_pump_status").state == "running_metal_ex"
    assert hass.states.get("binary_sensor.pool_metal_remover_treatment").state == "on"
    assert float(hass.states.get("sensor.pool_metal_remover_dose").state) == 0
    assert float(hass.states.get("sensor.pool_metal_remover_remaining").state) == 48

    # Still running in the evening although the daily target is long reached.
    await _advance(hass, freezer, timedelta(hours=20))
    assert hass.states.get(PUMP).state == "on"

    for _ in range(3):
        await _advance(hass, freezer, timedelta(hours=10))
    assert hass.states.get("binary_sensor.pool_metal_remover_treatment").state == "off"
    assert hass.states.get("binary_sensor.pool_backwash_due").state == "on"
    assert "backwash" in hass.states.get("sensor.pool_guidance").state

    await _press(hass, "button.pool_backwash_done")
    assert hass.states.get("binary_sensor.pool_backwash_due").state == "off"
    types = [e.data["type"] for e in events]
    assert {"refilled", "metal_ex_added", "metal_ex_done", "backwash_done"} <= set(types)


async def test_weather_forecast(
    hass: HomeAssistant, sources, freezer: FrozenDateTimeFactory
) -> None:
    """Forecast drives rain estimate, heavy rain, hints and extra runtime."""
    freezer.move_to(dt_util.start_of_local_day() + timedelta(hours=12, minutes=10))
    hass.states.async_set("sensor.orp", "700")
    hour = dt_util.now().replace(minute=0, second=0, microsecond=0)
    calls = []

    async def forecasts(call: ServiceCall) -> ServiceResponse:
        calls.append(call.data["type"])
        return {
            "weather.home": {
                "forecast": [
                    {"datetime": hour.isoformat(), "precipitation": 12, "temperature": 18},
                    {
                        "datetime": (hour + timedelta(hours=3)).isoformat(),
                        "precipitation": 3,
                        "temperature": 31,
                    },
                ]
            }
        }

    hass.services.async_register(
        "weather", "get_forecasts", forecasts, supports_response=SupportsResponse.ONLY
    )
    hass.states.async_set("weather.home", "rainy")
    await _setup(hass, _entry(**{CONF_WEATHER_ENTITY: "weather.home", CONF_SURFACE: 15}))

    assert calls[0] == "hourly"
    assert float(hass.states.get("sensor.pool_rain_last_24_h").state) == 12
    forecast = hass.states.get("sensor.pool_rain_forecast_24_h")
    assert float(forecast.state) == 15
    assert forecast.attributes["liters"] == 225
    assert forecast.attributes["max_temperature"] == 31
    assert hass.states.get("binary_sensor.pool_heavy_rain").state == "on"
    hint = hass.states.get("sensor.pool_weather_hint").state
    assert hint.startswith("Heavy rain (12 mm)")
    # 15 °C / 2 = 7.5 h + 1 h heavy rain + 1 h heat
    assert float(hass.states.get("sensor.pool_recommended_runtime").state) == 9.5

    # Cached for 30 minutes.
    await _advance(hass, freezer, timedelta(minutes=5))
    assert len(calls) == 1
    await _advance(hass, freezer, timedelta(minutes=30))
    assert len(calls) == 2


async def test_rain_gauge(hass: HomeAssistant, sources, freezer: FrozenDateTimeFactory) -> None:
    """Rain gauge deltas are summed over 24 h, daily resets are handled."""
    freezer.move_to(dt_util.start_of_local_day() + timedelta(hours=20))
    hass.states.async_set("sensor.rain", "100")
    await _setup(hass, _entry(**{CONF_RAIN_ENTITY: "sensor.rain"}))
    assert float(hass.states.get("sensor.pool_rain_last_24_h").state) == 0

    for value in ("104", "111"):
        hass.states.async_set("sensor.rain", value)
        await hass.async_block_till_done()
    assert float(hass.states.get("sensor.pool_rain_last_24_h").state) == 11
    assert hass.states.get("binary_sensor.pool_heavy_rain").state == "on"

    await _advance(hass, freezer, timedelta(hours=5))
    hass.states.async_set("sensor.rain", "2")  # meter reset at midnight
    await hass.async_block_till_done()
    assert float(hass.states.get("sensor.pool_rain_last_24_h").state) == 13

    await _advance(hass, freezer, timedelta(hours=25))
    assert float(hass.states.get("sensor.pool_rain_last_24_h").state) == 0
    assert hass.states.get("binary_sensor.pool_heavy_rain").state == "off"
