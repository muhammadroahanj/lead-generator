"""Run statistics and the reporter interface the orchestrator talks to.

Keeping this separate from the UI means the runner has no idea whether it is
driving a Rich dashboard or writing plain log lines.
"""

import time
from dataclasses import dataclass, field

from geo.models import SearchUnit


@dataclass
class RunStats:
    total_units: int = 0
    units_done: int = 0
    units_failed: int = 0
    units_skipped: int = 0
    found: int = 0
    unique: int = 0
    duplicates: int = 0
    qualified: int = 0
    blocks: int = 0
    retries: int = 0
    aborted_reason: str | None = None
    started_at: float = field(default_factory=time.monotonic)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def eta_seconds(self) -> float | None:
        """Projected remaining time from the average unit duration so far."""
        completed = self.units_done + self.units_failed + self.units_skipped
        if completed <= 0 or self.total_units <= 0:
            return None
        remaining = self.total_units - completed
        if remaining <= 0:
            return 0.0
        return (self.elapsed / completed) * remaining


class Reporter:
    """No-op reporter. Subclasses render progress however they like."""

    def start(self, stats: RunStats) -> None: ...
    def stop(self) -> None: ...

    def on_phase(self, message: str) -> None: ...
    def on_plan(self, units: list[SearchUnit]) -> None: ...
    def on_unit_start(self, unit: SearchUnit, index: int, total: int) -> None: ...
    def on_unit_progress(self, done: int, total: int) -> None: ...
    def on_unit_end(self, unit: SearchUnit, found: int, unique: int, qualified: int) -> None: ...
    def on_business(self, business, unique: bool, qualified: bool) -> None: ...
    def on_log(self, message: str, level: str = "info") -> None: ...
    def refresh(self) -> None: ...


def format_duration(seconds: float | None) -> str:
    """Human-readable duration, e.g. '2h 14m' or '45s'."""
    if seconds is None:
        return "--"
    seconds = int(max(0, seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"
