"""When will the solar mode run? Plan from a PV forecast (no Home Assistant imports).

The forecast is a list of periods (Solcast: 30 minutes) with the expected PV
power. The solar mode starts after the power has been above the threshold for
the confirmation time and stops after it has been below for the same time, so
a forecast window [start, end) means "pump on from start + confirm until
end + confirm". The pump also stops once the daily target is reached.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

DEFAULT_PERIOD = timedelta(minutes=30)

# Learned correction of the forecast against the measured PV power.
FACTOR_MIN = 0.3
FACTOR_MAX = 1.5
FACTOR_WEIGHT = 0.2
# Periods with less forecast power are too uncertain to learn from.
FACTOR_MIN_FORECAST_W = 200.0


@dataclass(frozen=True, slots=True)
class Period:
    """Forecast PV power for a period starting at ``start``."""

    start: datetime
    watts: float


@dataclass(frozen=True, slots=True)
class Window:
    """Expected pump run: from ``start`` to ``end``."""

    start: datetime
    end: datetime

    @property
    def hours(self) -> float:
        """Length in hours."""
        return (self.end - self.start).total_seconds() / 3600


@dataclass(slots=True)
class SolarPlan:
    """Expected solar runs today and tomorrow."""

    running: bool = False
    # Start of the window the pump is in now (when running).
    started: datetime | None = None
    next_start: datetime | None = None
    end: datetime | None = None
    hours_today: float = 0.0
    tomorrow_start: datetime | None = None
    tomorrow_end: datetime | None = None
    tomorrow_hours: float = 0.0
    windows: list[Window] = field(default_factory=list)


def _to_datetime(value: Any, tz: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def parse_periods(raw: Any, tz: Any) -> list[Period]:
    """Read a forecast attribute.

    Supports Solcast's ``detailedForecast`` (``period_start`` + ``pv_estimate``
    in kW) and generic lists with ``watts`` / ``value`` (W).
    """
    periods: list[Period] = []
    if not isinstance(raw, list):
        return periods
    for item in raw:
        if not isinstance(item, dict):
            continue
        start = _to_datetime(item.get("period_start") or item.get("datetime"), tz)
        if start is None:
            continue
        if "pv_estimate" in item:
            watts = float(item["pv_estimate"] or 0) * 1000
        elif "watts" in item or "value" in item:
            watts = float(item.get("watts", item.get("value")) or 0)
        else:
            continue
        periods.append(Period(start, watts))
    periods.sort(key=lambda p: p.start)
    return periods


def forecast_watts(periods: list[Period], when: datetime) -> float | None:
    """Forecast power for the period containing ``when``."""
    for index, period in enumerate(periods):
        end = (
            periods[index + 1].start if index + 1 < len(periods) else period.start + DEFAULT_PERIOD
        )
        if period.start <= when < end:
            return period.watts
    return None


def solar_windows(
    periods: list[Period], *, threshold_w: float, factor: float, confirm: timedelta
) -> list[Window]:
    """Expected pump runs: forecast above the threshold, shifted by the confirmation time."""
    windows: list[Window] = []
    run_start: datetime | None = None
    for index, period in enumerate(periods):
        end = (
            periods[index + 1].start if index + 1 < len(periods) else period.start + DEFAULT_PERIOD
        )
        above = period.watts * factor >= threshold_w
        if above and run_start is None:
            run_start = period.start
        if run_start is not None and (not above or index + 1 == len(periods)):
            stop = end if above else period.start
            if stop - run_start > confirm:
                windows.append(Window(run_start + confirm, stop + confirm))
            run_start = None
    return windows


def _take(windows: list[Window], hours: float) -> list[Window]:
    """Use windows until ``hours`` of runtime are reached."""
    taken: list[Window] = []
    left = hours
    for window in windows:
        if left <= 0:
            break
        if window.hours > left:
            window = Window(window.start, window.start + timedelta(hours=left))
        taken.append(window)
        left -= window.hours
    return taken


def plan_solar(
    periods: list[Period],
    *,
    now: datetime,
    threshold_w: float,
    factor: float,
    confirm: timedelta,
    remaining_today_h: float,
    target_h: float,
) -> SolarPlan:
    """Plan the solar runs for the rest of today and for tomorrow."""
    windows = solar_windows(periods, threshold_w=threshold_w, factor=factor, confirm=confirm)
    today: date = now.date()
    plan = SolarPlan()

    rest_today = [
        Window(max(w.start, now), w.end) for w in windows if w.start.date() == today and w.end > now
    ]
    used = _take(rest_today, max(0.0, remaining_today_h))
    plan.windows = used
    plan.hours_today = round(sum(w.hours for w in used), 2)
    if used:
        first = used[0]
        plan.running = first.start <= now
        plan.next_start = None if plan.running else first.start
        if plan.running:
            plan.started = next(w.start for w in windows if w.start <= now < w.end)
        plan.end = first.end

    tomorrow = today + timedelta(days=1)
    used_tomorrow = _take([w for w in windows if w.start.date() == tomorrow], max(0.0, target_h))
    if used_tomorrow:
        plan.tomorrow_start = used_tomorrow[0].start
        plan.tomorrow_end = used_tomorrow[-1].end
        plan.tomorrow_hours = round(sum(w.hours for w in used_tomorrow), 2)
    return plan


def learn_factor(factor: float, measured_w: float, forecast_w: float) -> float:
    """Blend the ratio measured/forecast of one period into the correction factor."""
    if forecast_w < FACTOR_MIN_FORECAST_W:
        return factor
    ratio = min(FACTOR_MAX, max(FACTOR_MIN, measured_w / forecast_w))
    blended = (1 - FACTOR_WEIGHT) * factor + FACTOR_WEIGHT * ratio
    return round(min(FACTOR_MAX, max(FACTOR_MIN, blended)), 3)
