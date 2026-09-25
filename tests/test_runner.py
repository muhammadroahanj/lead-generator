"""Orchestration tests for ScraperRun, with the browser and scraper stubbed out."""

import asyncio

import pytest

import runner as runner_mod
from config.enums import Depth, LeadProfile
from config.paths import OutputPaths
from config.runconfig import RunConfig
from data.models import Business
from geo.models import Target
from runner import AbortRun, ScraperRun
from scraper.maps_scraper import UnitResult


class FakeBrowser:
    """Stands in for BrowserManager. Records context rotations."""

    instances: list["FakeBrowser"] = []

    def __init__(self, headless=None, proxy=None, **kwargs):
        self.contexts = 0
        self.closed = False
        FakeBrowser.instances.append(self)

    async def start(self):
        return await self.new_context()

    async def new_context(self):
        self.contexts += 1
        return object()

    def set_region(self, lng):
        pass

    async def close(self):
        self.closed = True


def make_business(name: str, **kwargs) -> Business:
    defaults = dict(phone="555-0000", rating=4.5, review_count=10)
    defaults.update(kwargs)
    return Business(name=name, **defaults)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Stub browser, network delays and target resolution."""
    FakeBrowser.instances = []
    monkeypatch.setattr(runner_mod, "BrowserManager", FakeBrowser)

    async def no_delay(*args, **kwargs):
        return None

    monkeypatch.setattr(runner_mod, "search_delay", no_delay)
    monkeypatch.setattr(runner_mod, "random_delay", no_delay)

    async def fake_resolve(page, raw):
        return Target(raw=raw, display_name=raw, lat=30.0, lng=-97.0, zoom=12, region="TX")

    monkeypatch.setattr(runner_mod, "resolve_target", fake_resolve)
    return monkeypatch


def build_cfg(tmp_path, **kwargs) -> RunConfig:
    params = dict(
        target_input="Austin TX",
        categories=["plumbers"],
        depth=Depth.CITY,
        profile=LeadProfile.ALL,
        output=OutputPaths(root=tmp_path),
    )
    params.update(kwargs)
    return RunConfig(**params)


def install_scrape(monkeypatch, handler):
    """Replace search_and_scrape with a handler(unit, on_business) -> UnitResult."""
    async def fake_scrape(page, unit, cfg, *, on_business=None, on_progress=None,
                          on_processed=None, skip_hrefs=None):
        return handler(unit, on_business)

    monkeypatch.setattr(runner_mod, "search_and_scrape", fake_scrape)


class TestHappyPath:
    def test_runs_every_unit_and_exports(self, tmp_path, env):
        def handler(unit, on_business):
            result = UnitResult()
            for i in range(3):
                b = make_business(f"{unit.category} {i}", place_id=f"pid-{unit.category}-{i}")
                result.businesses.append(b)
                on_business(b)
            return result

        install_scrape(env, handler)
        cfg = build_cfg(tmp_path, categories=["plumbers", "dentists"])
        run = ScraperRun(cfg)
        stats = asyncio.run(run.execute())

        assert stats.total_units == 2
        assert stats.units_done == 2
        assert stats.found == 6
        assert stats.unique == 6
        assert stats.qualified == 6
        assert run.summary()["raw_rows"] == 6
        assert cfg.output.leads_qualified_csv.exists()

    def test_duplicates_are_counted_not_exported(self, tmp_path, env):
        def handler(unit, on_business):
            result = UnitResult()
            for _ in range(2):
                b = make_business("Same Shop", place_id="pid-same")
                result.businesses.append(b)
                on_business(b)
            return result

        install_scrape(env, handler)
        cfg = build_cfg(tmp_path, categories=["plumbers", "dentists"])
        run = ScraperRun(cfg)
        stats = asyncio.run(run.execute())

        assert stats.found == 4
        assert stats.unique == 1
        assert stats.duplicates == 3
        assert run.summary()["raw_rows"] == 1

    def test_profile_controls_qualification(self, tmp_path, env):
        def handler(unit, on_business):
            result = UnitResult()
            with_site = make_business("Has Site", place_id="p1", has_website=True,
                                      website_url="https://x.com")
            without = make_business("No Site", place_id="p2")
            for b in (with_site, without):
                result.businesses.append(b)
                on_business(b)
            return result

        install_scrape(env, handler)
        cfg = build_cfg(tmp_path, profile=LeadProfile.NO_WEBSITE)
        run = ScraperRun(cfg)
        stats = asyncio.run(run.execute())

        assert stats.unique == 2
        assert stats.qualified == 1


class TestResume:
    def test_completed_units_are_skipped_on_rerun(self, tmp_path, env):
        calls = []

        def handler(unit, on_business):
            calls.append(unit.key)
            b = make_business("A", place_id="pid-a")
            on_business(b)
            return UnitResult(businesses=[b])

        install_scrape(env, handler)

        first = ScraperRun(build_cfg(tmp_path))
        asyncio.run(first.execute())
        assert len(calls) == 1

        second = ScraperRun(build_cfg(tmp_path))
        stats = asyncio.run(second.execute())
        assert len(calls) == 1           # not scraped again
        assert stats.units_skipped == 1

    def test_no_resume_rescrapes(self, tmp_path, env):
        calls = []

        def handler(unit, on_business):
            calls.append(unit.key)
            return UnitResult(businesses=[make_business("A", place_id="pid-a")])

        install_scrape(env, handler)
        asyncio.run(ScraperRun(build_cfg(tmp_path)).execute())
        asyncio.run(ScraperRun(build_cfg(tmp_path, resume=False)).execute())
        assert len(calls) == 2

    def test_failed_units_are_retried_next_run(self, tmp_path, env):
        calls = []

        def handler(unit, on_business):
            calls.append(unit.key)
            return UnitResult(error="no results feed")

        install_scrape(env, handler)
        asyncio.run(ScraperRun(build_cfg(tmp_path)).execute())
        stats = asyncio.run(ScraperRun(build_cfg(tmp_path)).execute())

        assert len(calls) == 2
        assert stats.units_skipped == 0
        assert stats.units_failed == 1


class TestFailureHandling:
    def test_exception_fails_the_unit_but_not_the_run(self, tmp_path, env):
        def handler(unit, on_business):
            if unit.category == "plumbers":
                raise RuntimeError("page exploded")
            b = make_business("B", place_id="pid-b")
            on_business(b)
            return UnitResult(businesses=[b])

        install_scrape(env, handler)
        cfg = build_cfg(tmp_path, categories=["plumbers", "dentists"])
        stats = asyncio.run(ScraperRun(cfg).execute())

        assert stats.units_failed == 1
        assert stats.units_done == 1
        assert stats.unique == 1

    def test_block_is_retried_once_then_succeeds(self, tmp_path, env):
        attempts = []

        def handler(unit, on_business):
            attempts.append(unit.key)
            if len(attempts) == 1:
                return UnitResult(blocked=True, error="blocked mid-search")
            b = make_business("C", place_id="pid-c")
            on_business(b)
            return UnitResult(businesses=[b])

        install_scrape(env, handler)
        run = ScraperRun(build_cfg(tmp_path))
        stats = asyncio.run(run.execute())

        assert len(attempts) == 2
        assert stats.blocks == 1
        assert stats.units_done == 1

    def test_persistent_blocking_aborts_the_run(self, tmp_path, env):
        def handler(unit, on_business):
            return UnitResult(blocked=True, error="blocked")

        install_scrape(env, handler)
        cfg = build_cfg(tmp_path, categories=["a", "b", "c", "d", "e", "f"])
        run = ScraperRun(cfg)
        stats = asyncio.run(run.execute())

        # Stops rather than hammering the same IP forever.
        assert stats.aborted_reason is not None
        assert "Blocked" in stats.aborted_reason

    def test_state_is_saved_even_when_aborting(self, tmp_path, env):
        def handler(unit, on_business):
            if unit.category == "plumbers":
                b = make_business("D", place_id="pid-d")
                on_business(b)
                return UnitResult(businesses=[b])
            return UnitResult(blocked=True)

        install_scrape(env, handler)
        cfg = build_cfg(tmp_path, categories=["plumbers", "a", "b", "c", "d", "e"])
        run = ScraperRun(cfg)
        asyncio.run(run.execute())

        assert cfg.output.leads_raw_csv.exists()
        assert cfg.output.seen_keys_file.exists()
        assert cfg.output.progress_file.exists()


class TestPlanning:
    def test_area_depth_expands_the_plan(self, tmp_path, env):
        async def fake_discover(page, target, cfg, probe_category, on_business=None,
                                probe_limit=40):
            return ["Katy", "Sugar Land", "Pearland"], []

        env.setattr(runner_mod, "discover_subareas", fake_discover)
        install_scrape(env, lambda unit, on_business: UnitResult())

        cfg = build_cfg(tmp_path, depth=Depth.AREAS)
        run = ScraperRun(cfg)
        asyncio.run(run.execute())

        assert run.stats.total_units == 3
        assert {u.area for u in run.units} == {"Katy", "Sugar Land", "Pearland"}

    def test_grid_depth_expands_the_plan(self, tmp_path, env):
        install_scrape(env, lambda unit, on_business: UnitResult())
        cfg = build_cfg(tmp_path, depth=Depth.GRID, grid_rows=2, grid_cols=3)
        run = ScraperRun(cfg)
        asyncio.run(run.execute())
        assert run.stats.total_units == 6

    def test_empty_plan_exits_cleanly(self, tmp_path, env):
        install_scrape(env, lambda unit, on_business: UnitResult())
        cfg = build_cfg(tmp_path, categories=[])
        stats = asyncio.run(ScraperRun(cfg).execute())
        assert stats.total_units == 0
        assert stats.aborted_reason is None


class TestConcurrency:
    def test_pool_covers_every_unit_exactly_once(self, tmp_path, env):
        seen = []

        def handler(unit, on_business):
            seen.append(unit.key)
            b = make_business(unit.category, place_id=f"pid-{unit.category}")
            on_business(b)
            return UnitResult(businesses=[b])

        install_scrape(env, handler)
        cfg = build_cfg(tmp_path, categories=[f"c{i}" for i in range(8)], concurrency=3)
        run = ScraperRun(cfg)
        stats = asyncio.run(run.execute())

        assert sorted(seen) == sorted(u.key for u in run.units)
        assert len(seen) == 8
        assert stats.units_done == 8

    def test_pool_starts_one_browser_per_worker(self, tmp_path, env):
        install_scrape(env, lambda unit, on_business: UnitResult(
            businesses=[make_business("x", place_id="p")]))
        cfg = build_cfg(tmp_path, categories=["a", "b", "c", "d"], concurrency=3)
        asyncio.run(ScraperRun(cfg).execute())

        assert len(FakeBrowser.instances) == 3
        assert all(b.closed for b in FakeBrowser.instances)

    def test_serial_by_default(self, tmp_path, env):
        install_scrape(env, lambda unit, on_business: UnitResult())
        cfg = build_cfg(tmp_path, categories=["a", "b"])
        asyncio.run(ScraperRun(cfg).execute())
        assert len(FakeBrowser.instances) == 1
