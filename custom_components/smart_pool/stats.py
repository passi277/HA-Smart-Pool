"""Energy/solar statistics, weekly report, swim score and camera findings.

No Home Assistant imports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .chemistry import PRODUCT_UNITS, product_name

# --------------------------------------------------------------------- energy


@dataclass
class EnergyCounter:
    """Pump energy split into solar and grid share (from power readings)."""

    energy_kwh: float = 0.0
    solar_kwh: float = 0.0

    def add(self, seconds: float, pump_w: float | None, solar_w: float | None) -> None:
        """Integrate one interval of pump power."""
        if seconds <= 0 or pump_w is None or pump_w <= 0:
            return
        self.energy_kwh += pump_w * seconds / 3.6e6
        if solar_w is not None and solar_w > 0:
            self.solar_kwh += min(pump_w, solar_w) * seconds / 3.6e6

    @property
    def solar_share(self) -> float | None:
        """Solar share in percent."""
        if self.energy_kwh <= 0:
            return None
        return round(100 * self.solar_kwh / self.energy_kwh, 1)

    def as_dict(self) -> dict[str, float]:
        """Serialize."""
        return {"energy_kwh": self.energy_kwh, "solar_kwh": self.solar_kwh}

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> EnergyCounter:
        """Deserialize."""
        raw = raw or {}
        return cls(float(raw.get("energy_kwh", 0.0)), float(raw.get("solar_kwh", 0.0)))


def solar_savings_rate(pump_w: float | None, solar_w: float | None, price: float) -> float:
    """€ per hour currently saved by running the pump on solar power."""
    if not pump_w or not solar_w or pump_w <= 0 or solar_w <= 0:
        return 0.0
    return round(min(pump_w, solar_w) / 1000 * price, 3)


# ---------------------------------------------------------------- weekly report


@dataclass
class Range:
    """Min / max / mean accumulator."""

    low: float | None = None
    high: float | None = None
    total: float = 0.0
    count: int = 0

    def add(self, value: float | None) -> None:
        """Add a sample."""
        if value is None:
            return
        self.low = value if self.low is None else min(self.low, value)
        self.high = value if self.high is None else max(self.high, value)
        self.total += value
        self.count += 1

    @property
    def mean(self) -> float | None:
        """Mean of all samples."""
        return self.total / self.count if self.count else None

    def as_dict(self) -> dict[str, Any]:
        """Serialize."""
        return {"low": self.low, "high": self.high, "total": self.total, "count": self.count}

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> Range:
        """Deserialize."""
        raw = raw or {}
        return cls(raw.get("low"), raw.get("high"), raw.get("total", 0.0), raw.get("count", 0))


@dataclass
class WeekStats:
    """Accumulated values for the weekly report."""

    start: date | None = None
    runtime_s: float = 0.0
    energy: EnergyCounter = field(default_factory=EnergyCounter)
    ph: Range = field(default_factory=Range)
    orp: Range = field(default_factory=Range)
    water_temp: Range = field(default_factory=Range)
    outages: int = 0

    def as_dict(self) -> dict[str, Any]:
        """Serialize."""
        return {
            "start": self.start.isoformat() if self.start else None,
            "runtime_s": self.runtime_s,
            "energy": self.energy.as_dict(),
            "ph": self.ph.as_dict(),
            "orp": self.orp.as_dict(),
            "water_temp": self.water_temp.as_dict(),
            "outages": self.outages,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> WeekStats:
        """Deserialize."""
        raw = raw or {}
        return cls(
            start=date.fromisoformat(raw["start"]) if raw.get("start") else None,
            runtime_s=float(raw.get("runtime_s", 0.0)),
            energy=EnergyCounter.from_dict(raw.get("energy")),
            ph=Range.from_dict(raw.get("ph")),
            orp=Range.from_dict(raw.get("orp")),
            water_temp=Range.from_dict(raw.get("water_temp")),
            outages=int(raw.get("outages", 0)),
        )


REPORT_WEEKDAY = 6  # Sunday
REPORT_HOUR = 19


def report_due(now: datetime, last_report: date | None) -> bool:
    """The weekly report is due on Sunday from 19:00, once per day."""
    return now.weekday() == REPORT_WEEKDAY and now.hour >= REPORT_HOUR and last_report != now.date()


def build_report(
    week: WeekStats,
    *,
    doses: dict[str, float],
    price: float,
    language: str,
    now: datetime,
) -> tuple[str, dict[str, Any]]:
    """Return (short text, details) for the weekly report."""
    de = language.split("-")[0] == "de"
    hours = week.runtime_s / 3600
    energy = week.energy.energy_kwh
    cost = energy * price
    share = week.energy.solar_share
    details: dict[str, Any] = {
        "week": now.isocalendar().week,
        "runtime_hours": round(hours, 1),
        "energy_kwh": round(energy, 2),
        "solar_kwh": round(week.energy.solar_kwh, 2),
        "solar_share": share,
        "cost": round(cost, 2),
        "solar_savings": round(week.energy.solar_kwh * price, 2),
        "ph_min": week.ph.low,
        "ph_max": week.ph.high,
        "orp_min": week.orp.low,
        "orp_max": week.orp.high,
        "water_temp_min": week.water_temp.low,
        "water_temp_max": week.water_temp.high,
        "pump_outages": week.outages,
        "doses": {k: round(v) for k, v in doses.items()},
    }

    def num(value: float, digits: int = 1) -> str:
        text = f"{value:.{digits}f}"
        return text.replace(".", ",") if de else text

    parts = [
        f"{'KW' if de else 'Week'} {details['week']}",
        f"{num(hours)} h {'Filter' if de else 'filter'}",
    ]
    if energy > 0:
        parts.append(f"{num(energy)} kWh ({num(cost, 2)} €)")
    if share is not None:
        parts.append(f"{share:.0f} % Solar")
    if week.ph.low is not None and week.ph.high is not None:
        parts.append(f"pH {num(week.ph.low)}–{num(week.ph.high)}")
    if week.orp.low is not None and week.orp.high is not None:
        parts.append(f"Redox {week.orp.low:.0f}–{week.orp.high:.0f} mV")
    for product, amount in sorted(doses.items()):
        parts.append(f"{product_name(product, language)} {amount:.0f} {PRODUCT_UNITS[product]}")
    if week.outages:
        parts.append(f"{week.outages}× {'Pumpe offline' if de else 'pump offline'}")
    return " · ".join(parts), details


# ------------------------------------------------------------------ swim score


def _scale(value: float, low: float, high: float) -> float:
    if value <= low:
        return 0.0
    if value >= high:
        return 1.0
    return (value - low) / (high - low)


def swim_score(
    *,
    water_temp: float | None,
    air_temp: float | None,
    rain_mm: float | None,
    thunder: bool,
    quality: str,
) -> int | None:
    """0-100 rating how inviting the pool is today."""
    if water_temp is None:
        return None
    score = 50 * _scale(water_temp, 18, 28)
    score += 25 * (_scale(air_temp, 16, 30) if air_temp is not None else 0.5)
    score += 15 * (1 - _scale(rain_mm, 0, 5) if rain_mm is not None else 0.5)
    score += 10 * (0 if thunder else 1)
    if quality == "critical":
        score = min(score, 20)
    elif quality == "check":
        score = min(score, 70)
    return round(score)


def swim_label(score: int | None) -> str:
    """Category for the swim score."""
    if score is None:
        return "unknown"
    if score >= 80:
        return "great"
    if score >= 60:
        return "good"
    if score >= 35:
        return "fair"
    return "poor"


# ------------------------------------------------------------- camera finding

FINDING_CLOUDY = "cloudy"
FINDING_GREEN = "green"
FINDING_BROWN = "brown"
FINDING_DIRTY = "dirty"
FINDINGS = (FINDING_CLOUDY, FINDING_GREEN, FINDING_BROWN, FINDING_DIRTY)

_KEYWORDS = {
    FINDING_CLOUDY: ("trüb", "trueb", "milchig", "cloudy", "murky", "hazy"),
    FINDING_GREEN: ("grün", "gruen", "alge", "algen", "green", "algae"),
    FINDING_BROWN: ("braun", "bräunlich", "rost", "eisen", "gelblich", "brown", "rust", "iron"),
    FINDING_DIRTY: ("schmutz", "verschmutzt", "dreckig", "laub", "blätter", "dirty", "leaves"),
}
_NEGATIONS = ("nicht", "kein", "keine", "keinen", "ohne", "no", "not", "without")
_WORD = re.compile(r"[\wäöüß]+", re.IGNORECASE)


def parse_visual(text: str | None) -> list[str]:
    """Findings from a free-text camera/AI description, negations respected."""
    if not text:
        return []
    words = [w.lower() for w in _WORD.findall(text)]
    found: list[str] = []
    for finding, keywords in _KEYWORDS.items():
        for index, word in enumerate(words):
            if not any(word.startswith(k) for k in keywords):
                continue
            if any(w in _NEGATIONS for w in words[max(0, index - 2) : index]):
                continue
            found.append(finding)
            break
    return found
