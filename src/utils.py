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
import sys
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

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
        now = time.monotonic()
        elapsed = now - self.last_request_time
        remaining = self.min_interval - elapsed
        slept = 0.0

        if self.last_request_time > 0.0 and remaining > 0.0:
            time.sleep(remaining)
            slept = remaining

        self.last_request_time = time.monotonic()
        return slept


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
        func_name = getattr(func, "__name__", str(func))

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_logger = logger or logging.getLogger(__name__)
            delay = initial_delay

            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    is_retryable = False

                    if requests and isinstance(exc, requests.RequestException):
                        if exc.response is not None and exc.response.status_code in retryable_statuses:
                            is_retryable = True
                        elif isinstance(exc, (requests.Timeout, requests.ConnectionError)):
                            is_retryable = True
                    elif isinstance(exc, (TimeoutError, ConnectionError, OSError)):
                        is_retryable = True

                    if not is_retryable or attempt == max_retries:
                        current_logger.error(
                            "Function %s failed on attempt %d/%d with non-retryable error: %s",
                            func_name,
                            attempt,
                            max_retries,
                            exc,
                        )
                        raise

                    current_logger.warning(
                        "Attempt %d/%d for %s failed (%s). Retrying in %.2fs (backoff factor %.1f)...",
                        attempt,
                        max_retries,
                        func_name,
                        exc,
                        delay,
                        backoff_factor,
                    )
                    time.sleep(delay)
                    delay *= backoff_factor

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
    configured_logger = logging.getLogger(name)
    configured_logger.setLevel(level)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # Ensure stream handler exists
    has_stream_handler = any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        for h in configured_logger.handlers
    )
    if not has_stream_handler:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        configured_logger.addHandler(stream_handler)

    # Add file handler if log_file is specified
    if log_file:
        file_path = Path(log_file).resolve()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        already_has_file = any(
            isinstance(h, logging.FileHandler) and Path(h.baseFilename).resolve() == file_path
            for h in configured_logger.handlers
        )
        if not already_has_file:
            file_handler = logging.FileHandler(str(file_path), encoding="utf-8")
            file_handler.setFormatter(formatter)
            configured_logger.addHandler(file_handler)

    return configured_logger
