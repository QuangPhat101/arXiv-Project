import gzip
import io
import tarfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.extractor import ExtractionResult, extract_tex_bib

TEX = b"\\documentclass{article}\n\\begin{figure}\\includegraphics{fig.png}\\end{figure}\n"


def make_tar(path: Path, files: dict[str, bytes], symlinks: dict[str, str] | None = None) -> Path:
    with tarfile.open(path, "w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for name, link_target in (symlinks or {}).items():
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = link_target
            tar.addfile(info)
    return path


class TestExtractor(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.target = self.tmp / "out" / "v1"

    def tearDown(self):
        self._tmp.cleanup()

    def test_none_archive_is_pdf_only(self):
        self.assertEqual(extract_tex_bib(None, self.target), ExtractionResult.PDF_ONLY)
        self.assertTrue(self.target.is_dir())
        self.assertEqual(list(self.target.iterdir()), [])

    def test_tar_keeps_only_tex_bib_with_subfolders(self):
        archive = make_tar(
            self.tmp / "src.tar.gz",
            {"main.tex": TEX, "refs.BIB": b"@article{x}", "sections/intro.tex": b"intro",
             "fig.png": b"\x89PNG", "main.pdf": b"%PDF-1.5"},
        )
        self.assertEqual(extract_tex_bib(archive, self.target), ExtractionResult.SUCCESS)
        found = sorted(p.relative_to(self.target).as_posix() for p in self.target.rglob("*") if p.is_file())
        self.assertEqual(found, ["main.tex", "refs.BIB", "sections/intro.tex"])
        self.assertEqual((self.target / "main.tex").read_bytes(), TEX)

    def test_tar_without_latex_is_pdf_only(self):
        archive = make_tar(self.tmp / "src.tar.gz", {"paper.pdf": b"%PDF-1.5", "fig.png": b"x"})
        self.assertEqual(extract_tex_bib(archive, self.target), ExtractionResult.PDF_ONLY)

    def test_zip_slip_and_symlinks_are_skipped(self):
        archive = make_tar(
            self.tmp / "evil.tar.gz",
            {"../evil.tex": b"x", "/tmp/abs_evil.tex": b"x", "ok.tex": b"ok"},
            symlinks={"link.tex": "/etc/passwd"},
        )
        self.assertEqual(extract_tex_bib(archive, self.target), ExtractionResult.SUCCESS)
        self.assertFalse((self.target.parent / "evil.tex").exists())
        self.assertFalse((self.target / "link.tex").exists())
        self.assertEqual([p.name for p in self.target.iterdir()], ["ok.tex"])

    def test_single_gzip_becomes_main_tex(self):
        archive = self.tmp / "src.gz"
        archive.write_bytes(gzip.compress(TEX))
        self.assertEqual(extract_tex_bib(archive, self.target), ExtractionResult.SUCCESS)
        self.assertEqual((self.target / "main.tex").read_bytes(), TEX)

    def test_gzipped_pdf_is_pdf_only(self):
        archive = self.tmp / "src.gz"
        archive.write_bytes(gzip.compress(b"%PDF-1.4 data"))
        self.assertEqual(extract_tex_bib(archive, self.target), ExtractionResult.PDF_ONLY)

    def test_raw_pdf_is_pdf_only(self):
        archive = self.tmp / "src"
        archive.write_bytes(b"%PDF-1.7\n...")
        self.assertEqual(extract_tex_bib(archive, self.target), ExtractionResult.PDF_ONLY)

    def test_corrupt_files_fail(self):
        junk = self.tmp / "junk"
        junk.write_bytes(b"not an archive at all")
        self.assertEqual(extract_tex_bib(junk, self.target), ExtractionResult.FAILED)
        broken_gz = self.tmp / "broken.gz"
        broken_gz.write_bytes(gzip.compress(TEX)[:20])
        self.assertEqual(extract_tex_bib(broken_gz, self.target), ExtractionResult.FAILED)


if __name__ == "__main__":
    unittest.main()
