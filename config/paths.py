"""Output file locations for a run.

Bundled together so an alternate ``--output`` directory changes every artifact
consistently, instead of each module reaching for its own module-level constant.
"""

from dataclasses import dataclass
from pathlib import Path

from config import settings


@dataclass(frozen=True)
class OutputPaths:
    root: Path

    @property
    def progress_file(self) -> Path:
        return self.root / "progress.json"

    @property
    def seen_keys_file(self) -> Path:
        return self.root / "seen_keys.json"

    @property
    def checkpoint_dir(self) -> Path:
        return self.root / "checkpoints"

    @property
    def log_file(self) -> Path:
        return self.root / "scraper.log"

    @property
    def leads_raw_csv(self) -> Path:
        return self.root / "leads_raw.csv"

    @property
    def leads_qualified_csv(self) -> Path:
        return self.root / "leads_qualified.csv"

    @property
    def leads_xlsx(self) -> Path:
        return self.root / "leads.xlsx"

    def ensure(self) -> "OutputPaths":
        self.root.mkdir(parents=True, exist_ok=True)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        return self


def default_paths() -> OutputPaths:
    return OutputPaths(root=settings.OUTPUT_DIR)
