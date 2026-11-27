import unittest
import tempfile
import shutil
from pathlib import Path
from src.bibtex_parser import (
    clean_latex_markup,
    parse_bib_file,
    parse_tex_bibitem,
    parse_version_bibtex,
    build_cross_version_citation_map,
)


class TestBibtexParser(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_clean_latex_markup(self):
        raw = r"\emph{Attention} is \textbf{all} you \url{https://arxiv.org} need % comment"
        cleaned = clean_latex_markup(raw)
        self.assertEqual(cleaned, "Attention is all you need")

    def test_parse_bib_file(self):
        bib_content = """
        @String(PAMI = {IEEE TPAMI})
        @article{vaswani2017attention,
            title = {Attention Is All You Need},
            author = {Vaswani, Ashish and Shazeer, Noam and others},
            journal = PAMI,
            year = {2017},
            doi = {10.5555/3295222.3295349},
            url = {https://arxiv.org/abs/1706.03762}
        }
        """
        bib_file = self.test_dir / "refs.bib"
        bib_file.write_text(bib_content, encoding="utf-8")

        entries = parse_bib_file(bib_file, "1706.03762")
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["arxiv_id"], "1706.03762")
        self.assertEqual(e["citation_key"], "vaswani2017attention")
        self.assertEqual(e["entry_type"], "article")
        self.assertEqual(e["title"], "Attention Is All You Need")
        self.assertIn("Ashish Vaswani", e["authors"])
        self.assertIn("Noam Shazeer", e["authors"])
        self.assertEqual(e["year"], 2017)
        self.assertEqual(e["doi"], "10.5555/3295222.3295349")
        self.assertEqual(e["journal"], "IEEE TPAMI")

    def test_parse_tex_bibitem(self):
        tex_content = r"""
        \begin{document}
        Some text.
        \begin{thebibliography}{99}
        \bibitem{lecun1998gradient}
        Y.~LeCun, L.~Bottou, Y.~Bengio, and P.~Haffner.
        \emph{Gradient-based learning applied to document recognition}.
        Proceedings of the IEEE, 1998.
        \doi{10.1109/5.726791}
        \end{thebibliography}
        \end{document}
        """
        tex_file = self.test_dir / "paper.tex"
        tex_file.write_text(tex_content, encoding="utf-8")

        entries = parse_tex_bibitem(tex_file, "sample_paper")
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["citation_key"], "lecun1998gradient")
        self.assertEqual(e["year"], 1998)
        self.assertEqual(e["doi"], "10.1109/5.726791")
        self.assertIn("Gradient-based learning", e["title"])

    def test_bibitem_year_respects_the_arxiv_identifier_and_the_publication_year(self):
        tex = self.test_dir / "paper.tex"
        tex.write_text(
            r"""\begin{thebibliography}{9}
            \bibitem{preprint} S. Friedland. Tensor optimal transport. arXiv:2005.00945.
            \bibitem{published} A preprint. arXiv:1910.00152. JMLR 23 (2022).
            \bibitem{url} A preprint. \url{https://arxiv.org/abs/2409.03698v1}.
            \bibitem{doi} An article. \doi{10.1109/2020.123456}.
            \end{thebibliography}""",
            encoding="utf-8",
        )

        years = {entry["citation_key"]: entry["year"] for entry in parse_tex_bibitem(tex, "sample")}

        self.assertEqual(years, {"preprint": 2020, "published": 2022, "url": 2024, "doi": None})

    def test_cross_version_citation_map(self):
        v1_entries = [{
            "citation_key": "vaswani_orig",
            "title": "Attention Is All You Need",
            "authors": ["Ashish Vaswani"],
        }]
        v2_entries = [{
            "citation_key": "vaswani2017",
            "title": "Attention Is All You Need",
            "authors": ["Ashish Vaswani"],
        }]
        mapping = build_cross_version_citation_map({1: v1_entries, 2: v2_entries})
        self.assertEqual(mapping[(1, "vaswani_orig")], "vaswani_orig")
        self.assertEqual(mapping[(2, "vaswani2017")], "vaswani_orig")

    def test_arxiv_id_links_join_alternate_keys(self):
        original = {"citation_key": "one", "url": "https://arxiv.org/abs/1706.03762v1"}
        revision = {"citation_key": "two", "doi": "10.48550/ARXIV.1706.03762"}
        mapping = build_cross_version_citation_map({1: [original], 2: [revision]})
        self.assertEqual(mapping, {(1, "one"): "one", (2, "two"): "one"})

    def test_title_without_identifying_metadata_keeps_distinct_keys(self):
        entries = [
            {"citation_key": "first", "title": "A common title"},
            {"citation_key": "second", "title": "A common title"},
        ]
        self.assertEqual(
            build_cross_version_citation_map({1: entries}),
            {(1, "first"): "first", (1, "second"): "second"},
        )

    def test_published_reference_can_replace_preprint_under_same_key(self):
        original = {"citation_key": "ref", "title": "A research article", "authors": ["Alice Smith"],
                    "year": 2021, "url": "https://arxiv.org/abs/2110.02205"}
        published = {"citation_key": "ref", "title": "A research article", "authors": ["Alice Smith"],
                     "year": 2024, "doi": "10.1234/article"}
        mapping = build_cross_version_citation_map({1: [original], 2: [published]})
        self.assertEqual(mapping, {(1, "ref"): "ref", (2, "ref"): "ref"})

    def test_volume_and_pages_resolve_an_author_typo(self):
        versions = {}
        for version, name in ((1, "Christoper Bishop"), (2, "Christopher Bishop")):
            path = self.test_dir / f"refs{version}.bib"
            path.write_text(
                f"@article{{ref,title={{Harmonic measure}},author={{{name}}},"
                "journal={Math Journal},volume={62},pages={77--113},year={1994}}",
                encoding="utf-8",
            )
            versions[version] = parse_bib_file(path, "2505.10666")
        self.assertEqual(build_cross_version_citation_map(versions), {(1, "ref"): "ref", (2, "ref"): "ref"})

    def test_abbreviated_journal_preserves_identity(self):
        common = {"citation_key": "ref", "title": "A research article", "authors": ["Alice Smith"], "year": 2020}
        original = {**common, "_locator": ("artificial intelligence", "219", "124")}
        revision = {**common, "_locator": ("artif intell", "219", "124")}
        self.assertEqual(
            build_cross_version_citation_map({1: [original], 2: [revision]}),
            {(1, "ref"): "ref", (2, "ref"): "ref"},
        )


if __name__ == "__main__":
    unittest.main()

