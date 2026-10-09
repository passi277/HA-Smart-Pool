"""Special programs with automatic end (no Home Assistant imports)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

PROGRAM_NONE = "none"
PROGRAM_BOOST = "boost"
PROGRAM_SHOCK = "shock"
PROGRAM_NEW_FILL = "new_fill"
PROGRAM_ALGAE = "algae"

PROGRAMS = (PROGRAM_NONE, PROGRAM_BOOST, PROGRAM_SHOCK, PROGRAM_NEW_FILL, PROGRAM_ALGAE)

# Fixed durations in hours; boost uses the configurable boost hours.
PROGRAM_HOURS = {
    PROGRAM_SHOCK: 24.0,
    PROGRAM_NEW_FILL: 48.0,
    PROGRAM_ALGAE: 72.0,
}
DEFAULT_BOOST_HOURS = 2.0

# What has to happen after a program ended.
FOLLOW_UP_MEASURE = "measure"
FOLLOW_UP_BACKWASH = "backwash"
PROGRAM_FOLLOW_UP = {
    PROGRAM_SHOCK: FOLLOW_UP_MEASURE,
    PROGRAM_NEW_FILL: FOLLOW_UP_BACKWASH,
    PROGRAM_ALGAE: FOLLOW_UP_BACKWASH,
}


@dataclass
class ProgramState:
    """The running program, if any."""

    name: str = PROGRAM_NONE
    started: datetime | None = None
    until: datetime | None = None

    @property
    def active(self) -> bool:
        """A program is running."""
        return self.name != PROGRAM_NONE and self.until is not None

    def remaining_hours(self, now: datetime) -> float:
        """Hours left, 0 if idle."""
        if not self.active or self.until is None:
            return 0.0
        return max(0.0, (self.until - now).total_seconds() / 3600)

    def start(self, name: str, now: datetime, hours: float) -> None:
        """Start (or restart) a program; PROGRAM_NONE cancels."""
        if name not in PROGRAMS:
            raise ValueError(f"Unknown program {name}")
        if name == PROGRAM_NONE or hours <= 0:
            self.cancel()
            return
        self.name = name
        self.started = now
        self.until = now + timedelta(hours=hours)

    def cancel(self) -> None:
        """Stop the program without follow-up."""
        self.name = PROGRAM_NONE
        self.started = None
        self.until = None

    def tick(self, now: datetime) -> str | None:
        """Return the program name when it just ended."""
        if self.active and self.until is not None and now >= self.until:
            ended = self.name
            self.cancel()
            return ended
        return None

    def as_dict(self) -> dict[str, Any]:
        """Serialize."""
        return {
            "name": self.name,
            "started": self.started.isoformat() if self.started else None,
            "until": self.until.isoformat() if self.until else None,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> ProgramState:
        """Deserialize."""
        raw = raw or {}
        name = raw.get("name", PROGRAM_NONE)
        state = cls(
            name=name if name in PROGRAMS else PROGRAM_NONE,
            started=datetime.fromisoformat(raw["started"]) if raw.get("started") else None,
            until=datetime.fromisoformat(raw["until"]) if raw.get("until") else None,
        )
        if state.until is None:
            state.cancel()
        return state
