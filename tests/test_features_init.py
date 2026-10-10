"""Integration tests for dose log, stock, programs, season, connection and stats."""

from __future__ import annotations

from datetime import datetime, timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.smart_pool.const import (
    CONF_MOTION_ENTITY,
    CONF_OUTAGE_LIMIT,
    CONF_PRESENCE_ENTITY,
    CONF_PROBE_DAYS,
    CONF_SHOPPING_LIST_ENTITY,
    CONF_VISUAL_ENTITY,
    DOMAIN,
    EVENT_SMART_POOL,
)
from custom_components.smart_pool.diagnostics import async_get_config_entry_diagnostics

from .test_init import PUMP, _advance, _entry, _press, _select_mode, _setup


async def _select(hass: HomeAssistant, entity_id: str, option: str) -> None:
    await hass.services.async_call(
        "select", "select_option", {"entity_id": entity_id, "option": option}, blocking=True
    )
    await hass.async_block_till_done()


async def _set_number(hass: HomeAssistant, entity_id: str, value: float) -> None:
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True
    )
    await hass.async_block_till_done()


def _types(events) -> list[str]:
    return [e.data["type"] for e in events]


async def test_dose_log_stock_and_shopping_list(hass: HomeAssistant, sources) -> None:
    """Dose log updates consumption and stock; low stock goes to the shopping list."""
    added: list[str] = []

    async def add_item(call: ServiceCall) -> None:
        added.append(call.data["item"])

    entry = _entry(**{CONF_SHOPPING_LIST_ENTITY: "todo.shopping"})
    await _setup(hass, entry)
    # Replace the real todo service (loaded with our task list) by a recorder.
    hass.services.async_register("todo", "add_item", add_item)
    events = async_capture_events(hass, EVENT_SMART_POOL)

    await _set_number(hass, "number.pool_stock_chlorine_granules", 500)
    await _select(hass, "select.pool_dose_product", "chlorine")
    # Prefilled with the recommended dose (ORP 535 -> 70 g for 40 m³).
    amount = hass.states.get("number.pool_dose_amount")
    assert float(amount.state) == 70
    assert amount.attributes["unit_of_measurement"] == "g"
    await _press(hass, "button.pool_log_dose")
    assert float(hass.states.get("sensor.pool_consumption_chlorine_granules").state) == 70
    assert float(hass.states.get("number.pool_stock_chlorine_granules").state) == 430
    last = hass.states.get("sensor.pool_last_dose")
    assert last.attributes["product"] == "chlorine"
    assert last.attributes["amount"] == 70

    await hass.services.async_call(
        DOMAIN,
        "log_dose",
        {"config_entry_id": entry.entry_id, "product": "chlorine", "amount": 300},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert float(hass.states.get("number.pool_stock_chlorine_granules").state) == 130
    assert hass.states.get("binary_sensor.pool_stock_low").state == "on"
    assert added == ["Pool: Chlorine granules"]
    assert "stock_low" in _types(events)
    assert _types(events).count("dose_logged") == 2


async def test_probe_check_flow(
    hass: HomeAssistant, sources, freezer: FrozenDateTimeFactory
) -> None:
    """Two chlorine doses without redox reaction raise the probe warning."""
    freezer.move_to(dt_util.start_of_local_day() + timedelta(hours=8))
    entry = _entry()
    await _setup(hass, entry)
    for _ in range(2):
        await hass.services.async_call(
            DOMAIN,
            "log_dose",
            {"config_entry_id": entry.entry_id, "product": "chlorine"},
            blocking=True,
        )
        await _advance(hass, freezer, timedelta(hours=7))
        hass.states.async_set("sensor.orp", "540", force_update=True)
        await hass.async_block_till_done()
    probe = hass.states.get("binary_sensor.pool_check_probe")
    assert probe.state == "on"
    assert probe.attributes["failed_checks"] == 2
    assert "calibrate the probe" in hass.states.get("sensor.pool_guidance").state
    items = await _todo_items(hass)
    assert "Maintenance: calibrate redox/pH probe" in items

    await _press(hass, "button.pool_probe_calibrated")
    assert hass.states.get("binary_sensor.pool_check_probe").state == "off"


async def _todo_items(hass: HomeAssistant) -> list[str]:
    result = await hass.services.async_call(
        "todo",
        "get_items",
        {"entity_id": "todo.pool_tasks"},
        blocking=True,
        return_response=True,
    )
    return [i["summary"] for i in result["todo.pool_tasks"]["items"]]


async def test_programs(hass: HomeAssistant, sources, freezer: FrozenDateTimeFactory) -> None:
    """Boost runs the pump outside the schedule and ends automatically."""
    freezer.move_to(dt_util.start_of_local_day() + timedelta(hours=6))
    # Report the readings at the frozen time, not at the real time of the fixture.
    hass.states.async_set("sensor.ph", "7.2", force_update=True)
    hass.states.async_set("sensor.orp", "700", force_update=True)
    entry = _entry()
    await _setup(hass, entry)
    events = async_capture_events(hass, EVENT_SMART_POOL)
    await _select_mode(hass, "auto")
    assert hass.states.get(PUMP).state == "off"

    await _select(hass, "select.pool_program", "boost")
    assert hass.states.get(PUMP).state == "on"
    assert hass.states.get("sensor.pool_pump_status").state == "running_program"
    assert float(hass.states.get("sensor.pool_program_remaining").state) == 2
    await _advance(hass, freezer, timedelta(hours=2, minutes=1))
    assert hass.states.get("select.pool_program").state == "none"
    assert hass.states.get(PUMP).state == "off"

    # Shock: afterwards measure the water.
    await hass.services.async_call(
        DOMAIN,
        "start_program",
        {"config_entry_id": entry.entry_id, "program": "shock", "hours": 1},
        blocking=True,
    )
    await _advance(hass, freezer, timedelta(hours=1, minutes=1))
    assert "check the water values" in hass.states.get("sensor.pool_guidance").state
    await _advance(hass, freezer, timedelta(minutes=5))
    hass.states.async_set("sensor.orp", "710", force_update=True)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.pool_guidance").state == "ok"

    # New fill: whole pool is fresh water -> metal remover for 40 m³.
    await _select(hass, "select.pool_program", "new_fill")
    assert float(hass.states.get("sensor.pool_metal_remover_dose").state) == 2400
    await _select(hass, "select.pool_program", "none")
    assert hass.states.get("select.pool_program").state == "none"
    assert {"program_started", "program_done"} <= set(_types(events))


async def test_visual_and_motion(hass: HomeAssistant, sources) -> None:
    """Camera text and motion while away."""
    hass.states.async_set("input_boolean.home", "off")
    hass.states.async_set("input_text.pool_finding", "Wasser klar · sauber")
    hass.states.async_set("binary_sensor.pool_motion", "off")
    await _setup(
        hass,
        _entry(
            **{
                CONF_VISUAL_ENTITY: "input_text.pool_finding",
                CONF_MOTION_ENTITY: "binary_sensor.pool_motion",
                CONF_PRESENCE_ENTITY: "input_boolean.home",
            }
        ),
    )
    hass.states.async_set("sensor.orp", "700")
    await hass.async_block_till_done()
    events = async_capture_events(hass, EVENT_SMART_POOL)
    assert hass.states.get("binary_sensor.pool_camera_finding").state == "off"

    hass.states.async_set("input_text.pool_finding", "Wasser leicht trüb")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.pool_camera_finding").state == "on"
    assert "cloudy (camera) despite good values" in hass.states.get("sensor.pool_guidance").state

    hass.states.async_set("binary_sensor.pool_motion", "on")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.pool_motion_while_away").state == "on"
    assert {"visual_finding", "motion_while_away"} <= set(_types(events))


async def test_connection_monitor(hass: HomeAssistant, sources) -> None:
    """Frequent pump outages raise a binary sensor and a repair issue."""
    entry = _entry(**{CONF_OUTAGE_LIMIT: 3})
    await _setup(hass, entry)
    for _ in range(3):
        hass.states.async_set(PUMP, "unavailable")
        await hass.async_block_till_done()
        hass.states.async_set(PUMP, "off")
        await hass.async_block_till_done()
    assert float(hass.states.get("sensor.pool_pump_outages_today").state) == 3
    assert hass.states.get("binary_sensor.pool_pump_connection_unstable").state == "on"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"pump_unstable_{entry.entry_id}")
    assert issue is not None and issue.translation_placeholders["count"] == "3"


