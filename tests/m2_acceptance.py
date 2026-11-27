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

    def test_distinct_sources_with_same_sora_title_keep_both_keys(self):
        version = self.version(1, r"Two systems are described in \cite{openai2024sora,opensora}.\bibliography{references}")
        (version / "references.bib").write_text(
            r"""@misc{openai2024sora,
  title={{Sora: Creating video from text}}, author={OpenAI}, year={2024},
  howpublished={\url{https://openai.com/sora}}
}
@misc{opensora,
  title={{Sora: Creating video from text}}, author={Zangwei Zheng and Xiangyu Peng}, year={2024},
  howpublished={\url{https://github.com/hpcaitech/Open-Sora}}
}
""",
            encoding="utf-8",
        )

        result = process_single_paper(str(self.paper))
        entries = {row["citation_key"]: row["authors"] for row in result["bibtex"]}
        self.assertEqual(entries, {"openai2024sora": ["OpenAI"], "opensora": ["Zangwei Zheng", "Xiangyu Peng"]})
        self.assertIn(r"\cite{openai2024sora,opensora}", " ".join(row[3] for row in result["elements"]))

    def test_distinct_cake_cutting_papers_keep_both_keys(self):
        version = self.version(1, r"\input{Introduction}\bibliography{ijcai25}")
        (version / "Introduction.tex").write_text(r"The early results are described in \cite{DS61,S80}.", encoding="utf-8")
        (version / "ijcai25.bib").write_text(
            """@article{DS61,
  title={How to cut a cake fairly}, author={Lester E. Dubins and Edwin H. Spanier}, year={1961}
}
@article{S80,
  title={How to cut a cake fairly}, author={Walter Stromquist}, year={1980}
}
""",
            encoding="utf-8",
        )

        result = process_single_paper(str(self.paper))
        years = {row["citation_key"]: row["year"] for row in result["bibtex"]}
        self.assertEqual(years, {"DS61": 1961, "S80": 1980})
        self.assertIn(r"\cite{DS61,S80}", " ".join(row[3] for row in result["elements"]))

    def test_declared_bibliography_emits_only_cited_entries(self):
        version = self.version(1, r"\input{content}")
        (version / "content.tex").write_text(
            r"The authors use data from \citep{koehn-2005-europarl,züfle2025nutshelldatasetabstractgeneration}."
            r"\bibliography{custom, anthology}",
            encoding="utf-8",
        )
        (version / "anthology.bib").write_text(
            """@inproceedings{koehn-2005-europarl, title={Europarl}, year={2005}}
@proceedings{wraicogs-ws-2025-1, title={Proceedings of an unrelated workshop}, year={2025}}
""",
            encoding="utf-8",
        )
        (version / "custom.bib").write_text(
            "@misc{züfle2025nutshelldatasetabstractgeneration, title={NUTSHELL}, year={2025}}",
            encoding="utf-8",
        )

        result = process_single_paper(str(self.paper))
        keys = {row["citation_key"] for row in result["bibtex"]}
        self.assertEqual(keys, {"koehn-2005-europarl", "züfle2025nutshelldatasetabstractgeneration"})
        self.assertIn(
            r"\citep{koehn-2005-europarl,züfle2025nutshelldatasetabstractgeneration}",
            " ".join(row[3] for row in result["elements"]),
        )

    def test_nocite_wildcard_keeps_declared_resources_and_inline_items(self):
        version = self.version(1, r"\nocite{*}")
        (version / "main.tex").write_text(
            r"""\documentclass{article}
\addbibresource[location=local]{refs.bib}
% \addbibresource{sample.bib}
\begin{document}
This paper lists all its references.
\nocite{*}
\begin{thebibliography}{9}
\bibitem{inline} Alice Smith. An inline reference. 2020.
\end{thebibliography}
\end{document}
""", encoding="utf-8",
        )
        (version / "refs.bib").write_text(
            '@article{listed, title={Declared entry}}\n% @article{commented, title={Ignored entry}}',
            encoding="utf-8",
        )
        (version / "sample.bib").write_text('@article{outside, title={Unrelated entry}}', encoding="utf-8")

        result = process_single_paper(str(self.paper))
        self.assertEqual({row["citation_key"] for row in result["bibtex"]}, {"listed", "inline"})

    def test_generated_bibliography_preserves_entries_and_reports_missing_keys(self):
        version = self.version(
            1, r"The authors refer to \parencite [see] [p. 2] {known,missing}.\bibliography{absent}\input{lost.bbl}",
        )
        (version / "main.bbl").write_text(
            r"\begin{thebibliography}{9}\bibitem{known} Alice Smith. The known article. 2020.\end{thebibliography}",
            encoding="utf-8",
        )

        result = process_single_paper(str(self.paper))
        self.assertEqual([row["citation_key"] for row in result["bibtex"]], ["known"])
        issues = {item["kind"]: item for item in result["bibtex_issues"]}
        self.assertEqual(issues["missing_bib_resources"]["resources"], ["absent"])
        self.assertEqual(issues["missing_bbl_inputs"]["resources"], ["lost.bbl"])
        self.assertEqual(issues["unresolved_citation_keys"]["keys"], ["missing"])

    def test_reused_key_for_different_works_is_renamed_by_version(self):
        first = self.version(1, r"We cite the first work \cite{shared}.\bibliography{refs}")
        second = self.version(2, r"We cite the second work \cite{shared,shared__v2}.\bibliography{refs}")
        (first / "refs.bib").write_text('@article{shared,title={The first work},doi={10.1234/first}}', encoding="utf-8")
        (second / "refs.bib").write_text(
            '@article{shared,title={The second work},doi={10.1234/second}}\n'
            '@article{shared__v2,title={The third work}}',
            encoding="utf-8",
        )

        result = process_single_paper(str(self.paper))
        key_map = result["citation_key_map"]
        self.assertEqual(key_map[(1, "shared")], "shared")
        self.assertEqual(key_map[(2, "shared")], "shared__v2_2")
        self.assertEqual(key_map[(2, "shared__v2")], "shared__v2")
        self.assertIn(r"\cite{shared__v2_2,shared__v2}", " ".join(row[3] for row in result["elements"]))

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
