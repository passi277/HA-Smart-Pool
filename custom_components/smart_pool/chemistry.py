"""Chemical log, stock keeping and probe plausibility (no Home Assistant imports)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

PRODUCT_CHLORINE = "chlorine"
PRODUCT_SHOCK = "shock"
PRODUCT_PH_MINUS = "ph_minus"
PRODUCT_PH_PLUS = "ph_plus"
PRODUCT_METAL_EX = "metal_ex"
PRODUCT_MULTITAB = "multitab"

PRODUCTS = (
    PRODUCT_CHLORINE,
    PRODUCT_SHOCK,
    PRODUCT_PH_MINUS,
    PRODUCT_PH_PLUS,
    PRODUCT_METAL_EX,
    PRODUCT_MULTITAB,
)
# Multitabs dissolve over days, so they are not used for the probe check.
CHLORINE_PRODUCTS = (PRODUCT_CHLORINE, PRODUCT_SHOCK)

PRODUCT_UNITS = {
    PRODUCT_CHLORINE: "g",
    PRODUCT_SHOCK: "g",
    PRODUCT_PH_MINUS: "g",
    PRODUCT_PH_PLUS: "g",
    PRODUCT_METAL_EX: "ml",
    PRODUCT_MULTITAB: "Tab",
}

PRODUCT_NAMES = {
    "de": {
        PRODUCT_CHLORINE: "Chlor-Granulat",
        PRODUCT_SHOCK: "Chlor-Schock",
        PRODUCT_PH_MINUS: "pH-Minus",
        PRODUCT_PH_PLUS: "pH-Plus",
        PRODUCT_METAL_EX: "Metall-Ex",
        PRODUCT_MULTITAB: "Multitabs",
    },
    "en": {
        PRODUCT_CHLORINE: "Chlorine granules",
        PRODUCT_SHOCK: "Shock chlorine",
        PRODUCT_PH_MINUS: "pH minus",
        PRODUCT_PH_PLUS: "pH plus",
        PRODUCT_METAL_EX: "Metal remover",
        PRODUCT_MULTITAB: "Multi tabs",
    },
}

# Probe check: after chlorinating, redox must rise noticeably once the pump
# has distributed the chlorine and a new measurement arrived.
PROBE_CHECK_AFTER = timedelta(hours=6)
PROBE_CHECK_GIVE_UP = timedelta(hours=48)
PROBE_MIN_RISE_MV = 30.0
PROBE_FAILURES_FOR_WARNING = 2
LOG_LIMIT = 200

SHOCK_PPM = 10.0


def product_name(product: str, language: str) -> str:
    """Localized product name."""
    names = PRODUCT_NAMES.get(language.split("-")[0], PRODUCT_NAMES["en"])
    return names.get(product, product)


def shock_dose(volume_m3: float, strength_percent: float) -> float:
    """Grams of product to raise free chlorine by ~10 mg/l (shock)."""
    if strength_percent <= 0:
        return 0.0
    return float(10 * round(volume_m3 * SHOCK_PPM / (strength_percent / 100) / 10))


def low_stock_thresholds(
    *, volume_m3: float, chlorine_strength: float, metal_ex_pool_ml: float
) -> dict[str, float]:
    """Stock below which a product is considered low.

    Chlorine: three regular doses (1 mg/l each). Shock: one shock dose.
    pH products: enough to move the pH by 0.6. Metal remover: one preventive
    dose for the whole pool.
    """
    regular = volume_m3 / (chlorine_strength / 100) if chlorine_strength > 0 else 0.0
    return {
        PRODUCT_CHLORINE: round(3 * regular),
        PRODUCT_SHOCK: shock_dose(volume_m3, chlorine_strength),
        PRODUCT_PH_MINUS: round(volume_m3 * 60),
        PRODUCT_PH_PLUS: round(volume_m3 * 60),
        PRODUCT_METAL_EX: round(metal_ex_pool_ml),
        PRODUCT_MULTITAB: 2,
    }


@dataclass(slots=True)
class DoseEntry:
    """One logged chemical addition."""

    time: datetime
    product: str
    amount: float
    orp_before: float | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize."""
        return {
            "time": self.time.isoformat(),
            "product": self.product,
            "amount": self.amount,
            "orp_before": self.orp_before,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DoseEntry:
        """Deserialize."""
        return cls(
            time=datetime.fromisoformat(raw["time"]),
            product=raw["product"],
            amount=float(raw["amount"]),
            orp_before=raw.get("orp_before"),
        )


@dataclass(slots=True)
class ProbeCheckResult:
    """Outcome of one dose-effect check."""

    rise_mv: float
    ok: bool


@dataclass
class Chemistry:
    """Dose log, season consumption, stock and redox probe plausibility."""

    log: list[DoseEntry] = field(default_factory=list)
    consumption: dict[str, float] = field(default_factory=dict)
    stock: dict[str, float] = field(default_factory=dict)
    shopping_added: set[str] = field(default_factory=set)
    pending_check: DoseEntry | None = None
    probe_failures: int = 0
    last_rise_mv: float | None = None

    # ------------------------------------------------------------- persistence

    def as_dict(self) -> dict[str, Any]:
        """Serialize."""
        return {
            "log": [e.as_dict() for e in self.log],
            "consumption": self.consumption,
            "stock": self.stock,
            "shopping_added": sorted(self.shopping_added),
            "pending_check": self.pending_check.as_dict() if self.pending_check else None,
            "probe_failures": self.probe_failures,
            "last_rise_mv": self.last_rise_mv,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> Chemistry:
        """Deserialize."""
        raw = raw or {}
        pending = raw.get("pending_check")
        return cls(
            log=[DoseEntry.from_dict(e) for e in raw.get("log", [])],
            consumption={k: float(v) for k, v in raw.get("consumption", {}).items()},
            stock={k: float(v) for k, v in raw.get("stock", {}).items()},
            shopping_added=set(raw.get("shopping_added", [])),
            pending_check=DoseEntry.from_dict(pending) if pending else None,
            probe_failures=int(raw.get("probe_failures", 0)),
            last_rise_mv=raw.get("last_rise_mv"),
        )

    # ------------------------------------------------------------------ dosing

    def add_dose(self, now: datetime, product: str, amount: float, orp: float | None) -> DoseEntry:
        """Log a dose, update consumption and stock, start a probe check."""
        if product not in PRODUCTS:
            raise ValueError(f"Unknown product {product}")
        entry = DoseEntry(now, product, max(0.0, amount), orp)
        self.log.append(entry)
        del self.log[:-LOG_LIMIT]
        self.consumption[product] = self.consumption.get(product, 0.0) + entry.amount
        if product in self.stock:
            self.stock[product] = max(0.0, self.stock[product] - entry.amount)
        if product in CHLORINE_PRODUCTS and orp is not None and entry.amount > 0:
            self.pending_check = entry
        return entry

    def last_dose(self, product: str | None = None) -> DoseEntry | None:
        """Most recent dose, optionally of one product."""
        for entry in reversed(self.log):
            if product is None or entry.product == product:
                return entry
        return None

    def doses_since(self, since: datetime) -> dict[str, float]:
        """Sum of doses per product since a point in time."""
        totals: dict[str, float] = {}
        for entry in self.log:
            if entry.time >= since:
                totals[entry.product] = totals.get(entry.product, 0.0) + entry.amount
        return totals

    def reset_season(self) -> None:
        """Start a new season: clear consumption (log and stock stay)."""
        self.consumption = {}

    # ------------------------------------------------------------------- stock

    def set_stock(self, product: str, amount: float) -> None:
        """Set the stock of a product (starts tracking it)."""
        self.stock[product] = max(0.0, amount)

    def low_products(self, thresholds: dict[str, float]) -> list[str]:
        """Tracked products whose stock is below their threshold."""
        return [
            product
            for product, amount in self.stock.items()
            if amount < thresholds.get(product, 0.0)
        ]

    def products_to_shop(self, thresholds: dict[str, float]) -> list[str]:
        """Low products not yet put on the shopping list; refilled ones are re-armed."""
        low = set(self.low_products(thresholds))
        self.shopping_added &= low
        new = sorted(low - self.shopping_added)
        self.shopping_added |= set(new)
        return new

    # ------------------------------------------------------------ probe check

    def evaluate_probe(
        self, now: datetime, orp: float | None, last_measurement: datetime | None
    ) -> ProbeCheckResult | None:
        """Check whether redox rose after the last chlorine dose."""
        entry = self.pending_check
        if entry is None or entry.orp_before is None:
            return None
        if now - entry.time > PROBE_CHECK_GIVE_UP:
            self.pending_check = None
            return None
        if now - entry.time < PROBE_CHECK_AFTER or orp is None:
            return None
        if last_measurement is None or last_measurement < entry.time + timedelta(hours=1):
            return None
        rise = orp - entry.orp_before
        ok = rise >= PROBE_MIN_RISE_MV
        self.probe_failures = 0 if ok else self.probe_failures + 1
        self.last_rise_mv = round(rise, 1)
        self.pending_check = None
        return ProbeCheckResult(rise, ok)

    @property
    def probe_suspect(self) -> bool:
        """Redox did not react to chlorine several times in a row."""
        return self.probe_failures >= PROBE_FAILURES_FOR_WARNING

    def probe_calibrated(self) -> None:
        """Reset the plausibility check after calibrating the probe."""
        self.probe_failures = 0
        self.pending_check = None
        self.last_rise_mv = None


def multitab_tabs(volume_m3: float, m3_per_tab: float) -> int:
    """Tabs per dose: one per started m3_per_tab of water."""
    if m3_per_tab <= 0:
        return 1
    return max(1, math.ceil(volume_m3 / m3_per_tab - 1e-9))


def multitab_next(last: datetime | None, interval_days: float) -> datetime | None:
    """When the next multitab is due (None until the first one was logged)."""
    if last is None or interval_days <= 0:
        return None
    return last + timedelta(days=interval_days)
