"""Requirement checks handed to Khanh/Bao; known failures are NOT expectedFailure.

Run explicitly: python -m unittest discover -s tests -p m2_acceptance.py -v
These expose the M2 integration blockers separately from the existing test suite.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.parser import parse_version
from src.run_m2_pipeline import process_single_paper


class M2Acceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.paper = Path(self.temp.name) / "2506.00001"
        self.paper.mkdir()
        (self.paper / "metadata.json").write_text(json.dumps({"arxiv_id": self.paper.name, "title": "Test"}))
        (self.paper / "references.json").write_text("[]")

    def version(self, n, body):
        v = self.paper / f"v{n}"
        v.mkdir()
        (v / "main.tex").write_text("\\documentclass{article}\n\\begin{document}\n" + body + "\n\\end{document}")
        return v

    def test_bibliography_excluded_acknowledgments_kept(self):
        v = self.version(1, r"""\section*{Acknowledgments}
We thank our colleagues.
\begin{thebibliography}{9}\bibitem{x} Alice Smith. A forbidden reference sentence here.\end{thebibliography}""")
        el, _ = parse_version(v, self.paper.name, 1)
        content = " ".join(e[3] for e in el)
        self.assertIn("We thank our colleagues", content)
        self.assertNotIn("forbidden reference", content)

    def test_itemize_has_item_nodes_and_sentence_children(self):
        v = self.version(1, r"\begin{itemize}\item This is the first item.\item This is the second item.\end{itemize}")
        el, hi = parse_version(v, self.paper.name, 1)
        items = {e[0] for e in el if e[2] == "item"}
        self.assertEqual(len(items), 2)
        sentences = {e[0] for e in el if e[2] == "sentence"}
        self.assertEqual(sum(e in sentences and parent in items for _, _, e, parent in hi), 2)

    def test_math_and_formatting_normalized_before_dedup(self):
        v1 = self.version(1, r"This is a \textbf{simple} result. \[x=y\]")
        v2 = self.version(2, r"This is a simple result. \begin{equation}x=y\end{equation}")
        a, _ = parse_version(v1, self.paper.name, 1)
        b, _ = parse_version(v2, self.paper.name, 2)
        self.assertEqual({e[0] for e in a if e[2] == "sentence"}, {e[0] for e in b if e[2] == "sentence"})
        self.assertEqual(len([e for e in a if e[2] == "equation"]), 1)
        self.assertEqual({e[0] for e in a if e[2] == "equation"}, {e[0] for e in b if e[2] == "equation"})

    def bib_versions(self):
        v1 = self.version(1, r"We cite the original work \cite{old}.")
        v2 = self.version(2, r"We cite the original work \cite{new}.")
        (v1 / "refs.bib").write_text('@article{old, title={A shared reference title}, author={Alice Smith}, year={2020}}')
        (v2 / "refs.bib").write_text('@article{new, title={A shared reference title}, author={Alice Smith}, doi={10.1234/example}}')

    def test_duplicate_bibtex_unions_fields(self):
        self.bib_versions()
        rows = process_single_paper(str(self.paper))["bibtex"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["year"], 2020)
        self.assertEqual(rows[0]["doi"], "10.1234/example")

    def test_citations_rewritten_to_canonical_key(self):
        self.bib_versions()
        result = process_single_paper(str(self.paper))
        canonical = result["bibtex"][0]["citation_key"]
        contents = " ".join(e[3] for e in result["elements"])
        self.assertNotIn(r"\cite{new}" if canonical == "old" else r"\cite{old}", contents)
        self.assertIn("\\cite{" + canonical + "}", contents)

    def test_parse_errors_are_observable(self):
        self.version(1, "This is a test.")
        with patch("src.run_m2_pipeline.parse_version", side_effect=ValueError("broken parser")):
            result = process_single_paper(str(self.paper))
        self.assertTrue(result.get("errors"), "Return structured errors (arxiv_id, version, stage, message), not silent pass")

    def test_empty_version_has_coverage_record(self):
        (self.paper / "v1").mkdir()
        result = process_single_paper(str(self.paper))
        self.assertTrue(result.get("coverage"), "Record PDF-only/empty versions separately from parse failures")


if __name__ == "__main__":
    unittest.main()
