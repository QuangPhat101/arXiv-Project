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
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.parser import (
    BIB_BLOCK_RE, BIB_INPUT_RE, BIB_RE, BIB_RESOURCE_RE, BODY_RE, CITE_RE, extract_body, load_version_tex,
    read_source_text, strip_comments,
)


ARXIV_NUMBER = r'(?:\d{4}\.\d{4,5}|[a-z][a-z0-9.-]*/\d{7})'
ARXIV_LINK = re.compile(r'(?:arxiv\s*:\s*|arxiv\.org/(?:abs|pdf)/|10\.48550/arxiv\.)'
                        rf'({ARXIV_NUMBER})(?:v\d+)?\b', re.I)


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


def parse_bib_file(bib_path: Path | str, arxiv_id: str, *, keys=None) -> List[Dict[str, Any]]:
    """Parse standalone BibTeX file (.bib) into structured records."""
    bib_path = Path(bib_path)
    if not bib_path.is_file() or (keys is not None and not keys):
        return []

    content = re.sub(r'^[ \t]*%[^\r\n]*', '', read_source_text(bib_path), flags=re.M)

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
        if keys is not None and key not in keys:
            continue
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
        url_match = re.search(r'https?://[^\s{}"]+', fields.get("url") or fields.get("howpublished", ""))
        url = url_match.group().rstrip('.,;)]') if url_match else None
        arxiv_match = ARXIV_LINK.search(f"{doi or ''} {url or ''} {fields.get('eprint', '')} {journal}")
        eprint = re.fullmatch(rf'({ARXIV_NUMBER})(?:v\d+)?', fields.get("eprint", ""), re.I)
        ref_arxiv_id = arxiv_match.group(1) if arxiv_match else None
        if not ref_arxiv_id and eprint and fields.get("archiveprefix", "arxiv").casefold() == "arxiv":
            ref_arxiv_id = eprint.group(1)
        locator = tuple(normalize_title_for_matching(value) for value in
                        (journal, fields.get("volume"), fields.get("pages")))

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
            **({"_arxiv_id": ref_arxiv_id.casefold()} if ref_arxiv_id else {}),
            **({"_locator": locator} if all(locator) else {}),
        })

    return entries


def parse_tex_bibitem(tex_path: Path | str, arxiv_id: str) -> List[Dict[str, Any]]:
    """Parse \\begin{thebibliography} ... \\bibitem ... \\end{thebibliography} blocks in .tex files."""
    tex_path = Path(tex_path)
    if not tex_path.exists():
        return []

    return parse_bibitems(strip_comments(read_source_text(tex_path)), arxiv_id)


def parse_bibitems(content, arxiv_id):
    bib_text = "\n".join(match.group() for match in BIB_BLOCK_RE.finditer(content))
    items = re.split(r'\\bibitem\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}', bib_text)
    entries: List[Dict[str, Any]] = []

    for i in range(1, len(items), 2):
        key = items[i].strip()
        body = items[i + 1]
        body = re.sub(r'\\end\s*\{thebibliography\}.*', '', body, flags=re.DOTALL)

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
        arxiv_id_pattern = r'(\d{2})(?:0[1-9]|1[0-2])\.\d{4,5}(?:v\d+)?\b'
        arxiv_match = re.search(r'(?:arxiv\s*:\s*|arxiv\.org/(?:abs|pdf)/)' + arxiv_id_pattern, body, re.I)
        year_text = re.sub(r'arxiv\s*:\s*' + arxiv_id_pattern, '', body, flags=re.I)
        for identifier in (doi, url):
            if identifier:
                year_text = year_text.replace(identifier, '')
        m_year = re.search(r'\b(19\d\d|20\d\d)\b', year_text)
        if m_year:
            year = int(m_year.group(1))
        elif arxiv_match:
            year = 2000 + int(arxiv_match.group(1))

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


