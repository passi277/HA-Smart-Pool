"""Pure calculation and decision helpers (no Home Assistant imports).

Everything in here is deterministic and side-effect free so it can be unit
tested without a running Home Assistant instance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from .const import (
    FROST_RUN_MINUTES,
    MIN_SWITCH_INTERVAL_SECONDS,
    MODE_AUTO,
    MODE_CONTINUOUS,
    MODE_MANUAL,
    MODE_OFF,
    MODE_SOLAR,
    MODE_WINTER,
    ORP_RANGES,
    PH_MINUS_G_PER_M3_PER_STEP,
    PH_PLUS_G_PER_M3_PER_STEP,
    PH_RANGES,
    PH_TARGET,
    QUALITY_CHECK,
    QUALITY_CRITICAL,
    QUALITY_OK,
    QUALITY_UNKNOWN,
    SOLAR_CONFIRM_SECONDS,
    STATUS_FAULT,
    STATUS_FROST_PROTECTION,
    STATUS_MANUAL,
    STATUS_NO_AIR_TEMP,
    STATUS_OFF,
    STATUS_PUMP_UNAVAILABLE,
    STATUS_RUNNING_CATCHUP,
    STATUS_RUNNING_CONTINUOUS,
    STATUS_RUNNING_SCHEDULE,
    STATUS_RUNNING_SOLAR,
    STATUS_TARGET_REACHED,
    STATUS_WAITING_SCHEDULE,
    STATUS_WAITING_SUN,
    STATUS_WINTER_IDLE,
)

_SEVERITY = {QUALITY_UNKNOWN: 0, QUALITY_OK: 1, QUALITY_CHECK: 2, QUALITY_CRITICAL: 3}


def classify(value: float | None, ranges: tuple[float, float, float, float]) -> str:
    """Classify a reading as ok / check / critical against its ranges."""
    if value is None:
        return QUALITY_UNKNOWN
    crit_low, ok_low, ok_high, crit_high = ranges
    if value < crit_low or value > crit_high:
        return QUALITY_CRITICAL
    if ok_low <= value <= ok_high:
        return QUALITY_OK
    return QUALITY_CHECK


def classify_ph(value: float | None) -> str:
    """Classify a pH reading."""
    return classify(value, PH_RANGES)


def classify_orp(value: float | None) -> str:
    """Classify a redox (ORP) reading in mV."""
    return classify(value, ORP_RANGES)


def combine_quality(*statuses: str) -> str:
    """Return the worst of several quality states.

    Unknown readings only win if nothing else is known.
    """
    known = [s for s in statuses if s != QUALITY_UNKNOWN]
    if not known:
        return QUALITY_UNKNOWN
    return max(known, key=_SEVERITY.__getitem__)


def recommended_runtime(
    water_temp: float | None,
    *,
    volume_m3: float,
    pump_flow_m3h: float,
    orp_status: str,
    min_hours: float,
    max_hours: float,
) -> float:
    """Recommend a daily filter runtime in hours.

    Base rule of thumb: water temperature / 2. If the pump flow is known the
    runtime is at least one full turnover of the pool volume. Poor redox
    values add extra filter time. The result is clamped and rounded to 0.5 h.
    """
    hours = water_temp / 2 if water_temp is not None else min_hours
    if pump_flow_m3h > 0:
        hours = max(hours, volume_m3 / pump_flow_m3h)
    if orp_status == QUALITY_CHECK:
        hours += 1
    elif orp_status == QUALITY_CRITICAL:
        hours += 2
    hours = min(max(hours, min_hours), max(max_hours, min_hours))
    return round(hours * 2) / 2


def chlorine_dose(
    orp: float | None,
    *,
    volume_m3: float,
    strength_percent: float,
    step_ppm: float,
) -> float:
    """Grams of chlorine product to raise free chlorine when redox is low.

    1 ppm (mg/l) in 1 m³ equals 1 g active chlorine. Below the critical
    redox limit the step is doubled. Returns 0 if redox is fine or unknown.
    """
    if orp is None or strength_percent <= 0:
        return 0.0
    crit_low, ok_low, _, _ = ORP_RANGES
    if orp >= ok_low:
        return 0.0
    ppm = step_ppm * (2 if orp < crit_low else 1)
    grams = volume_m3 * ppm / (strength_percent / 100)
    return _round_to(grams, 5)


def ph_doses(ph: float | None, *, volume_m3: float) -> tuple[float, float]:
    """Return (pH-minus grams, pH-plus grams) to move pH back to the target.

    Only doses when pH is outside the ok range. Values are rough guidance;
    dosing should be split into portions and re-measured.
    """
    if ph is None:
        return 0.0, 0.0
    _, ok_low, ok_high, _ = PH_RANGES
    if ph > ok_high:
        steps = (ph - PH_TARGET) / 0.1
        return _round_to(steps * PH_MINUS_G_PER_M3_PER_STEP * volume_m3, 5), 0.0
    if ph < ok_low:
        steps = (PH_TARGET - ph) / 0.1
        return 0.0, _round_to(steps * PH_PLUS_G_PER_M3_PER_STEP * volume_m3, 5)
    return 0.0, 0.0


_GUIDANCE_TEXT = {
    "de": {
        "ph_high": "pH zu hoch: ca. {g} g pH-Minus zugeben",
        "ph_low": "pH zu niedrig: ca. {g} g pH-Plus zugeben",
        "orp_low": "Redox zu niedrig: ca. {g} g Chlor zugeben",
        "orp_high": "Redox zu hoch: kein Chlor zugeben",
    },
    "en": {
        "ph_high": "pH too high: add about {g} g pH minus",
        "ph_low": "pH too low: add about {g} g pH plus",
        "orp_low": "Redox too low: add about {g} g chlorine",
        "orp_high": "Redox too high: do not add chlorine",
    },
}
GUIDANCE_OK = "ok"
GUIDANCE_UNKNOWN = "unknown"


def guidance(
    *,
    ph: float | None,
    orp: float | None,
    ph_minus_g: float,
    ph_plus_g: float,
    chlorine_g: float,
    language: str,
) -> str:
    """Short action hint, pH first (correct pH before chlorinating).

    Returns "ok" when nothing needs to be done, the format the Modern Pool
    Card expects.
    """
    if ph is None and orp is None:
        return GUIDANCE_UNKNOWN
    text = _GUIDANCE_TEXT.get(language.split("-")[0], _GUIDANCE_TEXT["en"])
    parts: list[str] = []
    if ph_minus_g > 0:
        parts.append(text["ph_high"].format(g=f"{ph_minus_g:.0f}"))
    elif ph_plus_g > 0:
        parts.append(text["ph_low"].format(g=f"{ph_plus_g:.0f}"))
    if chlorine_g > 0:
        parts.append(text["orp_low"].format(g=f"{chlorine_g:.0f}"))
    elif orp is not None and orp > ORP_RANGES[2]:
        parts.append(text["orp_high"])
    return " · ".join(parts) or GUIDANCE_OK


def _round_to(value: float, base: float) -> float:
    return float(base * round(value / base))


def split_at_midnight(start: datetime, end: datetime) -> tuple[float, float]:
    """Split the interval into seconds before and after the local midnight.

    Returns (seconds_on_start_day, seconds_on_end_day). If both are on the
    same day the second value is 0.
    """
    if end <= start:
        return 0.0, 0.0
    if start.date() == end.date():
        return (end - start).total_seconds(), 0.0
    midnight = datetime.combine(end.date(), time.min, tzinfo=end.tzinfo)
    return (midnight - start).total_seconds(), (end - midnight).total_seconds()


@dataclass(slots=True)
class PumpInputs:
    """Snapshot of everything the pump decision depends on."""

    mode: str
    now: datetime
    pump_on: bool | None
    runtime_today_h: float
    target_runtime_h: float
    start_time: time
    catchup_time: time
    solar_surplus_since: datetime | None = None
    solar_deficit_since: datetime | None = None
    air_temp: float | None = None
    frost_temp: float = 2.0
    fault: bool = False
    last_switch: datetime | None = None


@dataclass(slots=True)
class PumpDecision:
    """What the pump should do (None = leave as is) and why."""

    turn_on: bool | None
    status: str


def decide_pump(inp: PumpInputs) -> PumpDecision:
    """Decide the desired pump state for the current mode."""
    if inp.mode == MODE_MANUAL:
        return PumpDecision(None, STATUS_MANUAL)
    if inp.pump_on is None:
        return PumpDecision(None, STATUS_PUMP_UNAVAILABLE)
    if inp.fault:
        return PumpDecision(False, STATUS_FAULT)
    if inp.mode == MODE_OFF:
        return PumpDecision(False, STATUS_OFF)

    decision = _decide_for_mode(inp)
    return _apply_switch_guard(inp, decision)


def _decide_for_mode(inp: PumpInputs) -> PumpDecision:
    if inp.mode == MODE_CONTINUOUS:
        return PumpDecision(True, STATUS_RUNNING_CONTINUOUS)

    if inp.mode == MODE_WINTER:
        if inp.air_temp is None:
            return PumpDecision(False, STATUS_NO_AIR_TEMP)
        if inp.air_temp <= inp.frost_temp:
            run = inp.now.minute < FROST_RUN_MINUTES
            return PumpDecision(run, STATUS_FROST_PROTECTION)
        return PumpDecision(False, STATUS_WINTER_IDLE)

    if inp.runtime_today_h >= inp.target_runtime_h:
        return PumpDecision(False, STATUS_TARGET_REACHED)

    now_t = inp.now.time()

    if inp.mode == MODE_AUTO:
        if now_t >= inp.start_time:
            return PumpDecision(True, STATUS_RUNNING_SCHEDULE)
        return PumpDecision(False, STATUS_WAITING_SCHEDULE)

    if inp.mode == MODE_SOLAR:
        if now_t >= inp.catchup_time:
            return PumpDecision(True, STATUS_RUNNING_CATCHUP)
        confirm = timedelta(seconds=SOLAR_CONFIRM_SECONDS)
        if inp.pump_on:
            deficit = inp.solar_deficit_since
            if deficit is not None and inp.now - deficit >= confirm:
                return PumpDecision(False, STATUS_WAITING_SUN)
            return PumpDecision(True, STATUS_RUNNING_SOLAR)
        surplus = inp.solar_surplus_since
        if surplus is not None and inp.now - surplus >= confirm:
            return PumpDecision(True, STATUS_RUNNING_SOLAR)
        return PumpDecision(False, STATUS_WAITING_SUN)

    return PumpDecision(None, STATUS_MANUAL)


def _apply_switch_guard(inp: PumpInputs, decision: PumpDecision) -> PumpDecision:
    """Avoid rapid on/off toggling (protects the pump motor)."""
    if decision.turn_on is None or decision.turn_on == inp.pump_on:
        return decision
    if inp.last_switch is None:
        return decision
    if (inp.now - inp.last_switch).total_seconds() < MIN_SWITCH_INTERVAL_SECONDS:
        return PumpDecision(None, decision.status)
    return decision
