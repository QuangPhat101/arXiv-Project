import gzip
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src import crawler

ARXIV_ID = "2503.01914"
META = {ARXIV_ID: {"arxiv_id": ARXIV_ID, "title": "t", "authors": [], "submission_date": None,
                   "revised_dates": [], "venue": None, "versions": [f"{ARXIV_ID}v1"]}}


def fake_discover_batch(ids, output_dir):
    # The real batch discovery also writes metadata.json for each paper.
    for aid in ids:
        (Path(output_dir) / aid).mkdir(parents=True, exist_ok=True)
        (Path(output_dir) / aid / "metadata.json").write_text(json.dumps(META[aid]))
    return META


def fake_download(versioned_id, dest_path, session=None):
    Path(dest_path).write_bytes(gzip.compress(b"\\documentclass{article}"))
    return Path(dest_path)


def fake_get_references(arxiv_id, output_dir, api_key=None, session=None):
    (Path(output_dir) / arxiv_id / "references.json").write_text(json.dumps([{"ref_arxiv_id": "x"}]))
    return []


class TestSkipReferences(unittest.TestCase):
    def test_sources_first_then_references_only(self):
        with TemporaryDirectory() as tmp, \
                patch.object(crawler, "discover_papers_batch", side_effect=fake_discover_batch), \
                patch.object(crawler, "download_source", side_effect=fake_download) as dl, \
                patch.object(crawler, "get_references", side_effect=fake_get_references) as refs:
            out = Path(tmp)

            # Pass 1: sources only. No S2 call, paper stays out of the checkpoint.
            s1 = crawler.run_pipeline([ARXIV_ID], out, skip_references=True)
            self.assertEqual((s1["succeeded"], s1["failed"]), (1, 0))
            refs.assert_not_called()
            self.assertTrue((out / ARXIV_ID / "v1" / "main.tex").is_file())
            self.assertFalse((out / ARXIV_ID / "references.json").exists())
            self.assertNotIn(ARXIV_ID, crawler.load_checkpoint(out / "checkpoint.txt"))

            # Pass 2: with references. Source is not downloaded again, paper gets checkpointed.
            s2 = crawler.run_pipeline([ARXIV_ID], out)
            self.assertEqual((s2["succeeded"], s2["failed"]), (1, 0))
            self.assertEqual(dl.call_count, 1)
            refs.assert_called_once()
            self.assertIn(ARXIV_ID, crawler.load_checkpoint(out / "checkpoint.txt"))


if __name__ == "__main__":
    unittest.main()