def parse_version_bibtex(vdir: Path | str, arxiv_id: str, *, source=None, issues=None) -> List[Dict[str, Any]]:
    """Read the bibliography selected by the main document of this version."""
    vdir = Path(vdir).resolve()
    if not vdir.is_dir():
        return []

    def report(kind, **details):
        if issues is not None:
            issues.append({"kind": kind, **details})

    main, text = load_version_tex(vdir) if source is None else source
    entries = {}
    if main is None:
        bib_files = sorted(path for path in vdir.rglob("*.bib") if path.resolve().is_relative_to(vdir))
        if bib_files:
            report("no_main_tex", resources=[path.relative_to(vdir).as_posix() for path in bib_files])
            for path in bib_files:
                for row in parse_bib_file(path, arxiv_id):
                    entries.setdefault(row["citation_key"], row)
        return list(entries.values())

    document = BODY_RE.search(text)
    if document:
        text = text[:document.end()]
    body = extract_body(text)
    missing_bbl = list(dict.fromkeys(BIB_INPUT_RE.findall(text)))
    if missing_bbl:
        report("missing_bbl_inputs", resources=missing_bbl)
    commands = BIB_RE.sub(' ', body)
    wanted = set()
    wildcard = False
    for match in CITE_RE.finditer(commands):
        cited_keys = {key.strip() for key in match.group(2).split(',') if key.strip()}
        wildcard |= match.group(1).casefold().startswith(r'\nocite') and '*' in cited_keys
        wanted.update(key for key in cited_keys - {'*'} if not key.startswith('#'))

    main = main.resolve()
    names = dict.fromkeys(name.strip() for match in BIB_RESOURCE_RE.finditer(text)
                          for name in match.group(1).split(',') if name.strip())
    resources = {}
    missing_resources = []
    for name in names:
        filename = Path(name.replace(r'\jobname', main.stem))
        if filename.suffix.casefold() != '.bib':
            filename = Path(str(filename) + '.bib')
        if not filename.anchor and '\\' not in filename.name:
            for base in dict.fromkeys((main.parent, vdir)):
                path = (base / filename).resolve()
                if path.is_relative_to(vdir) and path.is_file():
                    resources[path] = None
                    break
            else:
                missing_resources.append(name)
        else:
            missing_resources.append(name)
    if missing_resources:
        report("missing_bib_resources", resources=missing_resources)
    if wildcard and not resources:
        report("wildcard_without_resolved_bib", resources=list(names))

    generated = main.with_suffix('.bbl')
    bbl = strip_comments(read_source_text(generated)) if generated.is_file() and generated.resolve().is_relative_to(vdir) else ''
    bibitems = parse_bibitems(body, arxiv_id) + parse_bibitems(bbl, arxiv_id)
    wanted.update(row["citation_key"] for row in bibitems)
    wanted.update(re.findall(r'\\entry\s*\{([^{}]+)\}\s*\{[^{}]*\}', bbl))
    if names and not wildcard and not wanted:
        report("no_recognized_citation_keys", resources=list(names))

    for path in resources:
        for row in parse_bib_file(path, arxiv_id, keys=None if wildcard else wanted - entries.keys()):
            entries.setdefault(row["citation_key"], row)
    for row in bibitems:
        target = entries.setdefault(row["citation_key"], row)
        fill_reference_fields(target, row)

    remaining = wanted - entries.keys()
    if remaining:
        recovered = set()
        for path in sorted(set(vdir.rglob("*.bib")) - resources.keys()):
            if not path.resolve().is_relative_to(vdir):
                continue
            for row in parse_bib_file(path, arxiv_id, keys=remaining - recovered):
                key = row["citation_key"]
                entries.setdefault(key, row)
                recovered.add(key)
            if recovered == remaining:
                break
        if recovered and names:
            report("citation_keys_from_undeclared_bib", keys=sorted(recovered))
        if remaining - recovered:
            report("unresolved_citation_keys", keys=sorted(remaining - recovered))
    return list(entries.values())


