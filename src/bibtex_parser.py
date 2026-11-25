"""BibTeX and Citation Parser Module.

Assigned to: Bảo
Purpose:
    Extract structured citation metadata from LaTeX source archives across
    all paper versions. Supports both standalone `.bib` files and inline
    `\\begin{thebibliography} ... \\bibitem{key}` blocks inside `.tex` files.
    Enforces deduplication and cross-version citation key alignment.

Schema (bibtex table):
    - arxiv_id: str (non-null)
    - citation_key: str (non-null)
    - entry_type: str ('article', 'inproceedings', 'book', 'misc', etc.)
    - title: str
    - authors: list[str]
    - year: int, nullable
    - doi: str, nullable
    - journal: str, nullable
    - url: str, nullable
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


def clean_latex_markup(text: str) -> str:
    """Strip LaTeX formatting, braces, and math markers to return plain clean text."""
    if not text:
        return ""
    # Strip comments
    text = re.sub(r'(?<!\\)%.*', '', text)
    # Strip \url{...}
    text = re.sub(r'\\url\{[^}]*\}', '', text)
    # Strip styling commands: \emph{x}, \textbf{x}, \textit{x}, \textsc{x}, \texttt{x}
    text = re.sub(r'\\(?:emph|textit|textbf|textsc|texttt|underline|mbox|bold|rm)\{([^}]*)\}', r'\1', text)
    # Strip \href{url}{label} -> label
    text = re.sub(r'\\href\{[^}]*\}\{([^}]*)\}', r'\1', text)
    # Strip generic LaTeX commands
    text = re.sub(r'\\[a-zA-Z]+\*?(?:\[[^\]]*\])?', ' ', text)
    # Strip residual braces and math symbols
    text = text.replace('{', '').replace('}', '').replace('$', '').replace('~', ' ')
    # Normalize whitespace
    return ' '.join(text.split())


def parse_bib_file(bib_path: Path | str, arxiv_id: str) -> List[Dict[str, Any]]:
    """Parse standalone BibTeX file (.bib) into structured records."""
    bib_path = Path(bib_path)
    if not bib_path.exists():
        return []

    content = bib_path.read_text(encoding="utf-8", errors="ignore")

    # 1. Collect @String definitions supporting both @string{...} and @string(...)
    strings: Dict[str, str] = {}
    for m in re.finditer(r'@string\s*[{(]\s*([a-zA-Z0-9_-]+)\s*=\s*(?:\{([^}]*)\}|"([^"]*)")\s*[})]', content, re.IGNORECASE):
        k = m.group(1).strip().lower()
        v = m.group(2) if m.group(2) is not None else m.group(3)
        strings[k] = clean_latex_markup(v) if v else ""

    # 2. Extract entries: @entry_type{key, ...}
    entry_re = re.compile(r'@([a-zA-Z]+)\s*\{\s*([^,\s]+)\s*,', re.DOTALL)
    entries: List[Dict[str, Any]] = []

    matches = list(entry_re.finditer(content))
    for i, m in enumerate(matches):
        entry_type = m.group(1).lower()
        if entry_type in ["string", "comment", "preamble"]:
            continue

        key = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start:end]

        # Extract fields
        field_matches = list(re.finditer(r'([a-zA-Z0-9_-]+)\s*=\s*', body))
        fields: Dict[str, str] = {}
        for fi, fm in enumerate(field_matches):
            fname = fm.group(1).lower()
            fstart = fm.end()
            fend = field_matches[fi + 1].start() if fi + 1 < len(field_matches) else len(body)
            raw_val = body[fstart:fend].strip()
            # Remove trailing comma or closing brace
            raw_val = re.sub(r'[,}]\s*$', '', raw_val).strip()

            if (raw_val.startswith('{') and raw_val.endswith('}')) or (raw_val.startswith('"') and raw_val.endswith('"')):
                val = raw_val[1:-1].strip()
            elif raw_val.lower() in strings:
                val = strings[raw_val.lower()]
            else:
                val = raw_val
            fields[fname] = val

        # Authors
        authors: List[str] = []
        raw_authors = fields.get("author", fields.get("authors", ""))
        if raw_authors:
            parts = re.split(r'\s+and\s+', raw_authors, flags=re.IGNORECASE)
            for a in parts:
                clean_a = clean_latex_markup(a).strip()
                if clean_a:
                    if "," in clean_a:
                        subparts = [sp.strip() for sp in clean_a.split(",", 1)]
                        clean_a = f"{subparts[1]} {subparts[0]}".strip()
                    if clean_a.lower() != "others":
                        authors.append(clean_a)

        # Year
        year: Optional[int] = None
        raw_year = fields.get("year", "")
        m_year = re.search(r'\b(19\d\d|20\d\d)\b', str(raw_year))
        if m_year:
            try:
                year = int(m_year.group(1))
            except ValueError:
                pass

        # DOI
        doi: Optional[str] = None
        raw_doi = fields.get("doi", "")
        m_doi = re.search(r'(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)', raw_doi)
        if m_doi:
            doi = m_doi.group(1).rstrip('.,;)]')

        title = clean_latex_markup(fields.get("title", ""))
        raw_journal = fields.get("journal", fields.get("booktitle", fields.get("venue", "")))
        journal = strings.get(raw_journal.lower(), clean_latex_markup(raw_journal))
        url = fields.get("url", "").strip() or None

        entries.append({
            "arxiv_id": str(arxiv_id),
            "citation_key": str(key),
            "entry_type": str(entry_type),
            "title": str(title),
            "authors": authors,
            "year": year,
            "doi": str(doi) if doi else None,
            "journal": str(journal) if journal else None,
            "url": str(url) if url else None,
        })

    return entries


def parse_tex_bibitem(tex_path: Path | str, arxiv_id: str) -> List[Dict[str, Any]]:
    """Parse \\begin{thebibliography} ... \\bibitem ... \\end{thebibliography} blocks in .tex files."""
    tex_path = Path(tex_path)
    if not tex_path.exists():
        return []

    content = tex_path.read_text(encoding="utf-8", errors="ignore")
    bib_block_m = re.search(r'\\begin\{thebibliography\}.*?\\end\{thebibliography\}', content, re.DOTALL)
    if not bib_block_m:
        return []

    bib_text = bib_block_m.group(0)
    items = re.split(r'\\bibitem\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}', bib_text)
    entries: List[Dict[str, Any]] = []

    for i in range(1, len(items), 2):
        key = items[i].strip()
        body = items[i + 1]
        body = re.sub(r'\\end\{thebibliography\}.*', '', body, flags=re.DOTALL)

        # DOI
        doi: Optional[str] = None
        m_doi = re.search(r'(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)', body)
        if m_doi:
            doi = m_doi.group(1).rstrip('.,;)]')

        # URL
        url: Optional[str] = None
        m_url = re.search(r'(https?://[^\s{}]+)', body)
        if m_url:
            url = m_url.group(1).rstrip('.,;)]')

        # Year
        year: Optional[int] = None
        m_year = re.search(r'\b(19\d\d|20\d\d)\b', body)
        if m_year:
            year = int(m_year.group(1))

        # Title heuristic
        title = ""
        m_title = re.search(r'\\(?:emph|textit)\{([^}]*)\}', body)
        if m_title:
            title = clean_latex_markup(m_title.group(1))
        else:
            m_quote = re.search(r'``([^\'\']*)[\'\'"]', body)
            if m_quote:
                title = clean_latex_markup(m_quote.group(1))
            else:
                cleaned_body = clean_latex_markup(body)
                parts = cleaned_body.split('.')
                title = parts[1].strip() if len(parts) > 1 else cleaned_body[:120].strip()

        # Authors heuristic
        authors: List[str] = []
        cleaned_body = clean_latex_markup(body)
        first_segment = cleaned_body.split('.')[0] if '.' in cleaned_body else cleaned_body
        for a in re.split(r',\s*|\s+and\s+', first_segment):
            a_clean = a.strip()
            if len(a_clean) > 2 and not any(c in a_clean.lower() for c in ['http', 'doi', 'vol', 'pages', '19', '20', 'et al']):
                authors.append(a_clean)

        entries.append({
            "arxiv_id": str(arxiv_id),
            "citation_key": str(key),
            "entry_type": "misc",
            "title": str(title),
            "authors": authors,
            "year": year,
            "doi": str(doi) if doi else None,
            "journal": None,
            "url": str(url) if url else None,
        })

    return entries


def parse_version_bibtex(vdir: Path | str, arxiv_id: str) -> List[Dict[str, Any]]:
    """Parse all citation entries in a version directory (.bib first, then .tex fallback)."""
    vdir = Path(vdir)
    if not vdir.exists():
        return []

    # 1. Search for .bib files
    bib_files = sorted(vdir.rglob("*.bib"))
    all_entries: List[Dict[str, Any]] = []
    seen_keys: Set[str] = set()

    for bf in bib_files:
        for entry in parse_bib_file(bf, arxiv_id):
            if entry["citation_key"] not in seen_keys:
                seen_keys.add(entry["citation_key"])
                all_entries.append(entry)

    # 2. If no .bib files or missing, scan .tex files for \begin{thebibliography}
    if not all_entries:
        for tf in sorted(vdir.rglob("*.tex")):
            for entry in parse_tex_bibitem(tf, arxiv_id):
                if entry["citation_key"] not in seen_keys:
                    seen_keys.add(entry["citation_key"])
                    all_entries.append(entry)

    return all_entries


def normalize_title_for_matching(title: str) -> str:
    """Normalize paper title for fuzzy/exact deduplication matching."""
    if not title:
        return ""
    # Lowercase, remove non-alphanumeric
    cleaned = re.sub(r'[^a-z0-9\s]', '', title.lower())
    return ' '.join(cleaned.split())


def build_cross_version_citation_map(
    entries_by_version: Dict[int, List[Dict[str, Any]]]
) -> Dict[Tuple[int, str], str]:
    """Build a mapping from (version, original_citation_key) to canonical_citation_key.

    Uses title match and key overlap to align keys across versions.
    """
    canonical_map: Dict[Tuple[int, str], str] = {}
    title_to_canonical: Dict[str, str] = {}

    sorted_versions = sorted(entries_by_version.keys())
    for v in sorted_versions:
        entries = entries_by_version[v]
        for e in entries:
            key = e["citation_key"]
            norm_title = normalize_title_for_matching(e.get("title", ""))

            if norm_title and norm_title in title_to_canonical:
                canonical_key = title_to_canonical[norm_title]
            else:
                canonical_key = key
                if norm_title and len(norm_title) > 8:
                    title_to_canonical[norm_title] = canonical_key

            canonical_map[(v, key)] = canonical_key

    return canonical_map
