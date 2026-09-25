"""Cross-run deduplication of scraped businesses."""

import logging

from config import settings
from config.paths import OutputPaths, default_paths
from data.models import Business
from persistence.atomic import read_json, write_json_atomic

logger = logging.getLogger(__name__)


class Deduplicator:
    """Tracks seen businesses across searches and across runs.

    State is flushed every ``DEDUP_SAVE_EVERY`` records rather than only at
    shutdown, so a hard kill cannot lose the whole run's dedup pool and cause
    the next run to re-scrape (and duplicate) everything.
    """

    def __init__(self, paths: OutputPaths | None = None, save_every: int | None = None):
        self.paths = paths or default_paths()
        self.save_every = save_every if save_every is not None else settings.DEDUP_SAVE_EVERY
        self._seen: set[str] = set()
        self._since_save = 0
        self._load()

    def _load(self):
        data = read_json(self.paths.seen_keys_file, [])
        if isinstance(data, list):
            self._seen = set(data)
            if self._seen:
                logger.info(f"Loaded {len(self._seen)} previously seen businesses.")

    def save(self):
        write_json_atomic(self.paths.seen_keys_file, sorted(self._seen))
        self._since_save = 0

    def _maybe_save(self):
        self._since_save += 1
        if self.save_every > 0 and self._since_save >= self.save_every:
            self.save()

    def is_duplicate(self, business: Business) -> bool:
        return business.dedup_key in self._seen

    def mark_seen(self, business: Business):
        self._seen.add(business.dedup_key)
        self._maybe_save()

    def deduplicate(self, businesses: list[Business]) -> list[Business]:
        """Return only businesses not seen before, marking them as seen."""
        unique = []
        for business in businesses:
            if self.is_duplicate(business):
                continue
            self.mark_seen(business)
            unique.append(business)
        return unique

    @property
    def total_seen(self) -> int:
        return len(self._seen)
