"""Offline notebook checks for milestone1_benchmark.ipynb.

Validates notebook structure, telemetry constants, compilation of all code cells,
absence of crawler/leakage code, and presence of pre-executed visualization outputs.
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks/milestone1_benchmark.ipynb"


def load_notebook():
    if not NOTEBOOK.exists():
        raise FileNotFoundError(f"Notebook not found: {NOTEBOOK}")
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


class BenchmarkNotebookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nb = load_notebook()
        cls.cells = cls.nb.get("cells", [])

    def test_notebook_exists_and_format(self):
        self.assertTrue(NOTEBOOK.is_file())
        self.assertEqual(self.nb.get("nbformat"), 4)

    def test_cell_count_and_sequence(self):
        self.assertEqual(len(self.cells), 13, "Notebook must have exactly 13 cells according to specification")
        expected_types = [
            "markdown",  # Cell 1: Title & Abstract
            "code",      # Cell 2: Import & Constants
            "markdown",  # Cell 3: Introduction
            "markdown",  # Cell 4: Traditional benchmark challenges
            "markdown",  # Cell 5: Distributed benchmark solution
            "markdown",  # Cell 6: Paper lifecycle pipeline
            "code",      # Cell 7: Figure 1 - Phase duration breakdown
            "code",      # Cell 8: Figure 2 - Partition outcomes
            "code",      # Cell 9: Figure 3 - Baseline vs Parallel vs 20k
            "code",      # Cell 10: Summary table
            "markdown",  # Cell 11: Bottleneck analysis
            "markdown",  # Cell 12: Future improvements
            "markdown",  # Cell 13: Conclusion
        ]
        actual_types = [c.get("cell_type") for c in self.cells]
        self.assertEqual(actual_types, expected_types)

    def test_compile_all_code_cells(self):
        for i, cell in enumerate(self.cells):
            if cell.get("cell_type") == "code":
                source = "".join(cell.get("source", []))
                compile(source, f"milestone1_benchmark_cell_{i+1}", "exec")

    def test_telemetry_constants(self):
        cell_2_source = "".join(self.cells[1].get("source", []))
        scope = {}
        exec(compile(cell_2_source, "constants", "exec"), scope)

        campaign = scope["CAMPAIGN"]
        self.assertEqual(campaign["total_papers"], 20000)
        self.assertAlmostEqual(campaign["calendar_span_h"], 70.12, places=2)
        self.assertAlmostEqual(campaign["machine_hours_total"], 49.19, places=2)
        self.assertAlmostEqual(campaign["per_paper_s"], 8.1657, places=4)
        self.assertAlmostEqual(campaign["peak_rss_mib"], 51.22, places=2)
        self.assertAlmostEqual(campaign["savings_pct"], 92.612, places=3)
        self.assertEqual(campaign["s2_429_count"], 22238)

        outcomes = scope["OUTCOMES"]
        self.assertEqual(outcomes["SUCCESS"], 18287)
        self.assertEqual(outcomes["PDF_ONLY"], 1711)
        self.assertEqual(outcomes["INCOMPLETE"], 2)
        self.assertEqual(outcomes["FAILED"], 0)

        partitions = scope["PARTITIONS"]
        self.assertEqual(len(partitions), 4)
        for name, p in partitions.items():
            self.assertEqual(p["success"] + p["pdf_only"] + p["incomplete"], 5000)

        baseline = scope["BASELINE"]
        self.assertEqual(baseline["n_papers"], 100)
        self.assertAlmostEqual(baseline["avg_per_paper_s"], 13.42, places=2)
        self.assertAlmostEqual(baseline["median_per_paper_s"], 6.98, places=2)

        parallel = scope["PARALLEL_100"]
        self.assertEqual(parallel["n_papers"], 100)
        self.assertAlmostEqual(parallel["avg_per_paper_s"], 5.69, places=2)
        self.assertAlmostEqual(parallel["speedup"], 2.36, places=2)

    def test_no_forbidden_patterns(self):
        for i, cell in enumerate(self.cells):
            source = "".join(cell.get("source", []))
            self.assertFalse(
                re.search(r"^\s*(from|import)\s+src\b", source, re.MULTILINE),
                f"Cell {i+1} imports from src/"
            )
            self.assertNotIn("/home/domi1712", source, f"Cell {i+1} has hardcoded absolute path")
            self.assertNotIn("/Users/", source, f"Cell {i+1} has hardcoded absolute path")

    def test_pre_executed_outputs_present(self):
        code_indices = [6, 7, 8, 9]  # Cells 7, 8, 9, 10
        for idx in code_indices:
            cell = self.cells[idx]
            outputs = cell.get("outputs", [])
            self.assertGreater(len(outputs), 0, f"Cell {idx+1} has no pre-executed output")
            for out in outputs:
                self.assertNotEqual(out.get("output_type"), "error", f"Cell {idx+1} has error output: {out}")

        # Cells 7, 8, 9 must contain image/png
        for idx in [6, 7, 8]:
            cell = self.cells[idx]
            has_png = any("image/png" in out.get("data", {}) for out in cell.get("outputs", []))
            self.assertTrue(has_png, f"Cell {idx+1} must contain image/png output")

        # Cell 10 must contain markdown/html table output
        cell_10 = self.cells[9]
        has_table = any(
            out.get("name") == "stdout" or "text/html" in out.get("data", {}) or "text/plain" in out.get("data", {})
            for out in cell_10.get("outputs", [])
        )
        self.assertTrue(has_table, "Cell 10 must contain table output")

    def test_sibling_report_sync(self):
        report_nb = ROOT.parent / "arXiv-Report/milestone1/performance.ipynb"
        if not report_nb.is_file():
            self.skipTest("arXiv-Report sibling repository not found")
        data = json.loads(report_nb.read_text(encoding="utf-8"))
        self.assertEqual(len(data.get("cells", [])), 13)
        for i in range(13):
            self.assertEqual(
                data["cells"][i]["cell_type"],
                self.cells[i]["cell_type"],
                f"Mismatch in cell {i+1} type between report and project notebooks"
            )
            self.assertEqual(
                "".join(data["cells"][i].get("source", [])),
                "".join(self.cells[i].get("source", [])),
                f"Mismatch in cell {i+1} source between report and project notebooks"
            )

    def test_chart_visual_layout_no_text_overlap(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        scope = {}
        exec(compile("".join(self.cells[1]["source"]), "constants", "exec"), scope)

        for idx in [6, 7, 8]:
            code = "".join(self.cells[idx]["source"])
            check_script = (
                "fig.canvas.draw()\n"
                "renderer = fig.canvas.get_renderer()\n"
                "texts = []\n"
                "for child in ax.get_children():\n"
                "    if hasattr(child, 'get_text') and child.get_text():\n"
                "        texts.append((child.get_text()[:25], child.get_window_extent(renderer)))\n"
                "for i in range(len(texts)):\n"
                "    for j in range(i + 1, len(texts)):\n"
                "        t1, b1 = texts[i]\n"
                "        t2, b2 = texts[j]\n"
                "        if (b1.x1 > b2.x0 and b1.x0 < b2.x1 and b1.y1 > b2.y0 and b1.y0 < b2.y1):\n"
                "            raise AssertionError(f'Text collision in chart cell {idx+1}: {t1!r} and {t2!r}')\n"
                "plt.close()\n"
            )
            exec(compile(code.replace("plt.show()", check_script), f"cell_{idx+1}", "exec"), scope)


if __name__ == "__main__":
    unittest.main()
