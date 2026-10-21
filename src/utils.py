"""Utility Module: Rate Limiting, Retry Mechanisms, and Logging.

Assigned to: Khôi
Purpose:
    Provide centralized utilities for controlling network request frequency,
    handling transient network/rate-limiting errors with exponential backoff,
    and managing project-wide logging.

Requirements for Member1:
    1. Implement RateLimiter using monotonic clock (`time.monotonic()`) to avoid
       clock drift issues. Calculate elapsed time since previous request; only
       sleep for the remaining interval (`min_interval - elapsed`). If elapsed >= min_interval,
       return 0.0 immediately without sleeping.
    2. Ensure arXiv requests share ONE coordinated rate limiter (arxiv_rate_limiter = 3.0s),
       preventing 403 blocks across discovery and download calls.
    3. Implement retry_with_backoff decorator catching requests.RequestException,
       retrying on status codes (403, 429, 500, 502, 503, 504), applying exponential delay
       with backoff factor, and re-raising on final failure.
    4. Implement setup_logger() with timestamped format and optional file output.
"""

from __future__ import annotations

import logging
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


class RateLimiter:
    """Thread-safe time-window rate limiter using monotonic clock.

    Ensures that consecutive requests to a specific domain or service
    are separated by at least `min_interval` seconds. Computes elapsed time
    since the previous request to avoid redundant sleeping.

    Attributes:
        min_interval (float): Minimum seconds between two consecutive requests.
        last_request_time (float): Monotonic timestamp of the last processed request.
    """

    def __init__(self, min_interval: float) -> None:
        """Initialize the RateLimiter.

        Args:
            min_interval: Minimum time interval in seconds between requests.
        """
        self.min_interval = min_interval
        self.last_request_time: float = 0.0

    def wait(self) -> float:
        """Wait if necessary to satisfy the minimum interval requirement.

        Calculates elapsed time since `last_request_time` using `time.monotonic()`.
        If elapsed < min_interval, sleeps for `(min_interval - elapsed)`.
        Updates `last_request_time` to current monotonic time.

        Returns:
            float: Number of seconds slept (0.0 if no sleep was needed).
        """
        # TODO (Khôi - Member1):
        # 1. now = time.monotonic()
        # 2. elapsed = now - self.last_request_time
        # 3. remaining = self.min_interval - elapsed
        # 4. if remaining > 0: time.sleep(remaining); slept = remaining
        # 5. else: slept = 0.0
        # 6. self.last_request_time = time.monotonic()
        # 7. return slept
        raise NotImplementedError("RateLimiter.wait() is not yet implemented.")


# Pre-configured instances for arXiv and Semantic Scholar
# arXiv policy: max 1 request per 3 seconds
# Semantic Scholar policy: 1 request per second without an API key
arxiv_rate_limiter = RateLimiter(min_interval=3.0)
s2_rate_limiter = RateLimiter(min_interval=1.0)


def retry_with_backoff(
    max_retries: int = 5,
    initial_delay: float = 2.0,
    backoff_factor: float = 2.0,
    retryable_statuses: tuple[int, ...] = (403, 429, 500, 502, 503, 504),
    logger: Optional[logging.Logger] = None,
) -> Callable[[F], F]:
    """Decorator for exponential backoff retries on network and rate-limiting errors.

    Retries a function if it encounters specified HTTP errors (e.g., 429 Too Many
    Requests, 403 Forbidden, 5xx Server Errors) or network timeouts.

    Args:
        max_retries: Maximum number of retry attempts before giving up.
        initial_delay: Delay in seconds before the first retry.
        backoff_factor: Multiplier applied to the delay after each retry attempt.
        retryable_statuses: HTTP status codes that trigger a retry.
        logger: Optional logger instance to record retry events.

    Returns:
        Decorated callable with retry logic.
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # TODO (Khôi - Member1):
            # delay = initial_delay
            # for attempt in range(1, max_retries + 1):
            #     try:
            #         return func(*args, **kwargs)
            #     except Exception as exc:
            #         # check if retryable (RequestException with response.status_code in retryable_statuses)
            #         # if last attempt, re-raise exc
            #         # time.sleep(delay)
            #         # delay *= backoff_factor
            raise NotImplementedError("retry_with_backoff decorator is not yet implemented.")

        return wrapper  # type: ignore[return-value]

    return decorator


def setup_logger(
    name: str = "arxiv_crawler",
    log_file: Optional[Path | str] = None,
    level: int = logging.INFO,
) -> logging.Logger:
    """Configure and return a structured logger.

    Sets up a logger with console and optional file handlers using a standard
    timestamped format.

    Args:
        name: Name of the logger.
        log_file: Path to log file. If provided, logs are also written to file.
        level: Logging level (e.g., logging.INFO, logging.DEBUG).

    Returns:
        logging.Logger: Configured logger instance.
    """
    # TODO (Khôi - Member1):
    # Set up StreamHandler and optional FileHandler with Formatter:
    # "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    raise NotImplementedError("setup_logger() is not yet implemented.")
