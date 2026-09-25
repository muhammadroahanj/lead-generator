"""Live Rich dashboard, plus a plain-logging fallback.

A full run is thousands of searches over many hours. The old interface was a
stream of log lines with no totals, no ETA and no sense of whether anything
was working. This shows overall progress, the current search, running lead
counts and a rolling log in one screen.
"""

import logging
from collections import deque
from datetime import datetime

from rich.console import Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn
from rich.table import Table
from rich.text import Text

from geo.models import SearchUnit
from reporting import Reporter, RunStats, format_duration
from ui.console import console

MAX_LOG_LINES = 12


class DashboardLogHandler(logging.Handler):
    """Feeds log records into the dashboard's rolling panel.

    Without this, console logging and the Live display fight over the same
    terminal and both come out garbled.
    """

    def __init__(self, dashboard: "DashboardReporter"):
        super().__init__(level=logging.INFO)
        self.dashboard = dashboard

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.dashboard.on_log(record.getMessage(), level=record.levelname.lower())
        except Exception:  # pragma: no cover - logging must never crash a run
            pass


_LEVEL_STYLES = {
    "debug": "dim",
    "info": "white",
    "warning": "yellow",
    "error": "red",
    "critical": "bold red",
}


class DashboardReporter(Reporter):
    """Rich ``Live`` dashboard driven by orchestrator callbacks."""

    def __init__(self, title: str = "Google Maps Lead Scraper"):
        self.title = title
        self.stats: RunStats | None = None
        self.phase = "Starting..."
        self.current_unit: SearchUnit | None = None
        self.unit_index = 0
        self.unit_done = 0
        self.unit_total = 0
        self.last_lead: str = "-"
        self.logs: deque[tuple[str, str]] = deque(maxlen=MAX_LOG_LINES)

        self._live: Live | None = None
        self._handler: DashboardLogHandler | None = None
        self._console_handlers: list[logging.Handler] = []

        self.overall = Progress(
            TextColumn("[bold blue]Searches"),
            BarColumn(bar_width=None),
            TaskProgressColumn(),
            TextColumn("{task.completed}/{task.total}"),
            expand=True,
        )
        self.overall_task = self.overall.add_task("overall", total=1)

        self.unit_progress = Progress(
            TextColumn("[bold green]Results "),
            BarColumn(bar_width=None),
            TaskProgressColumn(),
            TextColumn("{task.completed}/{task.total}"),
            expand=True,
        )
        self.unit_task = self.unit_progress.add_task("unit", total=1)

    # --- Lifecycle ----------------------------------------------------------

    def start(self, stats: RunStats) -> None:
        self.stats = stats

        # Detach any stdout logging handlers; they would tear through the
        # Live display. The DEBUG file log is left untouched.
        root = logging.getLogger()
        self._console_handlers = [
            h for h in root.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        for handler in self._console_handlers:
            root.removeHandler(handler)

        self._handler = DashboardLogHandler(self)
        root.addHandler(self._handler)

        self._live = Live(
            self._render(), console=console, refresh_per_second=4, screen=False
        )
        self._live.start()

    def stop(self) -> None:
        if self._live:
            try:
                self._live.update(self._render())
                self._live.stop()
            except Exception:
                pass
            self._live = None

        root = logging.getLogger()
        if self._handler:
            root.removeHandler(self._handler)
            self._handler = None
        for handler in self._console_handlers:
            root.addHandler(handler)
        self._console_handlers = []

    def refresh(self) -> None:
        if self._live:
            try:
                self._live.update(self._render())
            except Exception:
                pass

    # --- Callbacks ----------------------------------------------------------

    def on_phase(self, message: str) -> None:
        self.phase = message
        self.refresh()

    def on_plan(self, units: list[SearchUnit]) -> None:
        self.overall.update(self.overall_task, total=max(1, len(units)), completed=0)
        self.phase = f"{len(units)} searches planned"
        self.refresh()

    def on_unit_start(self, unit: SearchUnit, index: int, total: int) -> None:
        self.current_unit = unit
        self.unit_index = index
        self.unit_done = 0
        self.unit_total = 0
        self.phase = unit.label
        # Drive the overall bar from the unit index: the run's counters are
        # only incremented after a unit finishes, so reading them here would
        # leave the bar permanently one unit behind.
        self.overall.update(self.overall_task, completed=index - 1)
        self.unit_progress.update(self.unit_task, total=1, completed=0)
        self.refresh()

    def on_unit_progress(self, done: int, total: int) -> None:
        self.unit_done = done
        self.unit_total = total
        self.unit_progress.update(self.unit_task, total=max(1, total), completed=done)
        self.refresh()

    def on_unit_end(self, unit: SearchUnit, found: int, unique: int, qualified: int) -> None:
        self.overall.update(self.overall_task, completed=self.unit_index)
        self.on_log(
            f"{unit.label}: {found} found, {unique} new, {qualified} qualified"
        )

    def on_business(self, business, unique: bool, qualified: bool) -> None:
        if qualified:
            self.last_lead = f"{business.name} — {business.phone or 'no phone'}"
        self.refresh()

    def on_log(self, message: str, level: str = "info") -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.logs.append((f"{stamp}  {message}", level))
        self.refresh()

    # --- Rendering ----------------------------------------------------------

    def _header(self) -> Panel:
        stats = self.stats or RunStats()
        line = Text()
        line.append(self.title, style="bold cyan")
        line.append("   elapsed ", style="dim")
        line.append(format_duration(stats.elapsed), style="bold")
        line.append("   ETA ", style="dim")
        line.append(format_duration(stats.eta_seconds), style="bold")
        subtitle = Text(self.phase, style="yellow")
        return Panel(Group(line, subtitle), border_style="cyan")

    def _stats_table(self) -> Panel:
        stats = self.stats or RunStats()
        table = Table.grid(padding=(0, 3))
        table.add_column(justify="right", style="dim")
        table.add_column(justify="left", style="bold")
        table.add_column(justify="right", style="dim")
        table.add_column(justify="left", style="bold")

        table.add_row("Found", str(stats.found), "Duplicates", str(stats.duplicates))
        table.add_row(
            "Unique", f"[cyan]{stats.unique}[/cyan]",
            "Qualified", f"[green]{stats.qualified}[/green]",
        )
        table.add_row(
            "Done", str(stats.units_done),
            "Failed", f"[red]{stats.units_failed}[/red]" if stats.units_failed else "0",
        )
        table.add_row(
            "Skipped", str(stats.units_skipped),
            "Blocks", f"[yellow]{stats.blocks}[/yellow]" if stats.blocks else "0",
        )
        latest = Text(f"Latest lead: {self.last_lead}", style="dim")
        return Panel(Group(table, latest), title="Stats", border_style="green")

    def _progress_panel(self) -> Panel:
        return Panel(
            Group(self.overall, self.unit_progress),
            title="Progress",
            border_style="blue",
        )

    def _log_panel(self) -> Panel:
        body = Text()
        for message, level in self.logs:
            body.append(message + "\n", style=_LEVEL_STYLES.get(level, "white"))
        if not self.logs:
            body.append("Waiting for activity...", style="dim")
        return Panel(body, title="Activity", border_style="dim")

    def _render(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(self._header(), size=4, name="header"),
            Layout(self._progress_panel(), size=4, name="progress"),
            Layout(name="body"),
        )
        layout["body"].split_row(
            # Stats needs enough width that its labels aren't ellipsized on a
            # narrow terminal.
            Layout(self._stats_table(), name="stats", ratio=2, minimum_size=34),
            Layout(self._log_panel(), name="logs", ratio=3),
        )
        return layout


class PlainReporter(Reporter):
    """Log-only reporter for non-TTY environments (Docker, CI, piped output)."""

    def __init__(self):
        self.stats: RunStats | None = None
        self.log = logging.getLogger("gmaps_scraper")

    def start(self, stats: RunStats) -> None:
        self.stats = stats

    def on_phase(self, message: str) -> None:
        self.log.info(message)

    def on_plan(self, units: list[SearchUnit]) -> None:
        self.log.info(f"Planned {len(units)} searches.")

    def on_unit_start(self, unit: SearchUnit, index: int, total: int) -> None:
        self.log.info(f"[{index}/{total}] {unit.label}")

    def on_unit_end(self, unit: SearchUnit, found: int, unique: int, qualified: int) -> None:
        self.log.info(
            f"    {unit.label}: {found} found, {unique} new, {qualified} qualified"
        )

    def on_log(self, message: str, level: str = "info") -> None:
        getattr(self.log, level if level in ("info", "warning", "error") else "info")(message)


def make_reporter(use_tui: bool) -> Reporter:
    """Pick the dashboard when the terminal can render it, else plain logs."""
    from ui.console import supports_live

    if use_tui and supports_live():
        return DashboardReporter()
    return PlainReporter()
