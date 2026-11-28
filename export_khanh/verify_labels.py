"""Verify labels against arXiv IDs that authors wrote in their own bibliography (eprint field / "arXiv:..." text).

  python export_khanh/verify_labels.py auto     -> checks export_khanh/auto_labeled_khanh.csv
  python export_khanh/verify_labels.py hand     -> checks export_khanh/hand_labeled_5_papers_khanh.csv

For each labelled entry:
  CONFIRMED_OK    the bib states an arXiv id and the label agrees (or label=none and that id is not a reference)
  CONFIRMED_WRONG the bib states an arXiv id that is among the paper's references, and the label disagrees
  no evidence     bucketed by the matcher score (auto only) to count how many labels are uncertain
Writes <input>_verify.csv with a verdict per entry.
"""
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent.parent / 'data'
FILES = {'auto': HERE / 'auto_labeled_khanh.csv', 'hand': HERE / 'hand_labeled_5_papers_khanh.csv'}
AID = re.compile(r'(?:arxiv[:\s/]*|eprint\s*=\s*[{"]\s*|abs/)((?:\d{4}\.\d{4,5})|(?:[a-z\-]+(?:\.[A-Z]{2})?/\d{7}))', re.I)
ENTRY_START = re.compile(r'@\w+\s*\{\s*([^,\s]+)\s*,')
BIBITEM = re.compile(r'\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}')
# Score bands for entries without bib evidence; the uncertain band is where hand labels showed errors (0.48-0.67)
# and where near-threshold accepts were occasionally wrong (0.75-0.80).
BANDS = [(0.85, 'sure_match'), (0.75, 'unresolved_accept'), (0.45, 'unresolved_none'), (-1, 'sure_none')]


def raw_entries(paper):
    """citation_key -> raw entry text, merged over versions (newest version wins)."""
    versions = sorted((v for v in paper.glob('v*') if v.name[1:].isdigit()), key=lambda v: int(v.name[1:]))
    out = {}
    for v in reversed(versions):
        for k, t in raw_entries_of_version(v).items():
            out.setdefault(k, t)
    return out


def raw_entries_of_version(vdir):
    """citation_key -> raw text of its bib entry / bibitem in one version dir (brace-balanced, no overrun)."""
    out = {}
    for f in [*vdir.rglob('*.bib'), *vdir.rglob('*.bbl'), *vdir.rglob('*.tex')]:
        t = f.read_text(errors='ignore')
        for m in ENTRY_START.finditer(t):
            depth, i = 0, t.index('{', m.start())
            for j in range(i, min(len(t), i + 20000)):
                depth += {'{': 1, '}': -1}.get(t[j], 0)
                if depth == 0:
                    out.setdefault(m.group(1), t[m.start():j + 1])
                    break
        items = list(BIBITEM.finditer(t))
        for a, b in zip(items, items[1:] + [None]):
            end = b.start() if b else (t.find(r'\end{thebibliography}', a.end()) % (len(t) + 1) or len(t))
            out.setdefault(a.group(1), t[a.end():end])
    return out


def band(score):
    return next(name for lo, name in BANDS if score >= lo)


def main(which):
    src = FILES[which]
    with open(src, encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    cache, refs_cache, out, tally = {}, {}, [], Counter()
    for r in rows:
        pid = r['paper_arxiv_id']
        if pid not in cache:
            cache[pid] = raw_entries(DATA / pid)
            refs_cache[pid] = {x['ref_arxiv_id'] for x in json.loads((DATA / pid / 'references.json').read_text(encoding='utf-8'))
                               if x.get('ref_arxiv_id')}
        ids = {re.sub(r'v\d+$', '', x) for x in AID.findall(cache[pid].get(r['citation_key'], ''))}
        label = r['groundtruth_arxiv_id'] or None
        in_pool = ids & refs_cache[pid]
        # An author-written id is evidence only when it is one of the paper's references; authors sometimes
        # write a wrong id (e.g. dhariwal2021diffusion cites 2111.01027 for "Diffusion Models Beat GANs").
        if in_pool or (ids and not label):
            ok = (label in in_pool) if label else not in_pool
            verdict = 'CONFIRMED_OK' if ok else 'CONFIRMED_WRONG'
        elif which == 'auto':
            verdict = band(float(r['best_score']))
        else:
            verdict = 'no_evidence'
        tally[verdict] += 1
        out.append({**r, 'bib_arxiv_ids': ' '.join(sorted(ids)), 'verdict': verdict})
    dest = src.with_name(src.stem + '_verify.csv')
    with open(dest, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print(f'{src.name}: {len(rows)} entries -> {dest.name}')
    for k, v in sorted(tally.items()):
        print(f'  {k:18} {v:>7,}')
    return out


if __name__ == '__main__':
    main(sys.argv[1])
