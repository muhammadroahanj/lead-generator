"""The dashboard must never engage where it cannot render (Docker, CI, pipes)."""

import logging

from geo.models import SearchUnit
from reporting import RunStats
from ui.dashboard import DashboardReporter, PlainReporter, make_reporter


class TestReporterSelection:
    def test_falls_back_to_plain_without_a_tty(self):
        # pytest captures stdout, so this process is exactly the non-TTY case
        # Docker Compose creates with tty: false.
        assert isinstance(make_reporter(use_tui=True), PlainReporter)

    def test_no_tui_flag_forces_plain(self):
        assert isinstance(make_reporter(use_tui=False), PlainReporter)

    def test_plain_reporter_accepts_the_full_callback_surface(self):
        reporter = PlainReporter()
        unit = SearchUnit(category="plumbers", query="q", city="Austin")
        stats = RunStats(total_units=1)

        reporter.start(stats)
        reporter.on_phase("resolving")
        reporter.on_plan([unit])
        reporter.on_unit_start(unit, 1, 1)
        reporter.on_unit_progress(1, 10)
        reporter.on_business(object(), unique=True, qualified=True)
        reporter.on_unit_end(unit, found=1, unique=1, qualified=1)
        reporter.on_log("hello", level="warning")
        reporter.refresh()
        reporter.stop()


class TestDashboardRendering:
    def test_renders_without_a_live_display(self):
        dash = DashboardReporter()
        dash.stats = RunStats(total_units=4)
        unit = SearchUnit(category="plumbers", query="q", city="Austin", area="Katy")

        dash.on_plan([unit] * 4)
        dash.on_unit_start(unit, 2, 4)
        dash.on_unit_progress(5, 20)
        dash.on_log("something happened", level="error")

        # Must not raise even though start() was never called.
        assert dash._render() is not None

    def test_overall_bar_tracks_the_unit_index(self):
        # Reading run counters here would leave the bar one unit behind, since
        # they are only incremented after a unit finishes.
        dash = DashboardReporter()
        dash.stats = RunStats(total_units=10)
        unit = SearchUnit(category="x", query="q", city="c")

        dash.on_plan([unit] * 10)
        dash.on_unit_start(unit, 3, 10)
        assert dash.overall.tasks[0].completed == 2

        dash.on_unit_end(unit, found=1, unique=1, qualified=1)
        assert dash.overall.tasks[0].completed == 3

    def test_log_panel_is_bounded(self):
        dash = DashboardReporter()
        dash.stats = RunStats()
        for i in range(100):
            dash.on_log(f"line {i}")
        assert len(dash.logs) <= 12

    def test_stop_restores_console_logging(self):
        # The dashboard detaches stdout handlers so they don't tear through the
        # Live display; it must put them back.
        root = logging.getLogger()
        handler = logging.StreamHandler()
        root.addHandler(handler)
        try:
            dash = DashboardReporter()
            dash.start(RunStats())
            assert handler not in root.handlers
            dash.stop()
            assert handler in root.handlers
        finally:
            root.removeHandler(handler)
