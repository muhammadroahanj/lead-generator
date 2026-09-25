"""Retry-with-backoff for flaky page operations.

There was previously no retry anywhere in the scraper: a single transient
network blip on ``page.goto`` failed an entire search.
"""

import asyncio
import logging
import random
from typing import Awaitable, Callable, TypeVar

from config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryExhausted(Exception):
    """Raised when every attempt failed. Carries the last underlying error."""

    def __init__(self, description: str, attempts: int, last_error: Exception):
        super().__init__(f"{description} failed after {attempts} attempts: {last_error}")
        self.description = description
        self.attempts = attempts
        self.last_error = last_error


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    description: str = "operation",
    attempts: int | None = None,
    base_delay: float | None = None,
    factor: float | None = None,
    on_retry: Callable[[int, Exception], None] | None = None,
) -> T:
    """Run ``operation``, retrying with exponential backoff and jitter.

    Raises ``RetryExhausted`` when all attempts fail.
    """
    attempts = attempts if attempts is not None else settings.RETRY_ATTEMPTS
    base_delay = base_delay if base_delay is not None else settings.RETRY_BASE_DELAY
    factor = factor if factor is not None else settings.RETRY_FACTOR
    attempts = max(1, attempts)

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except asyncio.CancelledError:
            raise  # Never swallow cancellation — Ctrl-C must propagate.
        except Exception as exc:
            last_error = exc
            if attempt >= attempts:
                break
            delay = base_delay * (factor ** (attempt - 1))
            delay += random.uniform(0, delay * 0.25)  # jitter
            logger.warning(
                f"{description} failed (attempt {attempt}/{attempts}): {exc}. "
                f"Retrying in {delay:.1f}s"
            )
            if on_retry:
                on_retry(attempt, exc)
            await asyncio.sleep(delay)

    raise RetryExhausted(description, attempts, last_error or Exception("unknown"))
