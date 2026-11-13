import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.parser import expand_inputs, is_prose, parse_version, split_sentences


class SplitSentencesTest(unittest.TestCase):
    def test_does_not_break_on_abbreviations_numbers_math_urls(self):
        text = (r"See Fig. 1 and Smith et al. for details. The value is 3.14 here. "
                r"We use $a. B$ i.e. math. Visit https://x.org/a.b. Done!")
        self.assertEqual(split_sentences(text), [
            "See Fig. 1 and Smith et al. for details.",
            "The value is 3.14 here.",
            "We use $a. B$ i.e. math.",
            "Visit https://x.org/a.b.",
            "Done!",
        ])

    def test_is_prose_drops_pure_latex(self):
        self.assertFalse(is_prose(r"\vskip 0.3in ]"))
        self.assertFalse(is_prose(r"\icmlauthor{Seongheon Park}{mad}"))
        self.assertTrue(is_prose(r"We propose a \textbf{new} method here."))


class ParseVersionTest(unittest.TestCase):
    def test_follows_input_and_builds_tree(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.tex").write_text(
                "\\documentclass{article}\n\\begin{document}\n\\input{intro}\n\\end{document}\n")
            (root / "intro.tex").write_text(
                "\\section{Intro}\nFirst sentence is here. Second one is here too.\n"
                "\\begin{figure}\\includegraphics{x.png}\\end{figure}\n"
                "\\subsection{Detail}\nA detailed sentence goes here.\n")

            self.assertIn("First sentence", expand_inputs(root / "main.tex", root))

            elements, hierarchy = parse_version(root, "2503.00001", 1)
            kinds = {e[3]: e[2] for e in elements}
            self.assertEqual(kinds["Intro"], "section")
            self.assertEqual(kinds["Detail"], "subsection")
            self.assertEqual(sum(k == "sentence" for k in kinds.values()), 3)
            self.assertEqual(sum(k == "figure" for k in kinds.values()), 1)

            ids = {e[0] for e in elements}
            parent = {eid: p for _, _, eid, p in hierarchy}
            by_content = {e[3]: e[0] for e in elements}
            self.assertEqual(parent[by_content["Detail"]], by_content["Intro"])
            self.assertTrue(all(p in ids or p == "2503.00001" for p in parent.values()))

    def test_braceless_input_and_top_level_main_wins(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "template").mkdir()
            (root / "template" / "a.tex").write_text(
                "\\documentclass{article}\n\\begin{document}\nTemplate text only here.\n\\end{document}\n")
            (root / "z_main.tex").write_text(
                "\\documentclass{article}\n\\usepackage[utf8]{inputenc}\n\\begin{document}\n\\input intro\n\\end{document}\n")
            (root / "intro.tex").write_text("The real paper sentence is here.\n")

            elements, _ = parse_version(root, "2503.00001", 1)
            contents = [e[3] for e in elements]
            self.assertIn("The real paper sentence is here.", contents)
            self.assertNotIn("Template text only here.", contents)

    def test_main_is_longest_document_and_macro_begin_is_ignored(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a_cover.tex").write_text(
                "\\documentclass{letter}\n\\begin{document}\nDear editor, thanks a lot.\n\\end{document}\n")
            (root / "config.tex").write_text("\\documentclass{article}\n")
            (root / "paper.tex").write_text(
                "\\input{config}\n\\newcommand{\\edoc}{\\end{document}}\n\\begin{document}\n"
                "\\chapter{Intro}\n\\subfile{ch1}\n\\end{document}\n")
            (root / "ch1.tex").write_text(
                "\\documentclass[paper]{subfiles}\n\\begin{document}\n"
                "\\section{Part}\nThis long sentence comes from the chapter subfile itself.\n\\end{document}\n")

            elements, hierarchy = parse_version(root, "2503.00001", 1)
            by_content = {e[3]: e for e in elements}
            self.assertNotIn("Dear editor, thanks a lot.", by_content)
            self.assertEqual(by_content["Intro"][2], "chapter")
            parent = {eid: p for _, _, eid, p in hierarchy}
            self.assertEqual(parent[by_content["Part"][0]], by_content["Intro"][0])
            self.assertIn("This long sentence comes from the chapter subfile itself.", by_content)

    def test_pdf_only_version_is_empty(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(parse_version(Path(tmp), "2503.00001", 1), ([], []))


if __name__ == "__main__":
    unittest.main()
