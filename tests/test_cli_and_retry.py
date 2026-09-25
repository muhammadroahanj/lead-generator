import asyncio

import pytest

from config.enums import Depth, LeadProfile
from main import _parse_grid, _resolve_metro, config_from_args, parse_args, prepare_config
from reporting import RunStats, format_duration
from scraper.retry import RetryExhausted, retry_async
from scraper.selectors import CRITICAL_SELECTOR_KEYS, SELECTORS


class TestCli:
    def test_tree_services_is_a_builtin_category(self):
        from config.categories import CATEGORIES

        assert "tree services" in CATEGORIES

    def test_prepare_config_runs_wizard_without_asyncio_loop(self, monkeypatch):
        args = parse_args([])
        monkeypatch.setattr("main.is_interactive", lambda: True)

        def fake_wizard(cfg):
            with pytest.raises(RuntimeError, match="no running event loop"):
                asyncio.get_running_loop()
            cfg.target_input = "Lahore"
            return cfg

        monkeypatch.setattr("ui.wizard.run_wizard", fake_wizard)
        cfg, exit_code = prepare_config(args)

        assert exit_code is None
        assert cfg.target_input == "Lahore"

    def test_city_and_categories(self):
        cfg = config_from_args(parse_args(["--city", "Austin TX", "--categories", "plumbers", "dentists"]))
        assert cfg.target_input == "Austin TX"
        assert cfg.categories == ["plumbers", "dentists"]

    def test_depth_and_profile(self):
        cfg = config_from_args(parse_args(["--city", "X", "--depth", "grid", "--profile", "all"]))
        assert cfg.depth is Depth.GRID
        assert cfg.profile is LeadProfile.ALL

    def test_metro_preset_resolves(self):
        cfg = config_from_args(parse_args(["--metro", "Houston"]))
        assert cfg.target_input == "Houston TX"

    def test_metro_preset_is_case_insensitive(self):
        assert _resolve_metro("houston") == "Houston TX"
        assert _resolve_metro("New York") == "New York NY"

    def test_unknown_metro_is_rejected(self):
        with pytest.raises(SystemExit):
            config_from_args(parse_args(["--metro", "Atlantis"]))

    def test_city_overrides_metro(self):
        cfg = config_from_args(parse_args(["--metro", "Houston", "--city", "Lahore"]))
        assert cfg.target_input == "Lahore"

    @pytest.mark.parametrize("value,expected", [
        ("3x3", (3, 3)), ("4X2", (4, 2)), ("5,5", (5, 5)),
        ("bad", None), ("3x", None), ("", None),
    ])
    def test_parse_grid(self, value, expected):
        assert _parse_grid(value) == expected

    def test_bad_grid_is_rejected(self):
        with pytest.raises(SystemExit):
            config_from_args(parse_args(["--city", "X", "--grid", "banana"]))

    def test_thresholds_and_flags(self):
        cfg = config_from_args(parse_args([
            "--city", "X", "--min-rating", "4.2", "--min-reviews", "10",
            "--no-require-phone", "--headless", "--no-resume", "--no-tui",
            "--max-results", "25", "--max-areas", "6", "--grid-span", "12",
        ]))
        assert cfg.min_rating == 4.2
        assert cfg.min_reviews == 10
        assert cfg.require_phone is False
        assert cfg.headless is True
        assert cfg.resume is False
        assert cfg.tui is False
        assert cfg.max_results_per_unit == 25
        assert cfg.max_subareas == 6
        assert cfg.grid_span_km == 12

    def test_concurrency(self):
        cfg = config_from_args(parse_args(["--city", "X", "--concurrency", "3"]))
        assert cfg.concurrency == 3

    def test_concurrency_defaults_to_serial(self):
        assert config_from_args(parse_args(["--city", "X"])).concurrency == 1

    def test_no_website_crawl_flag(self):
        cfg = config_from_args(parse_args(["--city", "X", "--profile", "no_email",
                                           "--no-website-crawl"]))
        assert cfg.crawl_websites is False

    def test_zero_values_are_honoured(self):
        # "0" is falsy; the old CLI treated --metros 0 as "no argument given"
        # and silently launched the wizard instead.
        cfg = config_from_args(parse_args(["--city", "X", "--min-reviews", "0"]))
        assert cfg.min_reviews == 0

    def test_output_directory_moves_every_artifact(self, tmp_path):
        cfg = config_from_args(parse_args(["--city", "X", "--output", str(tmp_path)]))
        assert cfg.output.leads_raw_csv.parent == tmp_path
        assert cfg.output.progress_file.parent == tmp_path

    def test_defaults_to_all_categories(self):
        from config.categories import CATEGORIES
        cfg = config_from_args(parse_args(["--city", "X"]))
        assert cfg.categories == list(CATEGORIES)


class TestSelectors:
    def test_every_chain_has_a_fallback(self):
        # Reading only entry [0] used to turn a Google class rotation into a
        # silent zero-result run, so chains must be genuinely plural.
        for key in ("results_feed", "result_link", "detail_loaded", "detail_name"):
            assert len(SELECTORS[key]) >= 2, key

    def test_critical_keys_exist(self):
        for key in CRITICAL_SELECTOR_KEYS:
            assert key in SELECTORS

    def test_detail_loaded_does_not_match_a_bare_h1(self):
        # A bare "h1" matched almost any page state, letting half-loaded
        # panels report as ready.
        assert "h1" not in SELECTORS["detail_loaded"]

    def test_result_link_prefers_the_semantic_selector(self):
        assert "href" in SELECTORS["result_link"][0]


class TestRetry:
    def test_returns_on_first_success(self):
        async def go():
            calls = []

            async def op():
                calls.append(1)
                return "ok"

            result = await retry_async(op, attempts=3, base_delay=0)
            return result, calls

        result, calls = asyncio.run(go())
        assert result == "ok"
        assert len(calls) == 1

    def test_retries_then_succeeds(self):
        async def go():
            calls = []

            async def op():
                calls.append(1)
                if len(calls) < 3:
                    raise RuntimeError("boom")
                return "ok"

            return await retry_async(op, attempts=3, base_delay=0), calls

        result, calls = asyncio.run(go())
        assert result == "ok"
        assert len(calls) == 3

    def test_raises_after_exhausting_attempts(self):
        async def go():
            async def op():
                raise RuntimeError("always fails")

            await retry_async(op, attempts=2, base_delay=0)

        with pytest.raises(RetryExhausted) as excinfo:
            asyncio.run(go())
        assert "always fails" in str(excinfo.value)
        assert excinfo.value.attempts == 2

    def test_cancellation_is_never_swallowed(self):
        # Ctrl-C must propagate immediately rather than being retried.
        async def go():
            async def op():
                raise asyncio.CancelledError()

            await retry_async(op, attempts=5, base_delay=0)

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(go())


class TestStats:
    def test_eta_is_unknown_before_any_unit_completes(self):
        assert RunStats(total_units=10).eta_seconds is None

    def test_eta_projects_from_average(self):
        stats = RunStats(total_units=10, units_done=2)
        stats.started_at -= 100  # pretend 100s elapsed
        assert stats.eta_seconds == pytest.approx(400, rel=0.05)

    def test_eta_is_zero_when_finished(self):
        stats = RunStats(total_units=2, units_done=2)
        assert stats.eta_seconds == 0.0

    @pytest.mark.parametrize("seconds,expected", [
        (None, "--"), (45, "45s"), (90, "1m 30s"), (7200, "2h 00m"),
    ])
    def test_format_duration(self, seconds, expected):
        assert format_duration(seconds) == expected
