"""Progress tracking for resumable scraping."""

import logging

from config.paths import OutputPaths, default_paths
from persistence.atomic import read_json, write_json_atomic

logger = logging.getLogger(__name__)

COMPLETED = "completed"
IN_PROGRESS = "in_progress"
FAILED = "failed"


class ProgressTracker:
    """Tracks which search units have been completed.

    Keys are ``SearchUnit.key`` strings, so city / sub-area / grid-tile runs
    all resume independently of each other.
    """

    def __init__(self, paths: OutputPaths | None = None):
        self.paths = paths or default_paths()
        self._progress: dict[str, str] = {}
        self._load()

    def _load(self):
        data = read_json(self.paths.progress_file, {})
        if isinstance(data, dict):
            self._progress = data
            completed = sum(1 for v in self._progress.values() if v == COMPLETED)
            if self._progress:
                logger.info(
                    f"Loaded progress: {completed} completed, "
                    f"{len(self._progress) - completed} unfinished."
                )

    def save(self):
        write_json_atomic(self.paths.progress_file, self._progress)

    def status(self, key: str) -> str | None:
        return self._progress.get(key)

    def is_completed(self, key: str) -> bool:
        return self._progress.get(key) == COMPLETED

    def _mark(self, key: str, status: str, flush: bool):
        self._progress[key] = status
        if flush:
            self.save()

    def mark_in_progress(self, key: str):
        # Not flushed: an in-progress marker adds nothing on resume that the
        # checkpoint file does not already carry, and this used to cost a full
        # rewrite of progress.json on every unit.
        self._mark(key, IN_PROGRESS, flush=False)

    def mark_completed(self, key: str):
        self._mark(key, COMPLETED, flush=True)

    def mark_failed(self, key: str):
        self._mark(key, FAILED, flush=True)

    def reset(self):
        """Forget all progress (used by --no-resume)."""
        self._progress = {}
        self.save()

    @property
    def stats(self) -> dict:
        values = list(self._progress.values())
        return {
            "completed": values.count(COMPLETED),
            "failed": values.count(FAILED),
            "in_progress": values.count(IN_PROGRESS),
            "total_tracked": len(values),
        }