def normalize_title_for_matching(title: str) -> str:
    """Normalize a title for exact comparison."""
    return ' '.join(re.sub(r'[^\w\s]', '', (title or "").casefold()).split())


def fill_reference_fields(target, source):
    for name, value in source.items():
        if value and not target.get(name):
            target[name] = value


def reference_identity(entry):
    url = entry.get("url") or ""
    doi = (entry.get("doi") or "").strip().casefold()
    arxiv = entry.get("_arxiv_id")
    if not arxiv:
        match = ARXIV_LINK.search(f"{url} {doi}")
        arxiv = match.group(1).casefold() if match else ""
    if doi.startswith("10.48550/arxiv."):
        doi = ""
    return {
        "title": normalize_title_for_matching(entry.get("title", "")),
        "authors": frozenset(normalize_title_for_matching(name) for name in entry.get("authors") or ()),
        "year": entry.get("year"),
        "url": re.sub(r'^https?://(?:www\.)?', '', url, flags=re.I).split('#', 1)[0].rstrip("/"),
        "doi": doi,
        "arxiv": arxiv,
        "locator": entry.get("_locator"),
    }


def reference_match_score(left, right, same_key):
    strong = ("doi", "arxiv")
    if any(left[field] and right[field] and left[field] != right[field] for field in strong):
        return 0
    if any(left[field] and left[field] == right[field] for field in strong):
        return 2
    title_match = bool(left["title"] and left["title"] == right["title"])
    left_locator, right_locator = left["locator"], right["locator"]
    if left_locator and right_locator and left_locator[0] == right_locator[0]:
        if left_locator != right_locator:
            return 0
        if title_match:
            return 2
    if any(left[name] and right[name] and left[name] != right[name] for name in ("title", "url")):
        return 0
    left_authors, right_authors = left["authors"], right["authors"]
    authors_match = bool(left_authors and right_authors and
                         (left_authors <= right_authors or right_authors <= left_authors))
    if left_authors and right_authors and not authors_match:
        return 0
    if left["year"] and right["year"] and left["year"] != right["year"]:
        preprint_revision = (same_key and title_match and left_authors and left_authors == right_authors
                             and bool(left["arxiv"]) != bool(right["arxiv"]))
        if not preprint_revision:
            return 0
    url_match = bool(left["url"] and left["url"] == right["url"])
    return int(same_key or (title_match and (authors_match or url_match)))


def build_cross_version_citation_map(
    entries_by_version: Dict[int, List[Dict[str, Any]]]
) -> Dict[Tuple[int, str], str]:
    """Map each original version and citation key to the retained key."""
    canonical_map: Dict[Tuple[int, str], str] = {}
    by_signature = defaultdict(set)
    identities = {}
    original_keys = {entry["citation_key"] for rows in entries_by_version.values() for entry in rows}
    for version, entries in sorted(entries_by_version.items()):
        for entry in entries:
            key = entry["citation_key"]
            signature = ("key", key)
            identity = reference_identity(entry)
            signatures = [signature]
            signatures.extend((name, identity[name]) for name in ("doi", "arxiv", "title", "locator") if identity[name])
            candidates = set().union(*(by_signature[term] for term in signatures))
            best_score, best = 0, []
            for candidate in candidates:
                score = reference_match_score(identities[candidate], identity, candidate in by_signature[signature])
                if score > best_score:
                    best_score, best = score, [candidate]
                elif score and score == best_score:
                    best.append(candidate)
            if len(best) == 1:
                canonical_key = best[0]
                fill_reference_fields(identities[canonical_key], identity)
            else:
                canonical_key = key
                if canonical_key in identities:
                    base = f"{key}__v{version}"
                    canonical_key = base
                    suffix = 2
                    while canonical_key in original_keys or canonical_key in identities:
                        canonical_key = f"{base}_{suffix}"
                        suffix += 1
                identities[canonical_key] = identity

            for term in signatures:
                by_signature[term].add(canonical_key)
            canonical_map[(version, key)] = canonical_key

    return canonical_map
