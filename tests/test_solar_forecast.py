"""Solar start forecast."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.smart_pool.const import (
    CONF_SOLAR_FORECAST_ENTITY,
    CONF_SOLAR_FORECAST_TOMORROW_ENTITY,
)
from custom_components.smart_pool.solar_forecast import (
    learn_factor,
    parse_periods,
    plan_solar,
    solar_windows,
)

from .test_init import _advance, _entry, _setup

TZ = timezone(timedelta(hours=2))
CONFIRM = timedelta(minutes=10)


def _day(day: int, kw: dict[str, float]) -> list[dict]:
    """Solcast-like 30 min periods; ``kw`` maps 'HH:MM' to kW, rest 0."""
    out = []
    start = datetime(2026, 10, day, tzinfo=TZ)
    for i in range(48):
        t = start + timedelta(minutes=30 * i)
        out.append({"period_start": t.isoformat(), "pv_estimate": kw.get(t.strftime("%H:%M"), 0.0)})
    return out


SUNNY = {
    "09:00": 0.3,
    "09:30": 0.45,
    "10:00": 0.6,
    "10:30": 0.8,
    "11:00": 1.0,
    "11:30": 1.1,
    "12:00": 1.1,
    "12:30": 1.0,
    "13:00": 0.9,
    "13:30": 0.7,
    "14:00": 0.5,
    "14:30": 0.3,
}


def test_parse_and_windows():
    periods = parse_periods(_day(15, SUNNY), TZ)
    assert len(periods) == 48
    assert periods[18].watts == 300.0
    windows = solar_windows(periods, threshold_w=400, factor=1.0, confirm=CONFIRM)
    assert len(windows) == 1
    assert windows[0].start == datetime(2026, 10, 15, 9, 40, tzinfo=TZ)
    assert windows[0].end == datetime(2026, 10, 15, 14, 40, tzinfo=TZ)


def test_factor_shifts_window():
    periods = parse_periods(_day(15, SUNNY), TZ)
    windows = solar_windows(periods, threshold_w=400, factor=0.6, confirm=CONFIRM)
    assert windows[0].start == datetime(2026, 10, 15, 10, 40, tzinfo=TZ)
    assert windows[0].end == datetime(2026, 10, 15, 14, 10, tzinfo=TZ)


def test_plan_before_start_and_target_cap():
    periods = parse_periods(_day(15, SUNNY) + _day(16, SUNNY), TZ)
    now = datetime(2026, 10, 15, 8, 0, tzinfo=TZ)
    plan = plan_solar(
        periods,
        now=now,
        threshold_w=400,
        factor=1.0,
        confirm=CONFIRM,
        remaining_today_h=3.0,
        target_h=8.0,
    )
    assert not plan.running
    assert plan.next_start == datetime(2026, 10, 15, 9, 40, tzinfo=TZ)
    assert plan.end == datetime(2026, 10, 15, 12, 40, tzinfo=TZ)  # target reached first
    assert plan.hours_today == 3.0
    assert plan.tomorrow_start == datetime(2026, 10, 16, 9, 40, tzinfo=TZ)
    assert plan.tomorrow_hours == 5.0


def test_plan_running_and_after_sunset():
    periods = parse_periods(_day(15, SUNNY) + _day(16, SUNNY), TZ)
    running = plan_solar(
        periods,
        now=datetime(2026, 10, 15, 12, 0, tzinfo=TZ),
        threshold_w=400,
        factor=1.0,
        confirm=CONFIRM,
        remaining_today_h=8.0,
        target_h=8.0,
    )
    assert running.running
    assert running.next_start is None
    assert running.started == datetime(2026, 10, 15, 9, 40, tzinfo=TZ)
    assert running.end == datetime(2026, 10, 15, 14, 40, tzinfo=TZ)
    assert running.hours_today == 2.67
    evening = plan_solar(
        periods,
        now=datetime(2026, 10, 15, 18, 0, tzinfo=TZ),
        threshold_w=400,
        factor=1.0,
        confirm=CONFIRM,
        remaining_today_h=8.0,
        target_h=8.0,
    )
    assert evening.next_start is None and not evening.running
    assert evening.hours_today == 0
    assert evening.tomorrow_start == datetime(2026, 10, 16, 9, 40, tzinfo=TZ)


def test_cloudy_day_has_no_start():
    periods = parse_periods(_day(15, {"12:00": 0.3, "12:30": 0.35}), TZ)
    plan = plan_solar(
        periods,
        now=datetime(2026, 10, 15, 8, 0, tzinfo=TZ),
        threshold_w=400,
        factor=1.0,
        confirm=CONFIRM,
        remaining_today_h=8.0,
        target_h=8.0,
    )
    assert plan.next_start is None and plan.hours_today == 0


def test_learn_factor():
    assert learn_factor(1.0, 700, 1000) == 0.94
    assert learn_factor(1.0, 50, 100) == 1.0  # too little forecast to judge
    assert learn_factor(1.0, 5000, 1000) == 1.1  # ratio clamped to 1.5


async def test_solar_start_sensor(
    hass: HomeAssistant, sources, freezer: FrozenDateTimeFactory
) -> None:
    """The sensor shows the expected start from the configured forecast entities."""
    today = dt_util.start_of_local_day()
    freezer.move_to(today + timedelta(hours=7))

    def periods(day_start: datetime) -> list[dict]:
        return [
            {
                "period_start": (day_start + timedelta(minutes=30 * i)).isoformat(),
                "pv_estimate": 1.0 if 22 <= i < 30 else 0.0,  # 11:00-15:00
            }
            for i in range(48)
        ]

    hass.states.async_set("sensor.pv_today", "5", {"detailedForecast": periods(today)})
    hass.states.async_set(
        "sensor.pv_tomorrow", "5", {"detailedForecast": periods(today + timedelta(days=1))}
    )
    await _setup(
        hass,
        _entry(
            **{
                CONF_SOLAR_FORECAST_ENTITY: "sensor.pv_today",
                CONF_SOLAR_FORECAST_TOMORROW_ENTITY: "sensor.pv_tomorrow",
            }
        ),
    )
    await _advance(hass, freezer, timedelta(seconds=30))
    state = hass.states.get("sensor.pool_solar_start_forecast")
    assert dt_util.parse_datetime(state.state) == today + timedelta(hours=11, minutes=10)
    assert state.attributes["hours_today"] == 4.0
    assert len(state.attributes["curve"]) == 96
    assert float(hass.states.get("sensor.pool_solar_runtime_forecast").state) == 4.0