async def test_season_and_maintenance(
    hass: HomeAssistant, sources, freezer: FrozenDateTimeFactory
) -> None:
    """Cold water in autumn recommends winterizing; maintenance gets due."""
    freezer.move_to(datetime(2026, 10, 1, 12, tzinfo=dt_util.get_default_time_zone()))
    hass.states.async_set("sensor.water_temp", "10")
    await _setup(hass, _entry(**{CONF_PROBE_DAYS: 3}))
    events = async_capture_events(hass, EVENT_SMART_POOL)
    assert hass.states.get("sensor.pool_season").state == "swim"
    for _ in range(6):
        await _advance(hass, freezer, timedelta(days=1))
    assert hass.states.get("sensor.pool_season").state == "winterize"
    assert hass.states.get("binary_sensor.pool_maintenance_due").state == "on"
    items = await _todo_items(hass)
    assert "Winterize: lower the water below the inlets" in items
    assert "Maintenance: calibrate redox/pH probe" in items
    assert {"season", "maintenance_due"} <= set(_types(events))

    # Tasks can be ticked off in the list.
    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": "todo.pool_tasks", "item": items[0], "status": "completed"},
        blocking=True,
    )
    assert hass.states.get("todo.pool_tasks").state == str(len(items) - 1)


async def test_solar_stats_and_weekly_report(
    hass: HomeAssistant, sources, freezer: FrozenDateTimeFactory
) -> None:
    """Solar share, savings and the Sunday report."""
    sunday = datetime(2026, 10, 11, 18, 0, tzinfo=dt_util.get_default_time_zone())
    freezer.move_to(sunday)
    hass.states.async_set("sensor.pump_power", "500")
    hass.states.async_set("sensor.solar", "300")
    entry = _entry()
    await _setup(hass, entry)
    events = async_capture_events(hass, EVENT_SMART_POOL)
    await _select_mode(hass, "continuous")
    for _ in range(20):
        await _advance(hass, freezer, timedelta(seconds=30))
    assert round(float(hass.states.get("sensor.pool_solar_energy_today").state), 3) == 0.05
    assert float(hass.states.get("sensor.pool_solar_share_today").state) == 60
    assert float(hass.states.get("sensor.pool_solar_savings_now").state) == 0.09
    card = hass.states.get("sensor.pool_water_quality").attributes["card_entities"]
    assert card["solar_savings"] == "sensor.pool_solar_savings_now"

    await _advance(hass, freezer, timedelta(hours=1))
    report = hass.states.get("sensor.pool_weekly_report")
    assert report.state.startswith("Week 41 · 1.2 h filter")
    assert report.attributes["solar_share"] == 60
    assert "weekly_report" in _types(events)
    # 15 °C water, 10 °C air, low redox: poor swim weather.
    assert hass.states.get("sensor.pool_swim_weather").state == "18"

    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["mode"] == "continuous"
    assert "chemistry" in diag["stored"]


