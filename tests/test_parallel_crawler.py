import json
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from src.crawler import (
    ExtractionResult,
    parse_arguments,
    run_parallel_pipeline,
    run_pipeline,
)
from src.utils import RateLimiter


class TestParallelCrawler(unittest.TestCase):
    def test_cli_parsing_arxiv_id_format(self):
        """Verify full arXiv IDs (e.g. 2506.05788) are parsed properly without requiring --month."""
        argv = [
            "--start", "2506.05788",
            "--end", "2506.05837",
            "--output-dir", "custom/data",
            "--stats-file", "stats.json",
            "--n-workers", "3",
        ]
        args = parse_arguments(argv)
        self.assertEqual(args.start, "2506.05788")
        self.assertEqual(args.end, "2506.05837")
        self.assertEqual(args.output, Path("custom/data"))
        self.assertEqual(args.profile_output, Path("stats.json"))
        self.assertEqual(args.n_workers, 3)

    def test_cli_parsing_parallel_flag(self):
        """Verify --parallel flag enables parallel mode."""
        argv = ["--start", "1000", "--end", "1010", "--month", "2505", "--parallel"]
        args = parse_arguments(argv)
        self.assertTrue(args.parallel)

    def test_rate_limiter_thread_safety(self):
        """Verify RateLimiter coordinates spacing across multiple concurrent threads."""
        limiter = RateLimiter(min_interval=0.05)
        call_times = []
        lock = threading.Lock()

        def worker():
            for _ in range(3):
                limiter.wait()
                with lock:
                    call_times.append(time.monotonic())

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(call_times), 9)
        call_times.sort()
        # Ensure consecutive requests across all threads are spaced by at least ~0.04s
        for i in range(1, len(call_times)):
            gap = call_times[i] - call_times[i - 1]
            self.assertGreaterEqual(gap, 0.035, f"Requests {i-1} and {i} were only {gap:.4f}s apart")

    def test_parallel_pipeline_end_to_end_mocked(self):
        """Verify run_parallel_pipeline executes 3-stage pipeline and outputs summary."""
        with TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir) / "output"
            stats_file = Path(tmp_dir) / "stats.json"
            target_ids = ["2506.00001", "2506.00002", "2506.00003"]

            mock_meta = {
                "arxiv_id": "mock",
                "title": "Mock Title",
                "authors": ["Author"],
                "versions": ["mockv1"],
            }

            def fake_discover(aid, output_dir=None):
                return {
                    "arxiv_id": aid,
                    "title": f"Title {aid}",
                    "authors": ["A"],
                    "versions": [f"{aid}v1"],
                }

            def fake_download(versioned_id, dest_path, session=None, timeout=60.0):
                p = Path(dest_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"dummy archive content")
                return p

            def fake_extract(archive_path, target_dir):
                target_dir.mkdir(parents=True, exist_ok=True)
                (target_dir / "paper.tex").write_text("\\documentclass{article}", encoding="utf-8")
                return ExtractionResult.SUCCESS

            def fake_refs(arxiv_id, output_dir=None, api_key=None, session=None):
                p_dir = out_dir / arxiv_id
                p_dir.mkdir(parents=True, exist_ok=True)
                (p_dir / "references.json").write_text("[]", encoding="utf-8")
                return []

            with patch("src.crawler.discover_paper", side_effect=fake_discover), \
                 patch("src.crawler.download_source", side_effect=fake_download), \
                 patch("src.crawler.extract_tex_bib", side_effect=fake_extract), \
                 patch("src.crawler.get_references", side_effect=fake_refs):

                summary = run_parallel_pipeline(
                    arxiv_ids=target_ids,
                    output_dir=out_dir,
                    resume=True,
                    profile=True,
                    profile_output=stats_file,
                    n_workers=2,
                    download_workers=2,
                    s2_workers=2,
                )

            self.assertEqual(summary["total_targets"], 3)
            self.assertEqual(summary["succeeded"], 3)
            self.assertEqual(summary["failed"], 0)

            # Check checkpoint file
            chk_file = out_dir / "checkpoint.txt"
            self.assertTrue(chk_file.exists())
            completed = chk_file.read_text().splitlines()
            self.assertEqual(set(completed), set(target_ids))

            # Check profile stats JSON
            self.assertTrue(stats_file.exists())
            with open(stats_file) as f:
                stats = json.load(f)
            self.assertEqual(stats["run_summary"]["evaluated_papers"], 3)
            self.assertEqual(stats["run_summary"]["success_count"], 3)
            self.assertEqual(stats["run_summary"]["n_workers"], 2)

    def test_parallel_pipeline_error_isolation(self):
        """Verify that when 1 paper fails download, other papers still complete successfully."""
        with TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir) / "output"
            target_ids = ["2506.00010", "2506.00011", "2506.00012"]

            def fake_discover(aid, output_dir=None):
                return {"arxiv_id": aid, "versions": [f"{aid}v1"]}

            def fake_download(versioned_id, dest_path, session=None, timeout=60.0):
                if "2506.00011" in versioned_id:
                    raise RuntimeError("Simulated network drop")
                p = Path(dest_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"content")
                return p

            def fake_extract(archive_path, target_dir):
                target_dir.mkdir(parents=True, exist_ok=True)
                (target_dir / "main.tex").write_text("% latex", encoding="utf-8")
                return ExtractionResult.SUCCESS

            def fake_refs(arxiv_id, output_dir=None, api_key=None, session=None):
                p_dir = out_dir / arxiv_id
                p_dir.mkdir(parents=True, exist_ok=True)
                (p_dir / "references.json").write_text("[]", encoding="utf-8")
                return []

            with patch("src.crawler.discover_paper", side_effect=fake_discover), \
                 patch("src.crawler.download_source", side_effect=fake_download), \
                 patch("src.crawler.extract_tex_bib", side_effect=fake_extract), \
                 patch("src.crawler.get_references", side_effect=fake_refs):

                summary = run_parallel_pipeline(
                    arxiv_ids=target_ids,
                    output_dir=out_dir,
                    resume=True,
                    n_workers=2,
                    download_workers=2,
                    s2_workers=2,
                )

            self.assertEqual(summary["total_targets"], 3)
            self.assertEqual(summary["succeeded"], 2)
            self.assertEqual(summary["failed"], 1)
            self.assertIn("2506.00011", summary["failed_papers"])

    def test_main_cli_execution_with_full_id_and_parallel(self):
        """Verify main() runs cleanly with full arXiv ID strings and --parallel."""
        from src.crawler import main

        with TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir) / "data"
            stats_file = Path(tmp_dir) / "stats.json"

            def fake_discover(aid, output_dir=None):
                return {"arxiv_id": aid, "versions": [f"{aid}v1"]}

            def fake_download(versioned_id, dest_path, session=None, timeout=60.0):
                p = Path(dest_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"content")
                return p

            def fake_extract(archive_path, target_dir):
                target_dir.mkdir(parents=True, exist_ok=True)
                (target_dir / "paper.tex").write_text("% latex", encoding="utf-8")
                return ExtractionResult.SUCCESS

            def fake_refs(arxiv_id, output_dir=None, api_key=None, session=None):
                p_dir = out_dir / arxiv_id
                p_dir.mkdir(parents=True, exist_ok=True)
                (p_dir / "references.json").write_text("[]", encoding="utf-8")
                return []

            cli_args = [
                "--start", "2506.00001",
                "--end", "2506.00002",
                "--output-dir", str(out_dir),
                "--stats-file", str(stats_file),
                "--parallel",
            ]

            with patch("src.crawler.discover_paper", side_effect=fake_discover), \
                 patch("src.crawler.download_source", side_effect=fake_download), \
                 patch("src.crawler.extract_tex_bib", side_effect=fake_extract), \
                 patch("src.crawler.get_references", side_effect=fake_refs):
                ret_code = main(cli_args)

            self.assertEqual(ret_code, 0)
            self.assertTrue(stats_file.exists())
            with open(stats_file) as f:
                stats = json.load(f)
            self.assertEqual(stats["run_summary"]["evaluated_papers"], 2)
            self.assertEqual(stats["run_summary"]["success_count"], 2)
            self.assertEqual(stats["run_summary"]["n_workers"], 3)


if __name__ == "__main__":
    unittest.main()
