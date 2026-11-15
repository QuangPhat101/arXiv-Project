"""Offline notebook checks: definition cells only, no Colab/network/live runner.

Queue operations run against temporary local state. A separate GitJournal test
uses a local bare repository to exercise a real non-fast-forward retry.
"""
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks/benchmark_20k_colab.ipynb"


def definitions():
    nb = json.loads(NOTEBOOK.read_text())
    scope = {}
    for i in (2, 3, 4, 5):
        source = "".join(nb["cells"][i]["source"])
        exec(compile(source, f"benchmark-cell-{i}", "exec"), scope)
    compile(scope["CHILD_SOURCE"], "benchmark-child", "exec")
    return scope


class LocalJournal:
    def __init__(self, path, base):
        self.path, self.base = path, base

    def update(self, message, edit):
        value, changes = edit(self.path)
        for name, data in changes.items():
            target = self.path / self.base / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return value


class BenchmarkNotebookTest(unittest.TestCase):
    def setUp(self):
        self.s = definitions()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.journal = LocalJournal(self.root, self.s["BASE"])
        self.groups = {f"2506.{i:05d}": [f"2506.{i:05d}"] for i in range(1, 7)}
        contract = {"csv_ranges": {"sample": ["2506.00001", "2506.00006", 6]}}
        self.s["bootstrap"](self.journal, self.groups, contract, b"test\n")

    def test_compile_all_cells_without_execution(self):
        nb = json.loads(NOTEBOOK.read_text())
        for i, cell in enumerate(nb["cells"]):
            if cell["cell_type"] == "code":
                compile("".join(cell["source"]), f"cell-{i}", "exec")
        self.assertEqual(self.s["CODE_SHA"], "c87f35aca9495f7e3aa4261340d5f10778b692ea")

    def test_four_runtime_limit_and_expired_lease_recovery(self):
        jobs = [self.s["claim"](self.journal, self.groups, str(i), now_fn=lambda: 100) for i in range(4)]
        self.assertEqual(len({job[1] for job in jobs}), 4)
        self.assertEqual(self.s["claim"](self.journal, self.groups, "fifth", now_fn=lambda: 101)[0], "wait")
        new = self.s["claim"](self.journal, self.groups, "restart", now_fn=lambda: 500)
        self.assertEqual(new[1], jobs[0][1])
        with self.assertRaises(self.s["LeaseLost"]):
            self.s["touch"](self.journal, jobs[0][1], jobs[0][2], {}, now_fn=lambda: 501)

    def test_checkpoint_release_and_idempotent_commit(self):
        claim = self.s["claim"]
        job = claim(self.journal, self.groups, "s", now_fn=lambda: 100)
        _, block, token, ids = job
        self.s["touch"](self.journal, block, token, {"evidence.txt": b"checkpoint"}, release=True, now_fn=lambda: 110)
        job = claim(self.journal, self.groups, "resume", now_fn=lambda: 120)
        _, block, token, ids = job
        rows = {aid: dict(outcome="SUCCESS", raw_bytes=10, extracted_bytes=5, disk_bytes=5) for aid in ids}
        receipt = dict(drive_id="fake", sha256="fake")
        commit = self.s["commit_pass"]
        with self.assertRaisesRegex(ValueError, "biên nhận"):
            commit(self.journal, self.groups, block, token, rows, {}, {}, now_fn=lambda: 125)
        commit(self.journal, self.groups, block, token, rows, {}, receipt, now_fn=lambda: 130)
        commit(self.journal, self.groups, block, token, rows, {}, receipt, now_fn=lambda: 140)
        state = self.s["get_state"](self.root, block)
        self.assertEqual(state["passes"][ids[0]], 1)
        self.assertIsNotNone(state["done_at"])
        progress = self.s["latest_progress"](self.root, self.groups)
        self.assertEqual(progress["evaluated_distinct"], 1)

    def test_discovery_slot_excludes_other_runtime(self):
        a = self.s["claim"](self.journal, self.groups, "a", now_fn=lambda: 100)
        b = self.s["claim"](self.journal, self.groups, "b", now_fn=lambda: 100)
        slot = self.s["api_slot"]
        self.assertTrue(slot(self.journal, a[1], a[2], now_fn=lambda: 101)[0])
        self.assertFalse(slot(self.journal, b[1], b[2], now_fn=lambda: 102)[0])
        self.s["free_slot"](self.journal, a[2], now_fn=lambda: 103)
        self.assertFalse(slot(self.journal, b[1], b[2], now_fn=lambda: 105)[0])
        self.assertTrue(slot(self.journal, b[1], b[2], now_fn=lambda: 108)[0])

    def test_success_record_with_missing_metadata_is_incomplete(self):
        stats = dict(testbed={}, run_summary={"evaluated_papers": 1}, memory={"sample_count": 1},
                     storage={}, phase_breakdown_s={}, failed_papers=[],
                     paper_records=[dict(arxiv_id="2506.00001", status="SUCCESS", raw_bytes=1, extracted_bytes=1)])
        rows = self.s["measured_rows"](stats, ["2506.00001"], self.root)
        self.assertEqual(rows["2506.00001"]["outcome"], "INCOMPLETE")

    def test_all_20000_ids_and_800_blocks_from_report(self):
        report = ROOT.parent / "arXiv-Report"
        if not report.is_dir():
            self.skipTest("Sibling report repository needed for actual manifest audit")
        groups, contract, manifest = self.s["read_manifest"](report)
        self.assertEqual(len(groups), 800)
        self.assertEqual(sum(map(len, groups.values())), 20000)
        self.assertEqual(len(set(manifest.decode().splitlines())), 20000)
        self.assertEqual(contract["id_list_sha256"], hashlib.sha256(manifest).hexdigest())

    def test_git_compare_and_swap_recomputes_after_competing_commit(self):
        def git(*args):
            return subprocess.check_output(["git", *map(str, args)], stderr=subprocess.DEVNULL, text=True).strip()
        bare, seed = self.root / "remote.git", self.root / "seed"
        git("init", "--bare", bare)
        git("init", seed)
        git("-C", seed, "config", "user.email", "test@example.invalid")
        git("-C", seed, "config", "user.name", "Test")
        git("-C", seed, "commit", "--allow-empty", "-m", "seed")
        git("-C", seed, "push", bare, "HEAD:refs/heads/main")
        base = git("-C", seed, "rev-parse", "HEAD")
        cls = self.s["GitJournal"]
        a, b = cls(self.root/"a", bare, "results", base), cls(self.root/"b", bare, "results", base)
        calls = []
        def competing_edit(repo):
            calls.append(True)
            if len(calls) == 1:
                b.update("other worker", lambda _: (None, {"b.txt": b"other"}))
            return None, {"a.txt": b"mine"}
        with patch("time.sleep"):
            a.update("worker a", competing_edit)
        a.refresh()
        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual((a.path/self.s["BASE"]/"a.txt").read_bytes(), b"mine")
        self.assertEqual((a.path/self.s["BASE"]/"b.txt").read_bytes(), b"other")


if __name__ == "__main__":
    unittest.main()