async def test_multitab_reminder(
    hass: HomeAssistant, sources, freezer: FrozenDateTimeFactory
) -> None:
    """A logged multi tab is due again after the interval."""
    freezer.move_to(dt_util.start_of_local_day() + timedelta(hours=10))
    hass.states.async_set("sensor.orp", "700")
    entry = _entry()
    await _setup(hass, entry)
    await _select(hass, "select.pool_dose_product", "multitab")
    amount = hass.states.get("number.pool_dose_amount")
    assert float(amount.state) == 2  # 40 m³ / 20 m³ per tab
    assert amount.attributes["step"] == 1
    assert amount.attributes["unit_of_measurement"] == "Tab"
    assert hass.states.get("binary_sensor.pool_multi_tab_due").state == "off"

    await _press(hass, "button.pool_log_dose")
    assert float(hass.states.get("sensor.pool_consumption_multi_tabs").state) == 2
    await _advance(hass, freezer, timedelta(days=6))
    assert hass.states.get("binary_sensor.pool_multi_tab_due").state == "off"
    await _advance(hass, freezer, timedelta(days=1, minutes=1))
    assert hass.states.get("binary_sensor.pool_multi_tab_due").state == "on"
    assert hass.states.get("sensor.pool_guidance").state.startswith("Add a multi tab: 2 tab")


async def test_set_maintenance_date(
    hass: HomeAssistant, sources, freezer: FrozenDateTimeFactory
) -> None:
    """Past maintenance dates can be recorded, including backwash pump hours."""
    freezer.move_to(datetime(2026, 10, 10, 12, tzinfo=dt_util.get_default_time_zone()))
    entry = _entry()
    await _setup(hass, entry)

    async def set_date(task: str, date: str, **extra) -> None:
        await hass.services.async_call(
            DOMAIN,
            "set_maintenance_date",
            {"config_entry_id": entry.entry_id, "task": task, "date": date, **extra},
            blocking=True,
        )
        await hass.async_block_till_done()

    await set_date("backwash", "2026-09-10", pump_hours=31.5)
    assert float(hass.states.get("sensor.pool_pump_hours_since_backwash").state) == 31.5
    assert hass.states.get("sensor.pool_last_backwash").state.startswith("2026-09-10")
    await set_date("sand", "2026-03-15")
    await set_date("seals", "2026-03-15")
    await set_date("probe", "2026-03-15")
    maintenance = hass.states.get("binary_sensor.pool_maintenance_due")
    assert maintenance.state == "on"
    assert maintenance.attributes["tasks"] == ["probe"]  # 90 days are over
    assert maintenance.attributes["last_done"]["sand"] == "2026-03-15"
    season = hass.states.get("sensor.pool_season")
    assert str(season.attributes["next_sand"]) == "2028-03-14"
