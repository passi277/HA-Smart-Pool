"""Tests for the pure calculation helpers."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import pytest

from custom_components.smart_pool.calculations import (
    PumpInputs,
    chlorine_dose,
    classify_orp,
    classify_ph,
    combine_quality,
    decide_pump,
    ph_doses,
    recommended_runtime,
    split_at_midnight,
)
from custom_components.smart_pool.const import (
    MODE_AUTO,
    MODE_CONTINUOUS,
    MODE_MANUAL,
    MODE_OFF,
    MODE_SOLAR,
    MODE_WINTER,
    STATUS_FAULT,
    STATUS_FROST_PROTECTION,
    STATUS_MANUAL,
    STATUS_PUMP_UNAVAILABLE,
    STATUS_RUNNING_CATCHUP,
    STATUS_RUNNING_SCHEDULE,
    STATUS_RUNNING_SOLAR,
    STATUS_TARGET_REACHED,
    STATUS_WAITING_SCHEDULE,
    STATUS_WAITING_SUN,
    STATUS_WINTER_IDLE,
)

TZ = timezone(timedelta(hours=2))


def _now(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 7, 1, hour, minute, tzinfo=TZ)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "unknown"),
        (6.5, "critical"),
        (7.0, "check"),
        (7.2, "ok"),
        (7.6, "ok"),
        (7.8, "check"),
        (8.2, "critical"),
    ],
)
def test_classify_ph(value, expected):
    assert classify_ph(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(350, "critical"), (535, "check"), (700, "ok"), (850, "check"), (950, "critical")],
)
def test_classify_orp(value, expected):
    assert classify_orp(value) == expected


def test_combine_quality():
    assert combine_quality("ok", "check") == "check"
    assert combine_quality("critical", "ok") == "critical"
    assert combine_quality("unknown", "ok") == "ok"
    assert combine_quality("unknown", "unknown") == "unknown"


def _runtime(temp, flow=0.0, orp="ok"):
    return recommended_runtime(
        temp, volume_m3=40, pump_flow_m3h=flow, orp_status=orp, min_hours=2, max_hours=12
    )


def test_recommended_runtime():
    assert _runtime(15) == 7.5
    assert _runtime(28) == 12  # 14 h clamped
    assert _runtime(2) == 2  # minimum
    assert _runtime(None) == 2
    assert _runtime(10, flow=4) == 10  # one turnover of 40 m³ at 4 m³/h
    assert _runtime(15, orp="check") == 8.5
    assert _runtime(15, orp="critical") == 9.5


def test_chlorine_dose():
    kwargs = {"volume_m3": 40, "strength_percent": 56, "step_ppm": 1}
    assert chlorine_dose(700, **kwargs) == 0
    assert chlorine_dose(None, **kwargs) == 0
    assert chlorine_dose(535, **kwargs) == 70  # 40 g / 0.56 = 71.4 -> 70
    assert chlorine_dose(350, **kwargs) == 145  # doubled below critical


def test_ph_doses():
    assert ph_doses(7.4, volume_m3=40) == (0, 0)
    assert ph_doses(7.8, volume_m3=40) == (1600, 0)  # 4 steps * 10 g * 40 m³
    assert ph_doses(7.0, volume_m3=40) == (0, 1600)
    assert ph_doses(None, volume_m3=40) == (0, 0)


def test_split_at_midnight():
    start = datetime(2026, 7, 1, 23, 50, tzinfo=TZ)
    assert split_at_midnight(start, start + timedelta(minutes=5)) == (300, 0)
    assert split_at_midnight(start, start + timedelta(minutes=20)) == (600, 600)
    assert split_at_midnight(start, start) == (0, 0)


def _inputs(**overrides) -> PumpInputs:
    base = {
        "mode": MODE_AUTO,
        "now": _now(12),
        "pump_on": False,
        "runtime_today_h": 0.0,
        "target_runtime_h": 6.0,
        "start_time": time(10),
        "catchup_time": time(17),
    }
    base.update(overrides)
    return PumpInputs(**base)


def test_manual_never_switches():
    decision = decide_pump(_inputs(mode=MODE_MANUAL, pump_on=True))
    assert decision.turn_on is None
    assert decision.status == STATUS_MANUAL


def test_unavailable_pump_is_left_alone():
    decision = decide_pump(_inputs(pump_on=None))
    assert decision.turn_on is None
    assert decision.status == STATUS_PUMP_UNAVAILABLE


def test_fault_and_off_stop_pump():
    assert decide_pump(_inputs(fault=True, pump_on=True)).status == STATUS_FAULT
    assert decide_pump(_inputs(fault=True, pump_on=True)).turn_on is False
    assert decide_pump(_inputs(mode=MODE_OFF, pump_on=True)).turn_on is False


def test_auto_schedule():
    early = decide_pump(_inputs(now=_now(9)))
    assert (early.turn_on, early.status) == (False, STATUS_WAITING_SCHEDULE)
    running = decide_pump(_inputs(now=_now(10, 1)))
    assert (running.turn_on, running.status) == (True, STATUS_RUNNING_SCHEDULE)
    done = decide_pump(_inputs(pump_on=True, runtime_today_h=6.0))
    assert (done.turn_on, done.status) == (False, STATUS_TARGET_REACHED)


def test_continuous():
    assert decide_pump(_inputs(mode=MODE_CONTINUOUS, runtime_today_h=20)).turn_on is True


def test_solar_needs_sustained_surplus():
    short = decide_pump(_inputs(mode=MODE_SOLAR, solar_surplus_since=_now(11, 55)))
    assert (short.turn_on, short.status) == (False, STATUS_WAITING_SUN)
    long = decide_pump(_inputs(mode=MODE_SOLAR, solar_surplus_since=_now(11, 45)))
    assert (long.turn_on, long.status) == (True, STATUS_RUNNING_SOLAR)


def test_solar_keeps_running_through_short_clouds():
    brief = decide_pump(_inputs(mode=MODE_SOLAR, pump_on=True, solar_deficit_since=_now(11, 55)))
    assert brief.turn_on is True
    stop = decide_pump(_inputs(mode=MODE_SOLAR, pump_on=True, solar_deficit_since=_now(11, 45)))
    assert (stop.turn_on, stop.status) == (False, STATUS_WAITING_SUN)


def test_solar_catchup():
    decision = decide_pump(_inputs(mode=MODE_SOLAR, now=_now(17, 30)))
    assert (decision.turn_on, decision.status) == (True, STATUS_RUNNING_CATCHUP)


def test_winter():
    warm = decide_pump(_inputs(mode=MODE_WINTER, air_temp=8))
    assert (warm.turn_on, warm.status) == (False, STATUS_WINTER_IDLE)
    frost_on = decide_pump(_inputs(mode=MODE_WINTER, air_temp=-1, now=_now(3, 5)))
    assert (frost_on.turn_on, frost_on.status) == (True, STATUS_FROST_PROTECTION)
    frost_off = decide_pump(_inputs(mode=MODE_WINTER, air_temp=-1, now=_now(3, 30), pump_on=True))
    assert frost_off.turn_on is False


def test_switch_guard_prevents_flapping():
    decision = decide_pump(_inputs(now=_now(10, 1), last_switch=_now(10, 0)))
    assert decision.turn_on is None
    decision = decide_pump(_inputs(now=_now(10, 5), last_switch=_now(10, 0)))
    assert decision.turn_on is True
