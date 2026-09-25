import json

import pytest

from config.enums import Depth, LeadProfile
from config.paths import OutputPaths
from config.runconfig import RunConfig
from data.dedup import Deduplicator
from data.exporter import CSV_HEADERS, Exporter, get_csv_row_count
from data.models import Business
from data.qualifier import filter_qualified, is_qualified_lead
from persistence.atomic import read_json, write_json_atomic
from persistence.checkpoint import CheckpointStore
from persistence.progress import ProgressTracker


def make_business(**kwargs) -> Business:
    defaults = dict(name="Joe's Pizza", phone="555-1234", rating=4.5, review_count=20)
    defaults.update(kwargs)
    return Business(**defaults)


@pytest.fixture
def paths(tmp_path) -> OutputPaths:
    return OutputPaths(root=tmp_path).ensure()


class TestQualifier:
    def test_no_website_profile_accepts_website_less_business(self):
        assert is_qualified_lead(make_business(has_website=False), LeadProfile.NO_WEBSITE)

    def test_no_website_profile_rejects_business_with_site(self):
        b = make_business(has_website=True, website_url="https://x.com")
        assert not is_qualified_lead(b, LeadProfile.NO_WEBSITE)

    def test_no_email_profile_wants_a_site_but_no_email(self):
        with_site = make_business(has_website=True, website_url="https://x.com")
        assert is_qualified_lead(with_site, LeadProfile.NO_EMAIL)

        with_email = make_business(has_website=True, website_url="https://x.com",
                                   email="hi@x.com")
        assert not is_qualified_lead(with_email, LeadProfile.NO_EMAIL)

        without_site = make_business(has_website=False)
        assert not is_qualified_lead(without_site, LeadProfile.NO_EMAIL)

    def test_all_profile_accepts_everything(self):
        junk = Business(name="X")  # no phone, no rating, has no website
        assert is_qualified_lead(junk, LeadProfile.ALL)

    def test_phone_requirement(self):
        no_phone = make_business(phone=None)
        assert not is_qualified_lead(no_phone, LeadProfile.NO_WEBSITE)
        assert is_qualified_lead(no_phone, LeadProfile.NO_WEBSITE, require_phone=False)

    def test_thresholds_are_applied(self):
        low = make_business(rating=2.0, review_count=100)
        assert not is_qualified_lead(low, LeadProfile.NO_WEBSITE, min_rating=3.0)
        assert is_qualified_lead(low, LeadProfile.NO_WEBSITE, min_rating=1.0)

        few = make_business(rating=5.0, review_count=1)
        assert not is_qualified_lead(few, LeadProfile.NO_WEBSITE, min_reviews=5)
        assert is_qualified_lead(few, LeadProfile.NO_WEBSITE, min_reviews=1)

    def test_unknown_rating_is_not_disqualifying(self):
        # Plenty of genuine small businesses have no rating yet.
        unrated = make_business(rating=None, review_count=None)
        assert is_qualified_lead(unrated, LeadProfile.NO_WEBSITE, min_rating=4.0)

    def test_filter_qualified(self):
        businesses = [
            make_business(name="A", has_website=False),
            make_business(name="B", has_website=True, website_url="https://b.com"),
            make_business(name="C", has_website=False, phone=None),
        ]
        assert [b.name for b in filter_qualified(businesses, LeadProfile.NO_WEBSITE)] == ["A"]


