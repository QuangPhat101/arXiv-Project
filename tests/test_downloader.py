import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import requests

from src.downloader import download_source, get_source_url


class TestDownloader(unittest.TestCase):
    def test_get_source_url(self):
        url = get_source_url("2506.05788v1")
        self.assertEqual(url, "https://export.arxiv.org/src/2506.05788v1")

    def test_download_source_200_success(self):
        with TemporaryDirectory() as tmp_dir:
            dest = Path(tmp_dir) / "output" / "sample.tar.gz"

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.iter_content.return_value = [b"chunk1", b"chunk2"]

            mock_session = MagicMock()
            mock_session.get.return_value = mock_response

            with patch("src.downloader.arxiv_rate_limiter.wait"):
                result = download_source("2506.05788v1", dest, session=mock_session)

            self.assertEqual(result, dest)
            self.assertTrue(dest.exists())
            self.assertEqual(dest.read_bytes(), b"chunk1chunk2")
            mock_session.get.assert_called_once()

    def test_download_source_404_returns_none(self):
        with TemporaryDirectory() as tmp_dir:
            dest = Path(tmp_dir) / "output" / "sample.tar.gz"

            mock_response = MagicMock()
            mock_response.status_code = 404

            mock_session = MagicMock()
            mock_session.get.return_value = mock_response

            with patch("src.downloader.arxiv_rate_limiter.wait"):
                result = download_source("2506.99999v1", dest, session=mock_session)

            self.assertIsNone(result)
            self.assertFalse(dest.exists())

    def test_download_source_retryable_recovers(self):
        with TemporaryDirectory() as tmp_dir:
            dest = Path(tmp_dir) / "output" / "sample.tar.gz"

            err_resp = MagicMock()
            err_resp.status_code = 429
            http_err = requests.HTTPError(response=err_resp)

            success_resp = MagicMock()
            success_resp.status_code = 200
            success_resp.iter_content.return_value = [b"recovered_content"]

            mock_session = MagicMock()
            mock_session.get.side_effect = [http_err, success_resp]

            with patch("src.downloader.arxiv_rate_limiter.wait"), \
                 patch("time.sleep"):
                result = download_source("2506.05788v1", dest, session=mock_session)

            self.assertEqual(result, dest)
            self.assertEqual(dest.read_bytes(), b"recovered_content")
            self.assertEqual(mock_session.get.call_count, 2)

    def test_download_source_exhausts_and_raises(self):
        with TemporaryDirectory() as tmp_dir:
            dest = Path(tmp_dir) / "output" / "sample.tar.gz"

            err_resp = MagicMock()
            err_resp.status_code = 503
            http_err = requests.HTTPError(response=err_resp)

            mock_session = MagicMock()
            mock_session.get.side_effect = http_err

            with patch("src.downloader.arxiv_rate_limiter.wait"), \
                 patch("time.sleep"):
                with self.assertRaises(RuntimeError):
                    download_source("2506.05788v1", dest, session=mock_session)


if __name__ == "__main__":
    unittest.main()
