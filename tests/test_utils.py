import logging
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

import requests

from src.utils import RateLimiter, retry_with_backoff, setup_logger


class TestUtils(unittest.TestCase):
    def test_rate_limiter_first_call(self):
        limiter = RateLimiter(min_interval=0.1)
        slept = limiter.wait()
        self.assertEqual(slept, 0.0)

    def test_rate_limiter_second_call_sleeps(self):
        limiter = RateLimiter(min_interval=0.1)
        limiter.wait()
        start = time.monotonic()
        slept = limiter.wait()
        elapsed = time.monotonic() - start
        self.assertGreaterEqual(slept, 0.05)
        self.assertGreaterEqual(elapsed, 0.08)

    def test_retry_success_first_try(self):
        mock_func = MagicMock(return_value="OK")
        decorated = retry_with_backoff(max_retries=3, initial_delay=0.01)(mock_func)
        result = decorated()
        self.assertEqual(result, "OK")
        self.assertEqual(mock_func.call_count, 1)

    def test_retry_recovers_after_retryable_error(self):
        err_response = MagicMock()
        err_response.status_code = 429
        http_err = requests.HTTPError(response=err_response)

        mock_func = MagicMock(side_effect=[http_err, "Success"])
        decorated = retry_with_backoff(
            max_retries=3, initial_delay=0.01, backoff_factor=1.5
        )(mock_func)

        result = decorated()
        self.assertEqual(result, "Success")
        self.assertEqual(mock_func.call_count, 2)

    def test_retry_exhausts_and_raises(self):
        err_response = MagicMock()
        err_response.status_code = 503
        http_err = requests.HTTPError(response=err_response)

        mock_func = MagicMock(side_effect=http_err)
        decorated = retry_with_backoff(max_retries=3, initial_delay=0.01)(mock_func)

        with self.assertRaises(requests.HTTPError):
            decorated()
        self.assertEqual(mock_func.call_count, 3)

    def test_retry_non_retryable_raises_immediately(self):
        err_response = MagicMock()
        err_response.status_code = 404
        http_err = requests.HTTPError(response=err_response)

        mock_func = MagicMock(side_effect=http_err)
        decorated = retry_with_backoff(max_retries=4, initial_delay=0.01)(mock_func)

        with self.assertRaises(requests.HTTPError):
            decorated()
        self.assertEqual(mock_func.call_count, 1)

    def test_setup_logger(self):
        with TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            log_path = Path(tmp_dir) / "test.log"
            logger = setup_logger("test_custom_logger", log_file=log_path, level=logging.DEBUG)
            logger.info("Hello world log test")

            self.assertTrue(log_path.exists())
            with open(log_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("Hello world log test", content)


if __name__ == "__main__":
    unittest.main()
