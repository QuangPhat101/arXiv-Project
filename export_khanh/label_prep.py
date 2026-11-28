"""Pre-label citations for hand labeling: for each cited BibTeX entry, rank arXiv references by similarity.

Usage (from the code repo root): python <this file> ../data out_dir
Writes candidates_all.csv (every cited entry of every scanned paper) and paper_stats.csv.
"""
import csv
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, '.')
from src.bibtex_parser import normalize_title_for_matching, parse_version_bibtex  # noqa: E402
from src.parser import CITE_RE, expand_inputs, extract_body, find_main_tex  # noqa: E402


def last_names(authors):
    if isinstance(authors, str):
        authors = re.split(r'\s+and\s+|,\s*', authors)
    out = set()
    for a in authors or []:
        a = re.sub(r'[{}\\\'"`^~]', '', str(a)).strip()
        if a:
            out.add(a.split(',')[0].split()[-1].lower() if ',' not in a else a.split(',')[0].strip().lower())
    return out


def clean_title(t):
    # S2 sometimes embeds a whole LaTeX document for a math symbol in the title: keep only its body.
    t = re.sub(r'\\documentclass.*?\\begin\{document\}(.*?)\\end\{document\}', r' \1 ', t or '', flags=re.S)
    return normalize_title_for_matching(re.sub(r'[$\\{}]', ' ', t))


def score(entry, ref):
    t = SequenceMatcher(None, clean_title(entry.get('title')), clean_title(ref.get('ref_title'))).ratio()
    a, b = last_names(entry.get('authors')), last_names(ref.get('ref_authors'))
    au = len(a & b) / len(a | b) if a and b else 0.0
    return round(0.8 * t + 0.2 * au, 4), round(t, 4)


def cited_keys(vdir):
    main = find_main_tex(vdir)
    if main is None:
        return set()
    body = extract_body(expand_inputs(main, main.parent))
    return {k.strip() for m in CITE_RE.finditer(body) for k in m.group(2).split(',') if k.strip()}


def main(data_dir, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, stats = [], []
    only = set(sys.argv[3].split(',')) if len(sys.argv) > 3 else None
    for paper in sorted(Path(data_dir).glob('25*')):
        if only and paper.name not in only:
            continue
        versions = sorted((v for v in paper.glob('v*') if v.name[1:].isdigit()), key=lambda v: int(v.name[1:]))
        if not versions or not (paper / 'references.json').exists():
            continue
        latest = versions[-1]
        if any(f.stat().st_size > 5_000_000 for f in latest.rglob('*.bib')):
            continue  # skip papers shipping a whole anthology.bib
        refs = [r for r in json.loads((paper / 'references.json').read_text(encoding='utf-8')) if r.get('ref_arxiv_id')]
        if len(refs) < 20:
            continue
        keys = cited_keys(latest)
        entries = [e for e in parse_version_bibtex(latest, paper.name) if e['citation_key'] in keys and e.get('title')]
        meta = json.loads((paper / 'metadata.json').read_text(encoding='utf-8'))
        strong = 0
        for e in entries:
            ranked = sorted(((score(e, r), r) for r in refs), key=lambda x: -x[0][0])[:3]
            best = ranked[0][0][1] if ranked else 0
            strong += best >= 0.9
            row = dict(paper_arxiv_id=paper.name, paper_title=meta.get('title', ''), version=latest.name,
                       citation_key=e['citation_key'], citation_title=e.get('title'),
                       citation_authors=e.get('authors'), citation_year=e.get('year'))
            for i, ((s, t), r) in enumerate(ranked, 1):
                row.update({f'cand{i}_arxiv_id': r['ref_arxiv_id'], f'cand{i}_title': r['ref_title'],
                            f'cand{i}_score': s, f'cand{i}_title_sim': t})
            rows.append(row)
        stats.append(dict(paper_arxiv_id=paper.name, title=meta.get('title', ''), n_versions=len(versions),
                          arxiv_refs=len(refs), cited_entries=len(entries), strong_matches=strong))
    cols = sorted({k for r in rows for k in r}, key=lambda k: list(rows[0]).index(k) if k in rows[0] else 99)
    with open(out_dir / 'candidates_all.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    with open(out_dir / 'paper_stats.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(stats[0]))
        w.writeheader()
        w.writerows(stats)
    print(len(stats), 'papers scanned,', len(rows), 'cited entries')


if __name__ == '__main__':
    main(Path(sys.argv[1]), Path(sys.argv[2]))
