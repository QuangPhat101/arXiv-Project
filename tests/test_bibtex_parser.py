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

    def test_parse_tex_bibitem_with_author_initials_and_eprint(self):
        tex_content = r"""
        \begin{document}
        \begin{thebibliography}{99}
        \bibitem{vaswani2017}
        A.~Vaswani, N.~Shazeer, et al. Attention is all you need. In NeurIPS, 2017. arXiv:1706.03762.
        \bibitem{smith2020}
        J.~Smith, A.~Wang, F.~K.~Zhao. Deep residual learning for image recognition. CVPR, 2016.
        \end{thebibliography}
        \end{document}
        """
        tex_file = self.test_dir / "paper2.tex"
        tex_file.write_text(tex_content, encoding="utf-8")

        entries = parse_tex_bibitem(tex_file, "sample_paper_2")
        self.assertEqual(len(entries), 2)
        
        # Check first entry: title should NOT be 'et al.' or 'Shazeer, N'
        self.assertEqual(entries[0]["title"], "Attention is all you need")
        self.assertEqual(entries[0]["eprint"], "1706.03762")
        
        # Check second entry: title should NOT be 'Wang, A' or 'K'
        self.assertEqual(entries[1]["title"], "Deep residual learning for image recognition")

    def test_cross_version_citation_map(self):
        v1_entries = [{
            "citation_key": "vaswani_orig",
            "title": "Attention Is All You Need",
        }]
        v2_entries = [{
            "citation_key": "vaswani2017",
            "title": "Attention Is All You Need",
        }]
        mapping = build_cross_version_citation_map({1: v1_entries, 2: v2_entries})
        self.assertEqual(mapping[(1, "vaswani_orig")], "vaswani_orig")
        self.assertEqual(mapping[(2, "vaswani2017")], "vaswani_orig")


if __name__ == "__main__":
    unittest.main()

