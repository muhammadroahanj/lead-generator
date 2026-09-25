"""Crash-safe JSON persistence.

A plain ``open(path, "w")`` truncates the file before writing it. If the
process dies in between — SIGKILL, OOM, power loss, ``docker stop`` — the file
is left empty or half-written and the run's state is gone. Writing to a
temporary file in the same directory and then ``os.replace``-ing it is atomic
on both POSIX and Windows.
"""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def write_json_atomic(path: Path, payload: Any) -> None:
    """Serialize ``payload`` to ``path`` atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        # Never leave the temp file behind on failure.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def read_json(path: Path, default: Any) -> Any:
    """Read JSON, returning ``default`` when missing or corrupt."""
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(f"Could not read {path.name} ({exc}); starting fresh.")
        return default