class TestAtomicJson:
    def test_roundtrip(self, tmp_path):
        path = tmp_path / "x.json"
        write_json_atomic(path, {"a": 1})
        assert read_json(path, None) == {"a": 1}

    def test_missing_file_returns_default(self, tmp_path):
        assert read_json(tmp_path / "nope.json", "fallback") == "fallback"

    def test_corrupt_file_returns_default(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        assert read_json(path, {}) == {}

    def test_no_temp_files_left_behind(self, tmp_path):
        write_json_atomic(tmp_path / "x.json", [1, 2, 3])
        assert [p.name for p in tmp_path.iterdir()] == ["x.json"]


class TestDedup:
    def test_filters_duplicates(self, paths):
        dedup = Deduplicator(paths)
        a = make_business(place_id="0xabc:0x1")
        b = make_business(place_id="0xabc:0x1", name="Different Name")
        assert len(dedup.deduplicate([a, b])) == 1

    def test_persists_across_instances(self, paths):
        first = Deduplicator(paths)
        first.deduplicate([make_business(place_id="0xabc:0x1")])
        first.save()

        second = Deduplicator(paths)
        assert second.is_duplicate(make_business(place_id="0xabc:0x1"))

    def test_auto_saves_before_shutdown(self, paths):
        # A hard kill must not lose the whole run's dedup pool.
        dedup = Deduplicator(paths, save_every=2)
        dedup.deduplicate([
            make_business(place_id="0x1:0x1"),
            make_business(place_id="0x2:0x2"),
        ])
        stored = json.loads(paths.seen_keys_file.read_text(encoding="utf-8"))
        assert len(stored) == 2


class TestProgress:
    def test_completed_units_are_remembered(self, paths):
        tracker = ProgressTracker(paths)
        tracker.mark_completed("Houston::plumbers")
        assert ProgressTracker(paths).is_completed("Houston::plumbers")

    def test_failed_units_are_retried_next_run(self, paths):
        tracker = ProgressTracker(paths)
        tracker.mark_failed("Houston::plumbers")
        assert not ProgressTracker(paths).is_completed("Houston::plumbers")

    def test_stats(self, paths):
        tracker = ProgressTracker(paths)
        tracker.mark_completed("a")
        tracker.mark_completed("b")
        tracker.mark_failed("c")
        assert tracker.stats["completed"] == 2
        assert tracker.stats["failed"] == 1

    def test_reset(self, paths):
        tracker = ProgressTracker(paths)
        tracker.mark_completed("a")
        tracker.reset()
        assert not ProgressTracker(paths).is_completed("a")


class TestCheckpoints:
    def test_roundtrip(self, paths):
        store = CheckpointStore(paths)
        store.save_done("Houston::plumbers", {"/maps/place/a", "/maps/place/b"})
        assert store.load_done("Houston::plumbers") == {"/maps/place/a", "/maps/place/b"}

    def test_missing_checkpoint_is_empty(self, paths):
        assert CheckpointStore(paths).load_done("nothing") == set()

    def test_clear(self, paths):
        store = CheckpointStore(paths)
        store.save_done("k", {"a"})
        store.clear("k")
        assert store.load_done("k") == set()

    def test_similar_keys_do_not_collide(self, paths):
        # Sanitizing "a/b" and "a b" to the same filename would merge two units.
        store = CheckpointStore(paths)
        store.save_done("a/b::x", {"one"})
        store.save_done("a b::x", {"two"})
        assert store.load_done("a/b::x") == {"one"}
        assert store.load_done("a b::x") == {"two"}


class TestExporter:
    def test_writes_header_and_rows(self, paths):
        exporter = Exporter(paths, flush_every=1)
        exporter.add_raw(make_business())
        exporter.flush()
        assert get_csv_row_count(paths.leads_raw_csv) == 1

    def test_buffers_until_flush(self, paths):
        exporter = Exporter(paths, flush_every=10)
        exporter.add_raw(make_business())
        assert get_csv_row_count(paths.leads_raw_csv) == 0
        exporter.flush()
        assert get_csv_row_count(paths.leads_raw_csv) == 1

    def test_appends_across_runs(self, paths):
        first = Exporter(paths, flush_every=1)
        first.add_raw(make_business())
        first.flush()

        second = Exporter(paths, flush_every=1)
        second.add_raw(make_business(name="Other"))
        second.flush()
        assert get_csv_row_count(paths.leads_raw_csv) == 2

    def test_archives_a_csv_with_stale_headers(self, paths):
        # Appending new-schema rows onto an old-schema file misaligns every
        # column, so the old file is moved aside instead.
        paths.leads_raw_csv.write_text("Name,Phone\nOld,555\n", encoding="utf-8")

        exporter = Exporter(paths, flush_every=1)
        exporter.add_raw(make_business())
        exporter.flush()

        header = paths.leads_raw_csv.read_text(encoding="utf-8").splitlines()[0]
        assert header.split(",")[:3] == CSV_HEADERS[:3]
        assert any("legacy-" in p.name for p in paths.root.iterdir())

    def test_xlsx_export(self, paths):
        exporter = Exporter(paths, flush_every=1)
        exporter.add_raw(make_business())
        exporter.add_qualified(make_business())
        assert exporter.export_xlsx() == paths.leads_xlsx
        assert paths.leads_xlsx.exists()


class TestRunConfig:
    def test_coerces_strings_to_enums(self):
        cfg = RunConfig(depth="grid", profile="all")
        assert cfg.depth is Depth.GRID
        assert cfg.profile is LeadProfile.ALL

    def test_website_crawl_is_skipped_when_it_cannot_help(self):
        # Under NO_WEBSITE any business with a site is rejected outright, so
        # crawling that site is pure wasted time.
        assert not RunConfig(profile=LeadProfile.NO_WEBSITE).crawl_websites
        assert RunConfig(profile=LeadProfile.NO_EMAIL).crawl_websites
        assert not RunConfig(profile=LeadProfile.NO_EMAIL, fetch_website_email=False).crawl_websites

    @pytest.mark.parametrize("proxy,expected", [
        (None, None),
        ("http://host:8080", {"server": "http://host:8080"}),
        ("http://user:pass@host:8080",
         {"server": "http://host:8080", "username": "user", "password": "pass"}),
    ])
    def test_proxy_dict(self, proxy, expected):
        assert RunConfig(proxy=proxy).proxy_dict() == expected

    def test_concurrency_is_at_least_one(self):
        assert RunConfig(concurrency=0).concurrency == 1
