"""Pure calculation and decision helpers (no Home Assistant imports).

Everything in here is deterministic and side-effect free so it can be unit
tested without a running Home Assistant instance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

from .const import (
    DEFAULT_WATER_DEPTH_M,
    FROST_RUN_MINUTES,
    HIGH_UV,
    HOT_TEMP,
    METAL_EX_PH_RANGE,
    METAL_EX_PH_TARGET,
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
    RAIN_HINT_MM,
    SOLAR_CONFIRM_SECONDS,
    STATUS_FAULT,
    STATUS_FROST_PROTECTION,
    STATUS_MANUAL,
    STATUS_NO_AIR_TEMP,
    STATUS_OFF,
    STATUS_PUMP_UNAVAILABLE,
    STATUS_RUNNING_CATCHUP,
    STATUS_RUNNING_CONTINUOUS,
    STATUS_RUNNING_METAL_EX,
    STATUS_RUNNING_PROGRAM,
    STATUS_RUNNING_SCHEDULE,
    STATUS_RUNNING_SOLAR,
    STATUS_TARGET_REACHED,
    STATUS_WAITING_SCHEDULE,
    STATUS_WAITING_SUN,
    STATUS_WINTER_IDLE,
    THUNDER_CONDITIONS,
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
    extra_hours: float = 0.0,
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
    hours += extra_hours
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
        "metal_ph_high": "Für Metall-Ex erst pH auf 7,0–7,4 senken (ca. {g} g pH-Minus)",
        "metal_ph_low": "Für Metall-Ex erst pH auf 7,0–7,4 anheben (ca. {g} g pH-Plus)",
        "metal_dose": "{ml} ml Metall-Ex bei laufender Pumpe zugeben – erst danach chloren",
        "metal_running": "Metall-Ex wirkt noch {h} h – Pumpe laufen lassen",
        "metal_backwash": "Metall-Ex fertig: Filter rückspülen",
        "multitab": "Multitab nachlegen: {n} Tab in Skimmer oder Dosierschwimmer",
        "after_shock": "Schockchlorung beendet: Wasserwerte prüfen",
        "visual_brown": "Wasser bräunlich (Kamera): Eisen – ca. {ml} ml Metall-Ex zugeben",
        "visual_green": "Wasser grün (Kamera): Algen-Programm starten",
        "visual_cloudy_ok": "Wasser trüb (Kamera) trotz guter Werte – rückspülen, Sonde prüfen",
        "visual_cloudy": "Wasser trüb (Kamera): Filter länger laufen lassen",
        "visual_dirty": "Verschmutzung (Kamera): Skimmer und Boden reinigen",
        "probe": "Redox reagiert nicht auf Chlor – Sonde reinigen und kalibrieren",
    },
    "en": {
        "ph_high": "pH too high: add about {g} g pH minus",
        "ph_low": "pH too low: add about {g} g pH plus",
        "orp_low": "Redox too low: add about {g} g chlorine",
        "orp_high": "Redox too high: do not add chlorine",
        "metal_ph_high": "Before metal remover lower pH to 7.0–7.4 (about {g} g pH minus)",
        "metal_ph_low": "Before metal remover raise pH to 7.0–7.4 (about {g} g pH plus)",
        "metal_dose": "Add {ml} ml metal remover with the pump running – chlorinate afterwards",
        "metal_running": "Metal remover still working for {h} h – keep the pump running",
        "metal_backwash": "Metal remover done: backwash the filter",
        "multitab": "Add a multi tab: {n} tab into skimmer or floating dispenser",
        "after_shock": "Shock chlorination finished: check the water values",
        "visual_brown": "Water brownish (camera): iron – add about {ml} ml metal remover",
        "visual_green": "Water green (camera): start the algae program",
        "visual_cloudy_ok": "Water cloudy (camera) despite good values – backwash, check probe",
        "visual_cloudy": "Water cloudy (camera): run the filter longer",
        "visual_dirty": "Dirt (camera): clean skimmer and floor",
        "probe": "Redox does not react to chlorine – clean and calibrate the probe",
    },
}
GUIDANCE_OK = "ok"
GUIDANCE_UNKNOWN = "unknown"


def _texts(language: str, table: dict[str, dict[str, str]]) -> dict[str, str]:
    return table.get(language.split("-")[0], table["en"])


@dataclass(slots=True)
class GuidanceInputs:
    """Everything the action hint depends on."""

    ph: float | None
    orp: float | None
    volume_m3: float
    ph_minus_g: float = 0.0
    ph_plus_g: float = 0.0
    chlorine_g: float = 0.0
    metal_ex_pending_ml: float = 0.0
    metal_ex_hours_left: float = 0.0
    metal_ex_backwash: bool = False
    metal_ex_pool_ml: float = 0.0
    after_shock: bool = False
    visual: tuple[str, ...] = ()
    probe_suspect: bool = False
    multitab_due_tabs: int = 0
    language: str = "en"


def guidance(inp: GuidanceInputs) -> str:
    """Short action hint in the order the steps should be done.

    Fresh (iron-rich) water first needs metal remover at pH 7.0-7.4 before
    any chlorine, otherwise the iron oxidises and stains the water. Returns
    "ok" when nothing needs to be done, the format the Modern Pool Card
    expects.
    """
    text = _texts(inp.language, _GUIDANCE_TEXT)
    parts: list[str] = []

    if inp.metal_ex_pending_ml > 0:
        minus, plus = metal_ex_ph_doses(inp.ph, volume_m3=inp.volume_m3)
        if minus > 0:
            parts.append(text["metal_ph_high"].format(g=f"{minus:.0f}"))
        elif plus > 0:
            parts.append(text["metal_ph_low"].format(g=f"{plus:.0f}"))
        parts.append(text["metal_dose"].format(ml=f"{inp.metal_ex_pending_ml:.0f}"))
        return " · ".join(parts)

    if inp.metal_ex_hours_left > 0:
        parts.append(text["metal_running"].format(h=f"{inp.metal_ex_hours_left:.0f}"))
    elif inp.metal_ex_backwash:
        parts.append(text["metal_backwash"])
    if inp.after_shock:
        parts.append(text["after_shock"])
    if inp.multitab_due_tabs > 0:
        parts.append(text["multitab"].format(n=inp.multitab_due_tabs))

    values_ok = (
        inp.ph_minus_g <= 0 and inp.ph_plus_g <= 0 and inp.chlorine_g <= 0 and inp.ph is not None
    )
    if "brown" in inp.visual and inp.metal_ex_hours_left <= 0:
        parts.append(text["visual_brown"].format(ml=f"{inp.metal_ex_pool_ml:.0f}"))
    if "green" in inp.visual:
        parts.append(text["visual_green"])
    if "cloudy" in inp.visual:
        parts.append(text["visual_cloudy_ok" if values_ok else "visual_cloudy"])
    if "dirty" in inp.visual:
        parts.append(text["visual_dirty"])

    if inp.ph is None and inp.orp is None:
        return " · ".join(parts) or GUIDANCE_UNKNOWN
    if inp.ph_minus_g > 0:
        parts.append(text["ph_high"].format(g=f"{inp.ph_minus_g:.0f}"))
    elif inp.ph_plus_g > 0:
        parts.append(text["ph_low"].format(g=f"{inp.ph_plus_g:.0f}"))
    if inp.chlorine_g > 0:
        parts.append(text["orp_low"].format(g=f"{inp.chlorine_g:.0f}"))
    elif inp.orp is not None and inp.orp > ORP_RANGES[2]:
        parts.append(text["orp_high"])
    if inp.probe_suspect:
        parts.append(text["probe"])
    return " · ".join(parts) or GUIDANCE_OK


# --- Metal remover ---------------------------------------------------------


def surface_area(volume_m3: float, configured_m2: float) -> float:
    """Water surface in m², estimated from the volume if not configured."""
    if configured_m2 > 0:
        return configured_m2
    return volume_m3 / DEFAULT_WATER_DEPTH_M


def refill_liters(cm: float, surface_m2: float) -> float:
    """Litres for raising the water level by `cm` (1 cm on 1 m² = 10 l)."""
    return max(0.0, cm) * surface_m2 * 10


def metal_ex_dose(liters: float, ml_per_m3: float) -> float:
    """Millilitres of metal remover for the given amount of water."""
    if liters <= 0 or ml_per_m3 <= 0:
        return 0.0
    return _round_to(liters / 1000 * ml_per_m3, 10)


def metal_ex_ph_doses(ph: float | None, *, volume_m3: float) -> tuple[float, float]:
    """(pH-minus g, pH-plus g) to bring pH into 7.0-7.4 before metal remover."""
    if ph is None:
        return 0.0, 0.0
    low, high = METAL_EX_PH_RANGE
    if ph > high:
        steps = (ph - METAL_EX_PH_TARGET) / 0.1
        return _round_to(steps * PH_MINUS_G_PER_M3_PER_STEP * volume_m3, 5), 0.0
    if ph < low:
        steps = (METAL_EX_PH_TARGET - ph) / 0.1
        return 0.0, _round_to(steps * PH_PLUS_G_PER_M3_PER_STEP * volume_m3, 5)
    return 0.0, 0.0


# --- Weather ---------------------------------------------------------------


@dataclass(slots=True)
class ForecastSummary:
    """Next 24 hours of the weather forecast."""

    rain_mm: float = 0.0
    max_temp: float | None = None
    min_temp: float | None = None
    uv_max: float | None = None
    thunder: bool = False
    current_hour_rain_mm: float | None = None


def _as_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def summarize_forecast(
    forecast: list[dict[str, Any]], now: datetime, *, hourly: bool
) -> ForecastSummary:
    """Summarise the next 24 h of a weather.get_forecasts response."""
    summary = ForecastSummary()
    horizon = now + timedelta(hours=24)
    hour_start = now.replace(minute=0, second=0, microsecond=0)
    temps: list[float] = []
    lows: list[float] = []
    uvs: list[float] = []
    for item in forecast:
        when = _parse_dt(item.get("datetime"))
        if when is None:
            continue
        # Hourly: entries overlapping the next 24 h. Daily: only today.
        if hourly and (when + timedelta(hours=1) <= now or when >= horizon):
            continue
        rain = _as_float(item.get("precipitation")) or 0.0
        summary.rain_mm += rain
        if hourly and when == hour_start:
            summary.current_hour_rain_mm = rain
        if (temp := _as_float(item.get("temperature"))) is not None:
            temps.append(temp)
        if (low := _as_float(item.get("templow"))) is not None:
            lows.append(low)
        if (uv := _as_float(item.get("uv_index"))) is not None:
            uvs.append(uv)
        if item.get("condition") in THUNDER_CONDITIONS:
            summary.thunder = True
        if not hourly:
            break
    summary.rain_mm = round(summary.rain_mm, 1)
    summary.max_temp = max(temps) if temps else None
    summary.min_temp = min(lows or temps) if (lows or temps) else None
    summary.uv_max = max(uvs) if uvs else None
    return summary


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def weather_extra_hours(*, heavy_rain: bool, max_temp: float | None, uv_max: float | None) -> float:
    """Extra filter hours: +1 after heavy rain, +1 on hot or high-UV days."""
    extra = 1.0 if heavy_rain else 0.0
    if (max_temp is not None and max_temp >= HOT_TEMP) or (
        uv_max is not None and uv_max >= HIGH_UV
    ):
        extra += 1.0
    return extra


_WEATHER_TEXT = {
    "de": {
        "heavy_rain": "Starkregen ({mm} mm): pH und Redox prüfen, Filter läuft länger",
        "rain": "{mm} mm Regen in 24 h erwartet (≈ {l} l) – Nachfüllen mit Brunnenwasser verschieben",
        "thunder": "Gewitter erwartet – danach Filter länger laufen lassen",
        "hot": "Hitze/hohe UV-Belastung – abends chloren, Filter läuft länger",
    },
    "en": {
        "heavy_rain": "Heavy rain ({mm} mm): check pH and redox, filter runs longer",
        "rain": "{mm} mm rain expected in 24 h (≈ {l} l) – postpone refilling",
        "thunder": "Thunderstorm expected – run the filter longer afterwards",
        "hot": "Heat/high UV – chlorinate in the evening, filter runs longer",
    },
}


def weather_hint(
    *,
    rain_last_24h: float,
    heavy_rain: bool,
    forecast: ForecastSummary | None,
    surface_m2: float,
    language: str,
) -> str:
    """Weather related advice, "ok" if there is nothing to mention."""
    text = _texts(language, _WEATHER_TEXT)
    parts: list[str] = []
    if heavy_rain:
        parts.append(text["heavy_rain"].format(mm=f"{rain_last_24h:.0f}"))
    if forecast is not None:
        if forecast.rain_mm >= RAIN_HINT_MM:
            liters = forecast.rain_mm * surface_m2
            parts.append(text["rain"].format(mm=f"{forecast.rain_mm:.0f}", l=f"{liters:.0f}"))
        if forecast.thunder:
            parts.append(text["thunder"])
        if weather_extra_hours(
            heavy_rain=False, max_temp=forecast.max_temp, uv_max=forecast.uv_max
        ):
            parts.append(text["hot"])
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
    metal_ex_active: bool = False
    program_active: bool = False


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

    if inp.program_active:
        return PumpDecision(True, STATUS_RUNNING_PROGRAM)

    # Metal remover needs the filter running for the whole treatment.
    if inp.metal_ex_active:
        return PumpDecision(True, STATUS_RUNNING_METAL_EX)

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
