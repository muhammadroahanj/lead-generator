"""Mid-search checkpoints so an interrupted unit resumes instead of restarting.

Previously this module wrote checkpoints that were never read, and only after
the search had already finished — the exact moment the data was safely in the
CSV. It now records which result links have been processed *during* a unit, so
a crash 100 detail visits in costs one result rather than all of them.

Only the processed hrefs are stored, not the businesses themselves: rows are
exported to CSV immediately, so re-storing them here would just be a second
copy that can drift out of sync.
"""

import hashlib
import logging
import re

from config.paths import OutputPaths, default_paths
from persistence.atomic import read_json, write_json_atomic

logger = logging.getLogger(__name__)

_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")


class CheckpointStore:
    """Per-unit record of which result links have already been scraped."""

    def __init__(self, paths: OutputPaths | None = None):
        self.paths = paths or default_paths()

    def _path(self, key: str):
        # Hash-suffixed so distinct keys can never collide after sanitizing,
        # while the readable prefix keeps the directory browsable.
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
        safe = _UNSAFE.sub("_", key)[:80].strip("_")
        return self.paths.checkpoint_dir / f"{safe}_{digest}.json"

    def load_done(self, key: str) -> set[str]:
        """Return the set of result hrefs already processed for this unit."""
        data = read_json(self._path(key), None)
        if isinstance(data, dict) and isinstance(data.get("done"), list):
            done = set(data["done"])
            if done:
                logger.info(f"Resuming '{key}' — {len(done)} results already done.")
            return done
        return set()

    def save_done(self, key: str, done: set[str]) -> None:
        write_json_atomic(self._path(key), {"key": key, "done": sorted(done)})

    def clear(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            try:
                path.unlink()
            except OSError as exc:
                logger.debug(f"Could not remove checkpoint {path.name}: {exc}")
