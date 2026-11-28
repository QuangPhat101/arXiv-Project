"""Automatic citation labelling for Khanh's range with the group's hybrid CitationMatcher (src/matching.py, Bao).

Rule: rank every arXiv reference of the paper with CitationMatcher.compute_hybrid_score; the label is cand_1 if its
score >= THRESHOLD, otherwise `none`. THRESHOLD was chosen on the 200 hand-labelled entries (98.5% accuracy,
0 wrong accepts at 0.74-0.76). The reference year is taken from ref_submission_date[:4], because references.json
has no `ref_year` field.

Usage (from the code repo root):
  python export_khanh/auto_label.py sample 495   -> export_khanh/auto_labeled_khanh.csv
  python export_khanh/auto_label.py check        -> accuracy of the rule on export_khanh/hand_labeled_5_papers_khanh.csv
"""
import csv
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
import re  # noqa: E402

from label_prep import cited_keys  # noqa: E402
from src.bibtex_parser import build_cross_version_citation_map, parse_version_bibtex  # noqa: E402
from verify_labels import AID, raw_entries_of_version  # noqa: E402
from src.matching import CitationMatcher, build_idf_dict  # noqa: E402

DATA = HERE.parent.parent / 'data'
MANUAL = {'2503.02783', '2503.03355', '2503.03509', '2503.05695', '2503.06704'}
OUT = HERE / 'auto_labeled_khanh.csv'
THRESHOLD = 0.75
SEED = 42  # fixed so the sample is reproducible
MATCHER = CitationMatcher()


def year(v):
    s = str(v or '')[:4]
    return int(s) if s.isdigit() else None


def load_paper(paper):
    """(title, arXiv refs, cited bib entries merged over ALL versions), or None if the paper cannot be labelled.

    Entries: cited with \\cite in some version and having a title. Keys are mapped to the canonical key with the
    group's build_cross_version_citation_map (same as the bibtex table); each entry keeps the arXiv ids its authors
    wrote in the bib (eprint / "arXiv:..."), from any version.
    """
    versions = sorted((v for v in paper.glob('v*') if v.name[1:].isdigit()), key=lambda v: int(v.name[1:]))
    if not versions or not (paper / 'references.json').exists():
        return None
    if any(f.stat().st_size > 5_000_000 for v in versions for f in v.rglob('*.bib')):
        return None  # a whole-anthology .bib is not the paper's real bibliography
    refs = [r for r in json.loads((paper / 'references.json').read_text(encoding='utf-8')) if r.get('ref_arxiv_id')]
    by_version, raw = {}, {}
    for v in versions:
        n = int(v.name[1:])
        keys = cited_keys(v)
        by_version[n] = [e for e in parse_version_bibtex(v, paper.name) if e['citation_key'] in keys and e.get('title')]
        raw[n] = raw_entries_of_version(v)
    if not refs or not any(by_version.values()):
        return None
    canon = build_cross_version_citation_map(by_version)
    merged = {}
    for n in sorted(by_version, reverse=True):  # newest version first: its title/authors win
        for e in by_version[n]:
            key = canon.get((n, e['citation_key']), e['citation_key'])
            m = merged.setdefault(key, {**e, 'citation_key': key, 'bib_ids': set()})
            m['bib_ids'] |= {re.sub(r'v\d+$', '', x) for x in AID.findall(raw[n].get(e['citation_key'], ''))}
    title = json.loads((paper / 'metadata.json').read_text(encoding='utf-8')).get('title', '')
    return title, refs, list(merged.values())


def ranked(entry, refs, idf):
    scored = [(MATCHER.compute_hybrid_score(entry.get('title', ''), entry.get('authors') or [], year(entry.get('year')),
                                            r.get('ref_title', ''), r.get('ref_authors') or [],
                                            year(r.get('ref_submission_date')), idf), r['ref_arxiv_id']) for r in refs]
    return sorted(scored, reverse=True)


def label_paper(pid, refs, entries):
    """Yield (entry, label, best_score, method). An arXiv id written by the authors wins over the score."""
    idf = build_idf_dict([r.get('ref_title', '') for r in refs])
    ref_ids = {r['ref_arxiv_id'] for r in refs}
    for e in entries:
        best_score, best_id = ranked(e, refs, idf)[0]
        stated = sorted(e.get('bib_ids', set()) & ref_ids)
        if len(stated) == 1:
            yield e, stated[0], best_score, 'bib_arxiv_id'
        else:
            yield e, (best_id if best_score >= THRESHOLD else None), best_score, 'score'


def sample(n):
    papers = [p for p in sorted(DATA.glob('25*')) if p.name not in MANUAL]
    random.Random(SEED).shuffle(papers)
    out, used = [], 0
    for p in papers:
        if used == n:
            break
        loaded = load_paper(p)
        if loaded is None:
            continue
        title, refs, entries = loaded
        for e, label, score, method in label_paper(p.name, refs, entries):
            out.append({'paper_arxiv_id': p.name, 'paper_title': title, 'citation_key': e['citation_key'],
                        'citation_title': e.get('title'), 'citation_authors': e.get('authors'),
                        'citation_year': e.get('year'), 'groundtruth_arxiv_id': label or '',
                        'best_score': round(score, 4), 'method': method})
        used += 1
    if used < n:
        sys.exit(f'only {used} labelable papers found, asked for {n}')
    with open(OUT, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    matched = sum(bool(r['groundtruth_arxiv_id']) for r in out)
    by_id = sum(r['method'] == 'bib_arxiv_id' for r in out)
    print(f'{OUT.name}: {used} papers, {len(out)} entries, {matched} matched ({by_id} via arXiv id in bib), '
          f'{len(out) - matched} none')


def check():
    hand = HERE / 'hand_labeled_5_papers_khanh.csv'
    with open(hand, encoding='utf-8-sig') as f:
        gold = {(r['paper_arxiv_id'], r['citation_key']): r['groundtruth_arxiv_id'] or None for r in csv.DictReader(f)}
    hit = total = 0
    for pid in sorted(MANUAL):
        _, refs, entries = load_paper(DATA / pid)
        for e, label, score, _ in label_paper(pid, refs, entries):
            key = (pid, e['citation_key'])
            if key in gold:
                total += 1
                hit += label == gold[key]
                if label != gold[key]:
                    print(f'  auto {label} vs hand {gold[key]} | score {score:.2f} | {pid} {e["citation_key"]}')
    print(f'accuracy on hand labels: {hit}/{total} = {hit / total:.1%}')


if __name__ == '__main__':
    {'sample': lambda: sample(int(sys.argv[2])), 'check': check}[sys.argv[1]]()
