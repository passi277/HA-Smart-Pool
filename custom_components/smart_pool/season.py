"""Season assistant and maintenance reminders (no Home Assistant imports)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

SEASON_SWIM = "swim"
SEASON_WINTERIZE = "winterize"
SEASON_WINTER = "winter"
SEASON_START = "season_start"
SEASONS = (SEASON_SWIM, SEASON_WINTERIZE, SEASON_WINTER, SEASON_START)

COLD_WATER = 12.0
WINTERIZE_DAYS = 5
SEASON_START_DAYS = 3
WINTERIZE_MONTHS = range(8, 13)
SEASON_START_MONTHS = range(3, 7)
TEMP_HISTORY_DAYS = 14

TASK_SAND = "sand"
TASK_PROBE = "probe"
TASK_SEALS = "seals"
MAINTENANCE_TASKS = (TASK_SAND, TASK_PROBE, TASK_SEALS)
DEFAULT_INTERVAL_DAYS = {TASK_SAND: 730, TASK_PROBE: 90, TASK_SEALS: 365}

CHECKLISTS = {
    "de": {
        SEASON_WINTERIZE: [
            "Einwintern: Rückspülen und Filter reinigen",
            "Einwintern: Wasserstand unter die Einlaufdüsen absenken",
            "Einwintern: Überwinterungsmittel zugeben",
            "Einwintern: Pumpe, Schläuche und Sonde abbauen und frostfrei lagern",
            "Einwintern: Betriebsart auf Winter oder Aus stellen",
        ],
        SEASON_START: [
            "Saisonstart: Becken reinigen und Wasser auffüllen",
            "Saisonstart: Pumpe, Schläuche und Sonde anschließen, Dichtungen prüfen",
            "Saisonstart: pH auf 7,0–7,4 einstellen",
            "Saisonstart: Metall-Ex zugeben (eisenhaltiges Füllwasser)",
            "Saisonstart: Schockchlorung starten",
            "Saisonstart: Sonde kalibrieren",
        ],
        TASK_SAND: ["Wartung: Filtersand wechseln"],
        TASK_PROBE: ["Wartung: Redox-/pH-Sonde kalibrieren"],
        TASK_SEALS: ["Wartung: Dichtungen und Schläuche der Pumpe prüfen"],
    },
    "en": {
        SEASON_WINTERIZE: [
            "Winterize: backwash and clean the filter",
            "Winterize: lower the water below the inlets",
            "Winterize: add winter chemical",
            "Winterize: remove pump, hoses and probe, store frost-free",
            "Winterize: set mode to winter or off",
        ],
        SEASON_START: [
            "Season start: clean the pool and top up water",
            "Season start: connect pump, hoses and probe, check seals",
            "Season start: set pH to 7.0–7.4",
            "Season start: add metal remover (iron-rich fill water)",
            "Season start: start shock chlorination",
            "Season start: calibrate the probe",
        ],
        TASK_SAND: ["Maintenance: replace filter sand"],
        TASK_PROBE: ["Maintenance: calibrate redox/pH probe"],
        TASK_SEALS: ["Maintenance: check pump seals and hoses"],
    },
}


def checklist(key: str, language: str) -> list[str]:
    """Localized checklist items for a season step or maintenance task."""
    table = CHECKLISTS.get(language.split("-")[0], CHECKLISTS["en"])
    return list(table.get(key, []))


@dataclass
class Season:
    """Daily water temperatures and maintenance dates."""

    days: dict[str, list[float]] = field(default_factory=dict)  # iso date -> [sum, count]
    maintenance: dict[str, str] = field(default_factory=dict)  # task -> iso date

    def as_dict(self) -> dict[str, Any]:
        """Serialize."""
        return {"days": self.days, "maintenance": self.maintenance}

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> Season:
        """Deserialize."""
        raw = raw or {}
        return cls(
            days={k: [float(v[0]), float(v[1])] for k, v in raw.get("days", {}).items()},
            maintenance=dict(raw.get("maintenance", {})),
        )

    # ------------------------------------------------------------ temperatures

    def add_temperature(self, today: date, value: float | None) -> None:
        """Add a temperature sample for today."""
        if value is None:
            return
        key = today.isoformat()
        total, count = self.days.get(key, [0.0, 0.0])
        self.days[key] = [total + value, count + 1]
        cutoff = (today - timedelta(days=TEMP_HISTORY_DAYS)).isoformat()
        self.days = {k: v for k, v in self.days.items() if k > cutoff}

    def daily_means(self, today: date, days: int) -> list[float] | None:
        """Means of the last complete `days` days, None if data is missing."""
        means = []
        for offset in range(1, days + 1):
            sample = self.days.get((today - timedelta(days=offset)).isoformat())
            if not sample or sample[1] == 0:
                return None
            means.append(sample[0] / sample[1])
        return means

    def status(self, today: date, winter_mode: bool) -> str:
        """Season state derived from the daily mean water temperature."""
        if winter_mode:
            means = self.daily_means(today, SEASON_START_DAYS)
            if (
                today.month in SEASON_START_MONTHS
                and means is not None
                and min(means) >= COLD_WATER
            ):
                return SEASON_START
            return SEASON_WINTER
        means = self.daily_means(today, WINTERIZE_DAYS)
        if today.month in WINTERIZE_MONTHS and means is not None and max(means) < COLD_WATER:
            return SEASON_WINTERIZE
        return SEASON_SWIM

    # ------------------------------------------------------------- maintenance

    def ensure_started(self, today: date) -> None:
        """Count maintenance intervals from installation if never done."""
        for task in MAINTENANCE_TASKS:
            self.maintenance.setdefault(task, today.isoformat())

    def done(self, task: str, today: date) -> None:
        """Mark a maintenance task as done today."""
        self.maintenance[task] = today.isoformat()

    def last_done(self, task: str) -> date | None:
        """Date a task was last done."""
        raw = self.maintenance.get(task)
        return date.fromisoformat(raw) if raw else None

    def due_tasks(self, today: date, intervals: dict[str, float]) -> list[str]:
        """Tasks whose interval has passed."""
        due = []
        for task in MAINTENANCE_TASKS:
            last = self.last_done(task)
            interval = intervals.get(task, DEFAULT_INTERVAL_DAYS[task])
            if last is not None and interval > 0 and (today - last).days >= interval:
                due.append(task)
        return due

    def next_due(self, task: str, intervals: dict[str, float]) -> date | None:
        """Date a task becomes due."""
        last = self.last_done(task)
        interval = intervals.get(task, DEFAULT_INTERVAL_DAYS[task])
        if last is None or interval <= 0:
            return None
        return last + timedelta(days=interval)
