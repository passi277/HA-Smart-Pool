"""Manual intervention, pausing and unanswered switch commands."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.smart_pool.const import CONF_PAUSE_ENTITY, CONF_PUMP_ENTITY, EVENT_SMART_POOL

from .test_init import PUMP, _advance, _entry, _select_mode, _setup

STATUS = "sensor.pool_pump_status"


async def _pump(hass: HomeAssistant, on: bool) -> None:
    await hass.services.async_call(
        "input_boolean", "turn_on" if on else "turn_off", {"entity_id": PUMP}, blocking=True
    )
    await hass.async_block_till_done()


async def test_switching_by_hand_is_respected(
    hass: HomeAssistant, sources, freezer: FrozenDateTimeFactory
) -> None:
    """A pump switched off by hand stays off until resumed or the next day."""
    freezer.move_to(dt_util.start_of_local_day() + timedelta(hours=12))
    await _setup(hass, _entry())
    events = async_capture_events(hass, EVENT_SMART_POOL)
    await _select_mode(hass, "continuous")
    assert hass.states.get(PUMP).state == "on"

    await _advance(hass, freezer, timedelta(minutes=5))
    await _pump(hass, False)
    await _advance(hass, freezer, timedelta(minutes=10))
    assert hass.states.get(PUMP).state == "off"
    assert hass.states.get(STATUS).state == "manual_override"
    assert hass.states.get("binary_sensor.pool_switched_by_hand").state == "on"
    assert any(e.data["type"] == "manual_override" for e in events)

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.pool_resume_automatic"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(PUMP).state == "on"
    assert hass.states.get("binary_sensor.pool_switched_by_hand").state == "off"


async def test_override_ends_next_day(
    hass: HomeAssistant, sources, freezer: FrozenDateTimeFactory
) -> None:
    """The intervention only counts for the day it happened."""
    freezer.move_to(dt_util.start_of_local_day() + timedelta(hours=20))
    await _setup(hass, _entry())
    await _select_mode(hass, "continuous")
    await _advance(hass, freezer, timedelta(minutes=5))
    await _pump(hass, False)
    await _advance(hass, freezer, timedelta(hours=3, minutes=56))
    await _advance(hass, freezer, timedelta(minutes=1))
    assert hass.states.get(PUMP).state == "on"


async def test_pause_entity_keeps_pump_off(
    hass: HomeAssistant, sources, freezer: FrozenDateTimeFactory
) -> None:
    """While the pause entity is on the pump stays off; afterwards it resumes."""
    freezer.move_to(dt_util.start_of_local_day() + timedelta(hours=12))
    hass.states.async_set("input_boolean.irrigation", "off")
    await _setup(hass, _entry(**{CONF_PAUSE_ENTITY: "input_boolean.irrigation"}))
    await _select_mode(hass, "continuous")
    assert hass.states.get(PUMP).state == "on"

    await _advance(hass, freezer, timedelta(minutes=5))
    hass.states.async_set("input_boolean.irrigation", "on")
    await hass.async_block_till_done()
    assert hass.states.get(PUMP).state == "off"
    assert hass.states.get(STATUS).state == "paused"

    # The irrigation script restores the pump itself: no manual override.
    await _advance(hass, freezer, timedelta(minutes=20))
    hass.states.async_set("input_boolean.irrigation", "off")
    await hass.async_block_till_done()
    await _pump(hass, True)
    await _advance(hass, freezer, timedelta(minutes=5))
    assert hass.states.get(PUMP).state == "on"
    assert hass.states.get("binary_sensor.pool_switched_by_hand").state == "off"


async def test_unanswered_command_is_reported_and_not_spammed(
    hass: HomeAssistant, sources, freezer: FrozenDateTimeFactory
) -> None:
    """A plug that ignores commands is flagged; commands are repeated rarely."""
    freezer.move_to(dt_util.start_of_local_day() + timedelta(hours=12))
    calls: list[ServiceCall] = []

    async def _ignore(call: ServiceCall) -> None:
        calls.append(call)

    hass.states.async_set("switch.dead_plug", "off")
    await _setup(hass, _entry(**{CONF_PUMP_ENTITY: "switch.dead_plug"}))
    # Registered after setup: loading the switch platform registers the real ones.
    hass.services.async_register("switch", "turn_on", _ignore)
    hass.services.async_register("switch", "turn_off", _ignore)
    await _select_mode(hass, "continuous")
    assert len(calls) == 1

    for _ in range(8):
        await _advance(hass, freezer, timedelta(seconds=30))
    assert hass.states.get(STATUS).state == "pump_no_response"
    assert hass.states.get("binary_sensor.pool_pump_connection_unstable").state == "on"
    assert len(calls) == 1

    for _ in range(4):
        await _advance(hass, freezer, timedelta(seconds=30))
    assert len(calls) == 2

    hass.states.async_set("switch.dead_plug", "on")
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "running_continuous"
    assert hass.states.get("binary_sensor.pool_pump_connection_unstable").state == "off"
