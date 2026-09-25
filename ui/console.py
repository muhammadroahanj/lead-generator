"""Shared Rich console plus TTY detection.

The dashboard takes over the terminal, so it must never engage when stdout is
a pipe or a Docker log stream (``docker-compose.yml`` runs with
``stdin_open: false`` and no TTY).
"""

import sys

from rich.console import Console

console = Console()


def is_interactive() -> bool:
    """Whether we can safely run prompts and a live-updating display."""
    try:
        return bool(sys.stdin and sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False


def supports_live() -> bool:
    """Whether a live-updating dashboard will render usefully."""
    return bool(sys.stdout and sys.stdout.isatty()) and not console.is_dumb_terminal
