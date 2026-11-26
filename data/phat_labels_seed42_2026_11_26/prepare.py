"""Build the seed 42 citation label handoff for Phat's assigned papers."""

from __future__ import annotations

import collections
import csv
import importlib.util
import json
import random
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
DATA = ROOT / 'data' / 'data'
sys.path.insert(0, str(ROOT))
from src.bibtex_parser import build_cross_version_citation_map, parse_version_bibtex
from src.parser import BIB_RE, CITE_RE, expand_inputs, extract_body, find_main_tex
from src.run_m2_pipeline import process_single_paper

spec = importlib.util.spec_from_file_location('matching_bao_snapshot', OUT / 'matching_bao_snapshot.py')
bao = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bao)
matcher = bao.CitationMatcher()
MANUAL = ['2505.10666', '2505.10667', '2505.10668', '2505.10669', '2505.10672']
MIN_ID, MAX_ID = '2505.10666', '2505.15665'
AUTO_COUNT = 495
AUTO_SOURCE = 'auto_hybrid_seed42'
MAX_BIB_BYTES = 5_000_000
SEED = 42
THRESHOLD = 0.75
MANUAL_FIELDS = ('paper_arxiv_id', 'paper_title', 'citation_key', 'citation_title',
                 'citation_authors', 'citation_year', 'groundtruth_arxiv_id')
AUTO_FIELDS = (*MANUAL_FIELDS, 'best_score', 'method')


def json_text(x):
    return json.dumps(x, ensure_ascii=False, separators=(',', ':'))


def valid_pool(paper):
    try:
        refs = json.loads((paper / 'references.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    if not isinstance(refs, list) or not any(isinstance(x, dict) and x.get('ref_arxiv_id') for x in refs):
        return False
    return not any(f.stat().st_size > MAX_BIB_BYTES for v in paper.glob('v*') if v.is_dir() for f in v.rglob('*.bib'))


def version_dirs(paper):
    return sorted((v for v in paper.iterdir() if v.is_dir() and re.fullmatch(r'v\d+', v.name)), key=lambda v: int(v.name[1:]))


def explicit_ids(entry):
    text = ' '.join(str(entry.get(x) or '') for x in ('title', 'url', 'doi'))
    return set(re.findall(r'(?i)(?:arxiv(?:\.org/(?:abs|pdf)/|[:/ ]+)|10\.48550/arxiv\.)(\d{4}\.\d{4,5})(?:v\d+)?', text))


def cited_keys_and_raw_ids(paper):
    """Collect real cite keys and explicit arXiv IDs across all versions."""
    entries_by_version = {}
    for v in version_dirs(paper):
        entries_by_version[int(v.name[1:])] = parse_version_bibtex(v, paper.name)
    key_map = build_cross_version_citation_map(entries_by_version)
    cited = set()
    raw_ids = collections.defaultdict(set)
    for v in version_dirs(paper):
        num = int(v.name[1:])
        main = find_main_tex(v)
        if main:
            body = BIB_RE.sub(' ', extract_body(expand_inputs(main, main.parent)))
            for match in CITE_RE.finditer(body):
                for raw_key in match.group(2).split(','):
                    raw_key = raw_key.strip()
                    if raw_key:
                        cited.add(key_map.get((num, raw_key), raw_key))
        for bib in sorted(v.rglob('*.bib')):
            content = bib.read_text(encoding='utf-8', errors='ignore')
            matches = list(re.finditer(r'@[a-zA-Z]+\s*\{\s*([^,\s]+)\s*,', content))
            for i, match in enumerate(matches):
                key = key_map.get((num, match.group(1)), match.group(1))
                chunk = content[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(content)]
                for ident in re.findall(r'(?i)\beprint\s*=\s*[\{" ]*\s*(?:arxiv[: ]*)?(\d{4}\.\d{4,5})(?:v\d+)?', chunk):
                    raw_ids[key].add(ident)
                for ident in re.findall(r'(?i)(?:arxiv\.org/(?:abs|pdf)/|arxiv[:/ ]+|10\.48550/arxiv\.)(\d{4}\.\d{4,5})(?:v\d+)?', chunk):
                    raw_ids[key].add(ident)
        # Some papers use inline \bibitem rather than a .bib file.
        if not list(v.rglob('*.bib')):
            for tex in v.rglob('*.tex'):
                content = tex.read_text(encoding='utf-8', errors='ignore')
                matches = list(re.finditer(r'\\bibitem\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}', content))
                for i, match in enumerate(matches):
                    key = key_map.get((num, match.group(1).strip()), match.group(1).strip())
                    chunk = content[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(content)]
                    for ident in re.findall(r'(?i)(?:arxiv\.org/(?:abs|pdf)/|arxiv[:/ ]+)(\d{4}\.\d{4,5})(?:v\d+)?', chunk):
                        raw_ids[key].add(ident)
    return cited, raw_ids


def choose_label(entry, refs, idf, raw_ids):
    pool_ids = {r['ref_arxiv_id'] for r in refs}
    explicit = set(raw_ids) | explicit_ids(entry)
    hits = sorted(explicit & pool_ids)
    ranked = []
    for ref in refs:
        date = str(ref.get('ref_submission_date') or '')
        year = int(date[:4]) if re.match(r'^(?:19|20)\d{2}', date) else None
        score = matcher.compute_hybrid_score(
            entry.get('title') or '', entry.get('authors') or [], entry.get('year'),
            ref.get('ref_title') or '', ref.get('ref_authors') or [], year, idf_dict=idf,
        )
        ranked.append((score, ref['ref_arxiv_id']))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    if hits:
        label = next(rid for _, rid in ranked if rid in hits)
        rule = 'explicit_arxiv_id' if len(hits) == 1 else 'explicit_arxiv_id_multiple_select_best'
    elif ranked and ranked[0][0] >= THRESHOLD:
        label, rule = ranked[0][1], 'hybrid_score_ge_0.75'
    else:
        label, rule = '', 'hybrid_score_lt_0.75'
    return label, rule, round(ranked[0][0], 6) if ranked else ''


def manual_label_rows(review):
    for row in review:
        if row['label_status'] not in ('matched', 'none'):
            continue
        export = {field: row[field] for field in MANUAL_FIELDS}
        export['citation_authors'] = [name.strip() for name in row['citation_authors'].split(';') if name.strip()]
        if row['label_status'] == 'none':
            export['groundtruth_arxiv_id'] = ''
        yield export


def auto_label_row(aid, title, entry, label, score, rule):
    return {
        'paper_arxiv_id': aid,
        'paper_title': title,
        'citation_key': entry['citation_key'],
        'citation_title': entry['title'],
        'citation_authors': entry.get('authors') or [],
        'citation_year': entry['year'],
        'groundtruth_arxiv_id': label,
        'best_score': score,
        'method': 'bib_arxiv_id' if rule.startswith('explicit_arxiv_id') else 'score',
    }


def write_csv(path, fields, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def parse_paper(paper):
    result = process_single_paper(str(paper))
    if result['errors']:
        raise ValueError(result['errors'])
    cited, raw_ids = cited_keys_and_raw_ids(paper)
    refs = {ref['ref_arxiv_id']: ref for ref in result['references'] if ref.get('ref_arxiv_id')}
    entries = {entry['citation_key']: entry for entry in result['bibtex']}
    title = (result['paper_meta'] or {}).get('title', '')
    return cited, raw_ids, refs, entries, title


def label_paper(paper):
    try:
        cited, raw_ids, refs, entries, title = parse_paper(paper)
    except (OSError, ValueError) as error:
        return f'{paper.name}: {error}', None
    if not refs or not any(key in cited and (entry.get('title') or '').strip()
                           for key, entry in entries.items()):
        return 'no_cited_titled_entry_or_reference', None

    idf = bao.build_idf_dict([ref['ref_title'] for ref in refs.values() if ref.get('ref_title')])
    labels, bibtex = [], []
    rules = collections.Counter()
    for key, entry in entries.items():
        label, rule, score = choose_label(entry, refs.values(), idf, raw_ids.get(key, set()))
        assert not label or label in refs
        labels.append(auto_label_row(paper.name, title, entry, label, score, rule))
        rules[rule] += 1
        bibtex.append({**entry, 'authors': json_text(entry.get('authors') or []),
                       'is_cited': str(key in cited).lower(), 'label_source': AUTO_SOURCE})
    info = {'paper_arxiv_id': paper.name, 'label_source': AUTO_SOURCE,
            'merged_bib_entries': len(entries), 'cited_keys': len(cited),
            'retained_entries': len(labels), 'reference_candidates': len(refs)}
    return '', (info, labels, bibtex, rules)


def main():
    with (OUT / 'manual_5_review.csv').open(encoding='utf-8-sig', newline='') as stream:
        manual = list(csv.DictReader(stream))
    assert {row['paper_arxiv_id'] for row in manual} == set(MANUAL)
    by_paper = collections.defaultdict(dict)
    for row in manual:
        labels = by_paper[row['paper_arxiv_id']]
        key = row['citation_key']
        assert key not in labels
        labels[key] = row

    manual_bibtex, manual_papers = [], []
    for aid in MANUAL:
        cited, _, refs, entries, _ = parse_paper(DATA / aid)
        labels = by_paper[aid]
        assert labels.keys() <= entries.keys()
        reviewed = sum(row['label_status'] in ('matched', 'none') for row in labels.values())
        assert reviewed >= 20
        for key, row in labels.items():
            label = row['groundtruth_arxiv_id']
            if row['label_status'] == 'matched':
                assert label in refs
            elif row['label_status'] == 'none':
                assert label in ('', 'none')
            else:
                assert not label
            entry = entries[key]
            manual_bibtex.append({**entry, 'authors': json_text(entry.get('authors') or []),
                                  'is_cited': str(key in cited).lower(), 'label_source': 'manual_review'})
        manual_papers.append({'paper_arxiv_id': aid, 'label_source': 'manual_review',
                              'merged_bib_entries': len(entries), 'cited_keys': len(cited),
                              'retained_entries': len(labels), 'reference_candidates': len(refs)})

    eligible = sorted(p for p in DATA.iterdir() if p.is_dir() and MIN_ID <= p.name <= MAX_ID
                      and p.name not in MANUAL and valid_pool(p))
    random.Random(SEED).shuffle(eligible)
    auto_papers, auto_labels, auto_bibtex = [], [], []
    skipped = collections.Counter()
    auto_rules = collections.Counter()
    with ProcessPoolExecutor(max_workers=6) as pool:
        for start in range(0, len(eligible), 18):
            for reason, result in pool.map(label_paper, eligible[start:start + 18]):
                if result is None:
                    skipped['parse_error' if ': ' in reason else reason] += 1
                    if ': ' in reason:
                        print(reason, flush=True)
                    continue
                info, labels, bibtex, rules = result
                auto_papers.append(info)
                auto_labels.extend(labels)
                auto_bibtex.extend(bibtex)
                auto_rules.update(rules)
                if len(auto_papers) % 50 == 0:
                    print(f'Selected {len(auto_papers)}/{AUTO_COUNT} auto papers', flush=True)
                if len(auto_papers) == AUTO_COUNT:
                    break
            if len(auto_papers) == AUTO_COUNT:
                break

    selected = manual_papers + auto_papers
    assert len(auto_papers) == AUTO_COUNT
    assert len({row['paper_arxiv_id'] for row in selected}) == 5 + AUTO_COUNT
    auto_keys = {(row['paper_arxiv_id'], row['citation_key']) for row in auto_labels}
    assert len(auto_keys) == len(auto_labels) == len(auto_bibtex)
    assert auto_keys == {(row['arxiv_id'], row['citation_key']) for row in auto_bibtex}
    assert len(manual_bibtex) == len(manual)
    outputs = {'manual_5_labels_draft.csv': list(manual_label_rows(manual)),
               'auto_495_labels.csv': auto_labels, 'bibtex_selected_500.csv': manual_bibtex + auto_bibtex,
               'selected_papers.csv': selected}
    label_fields = {'manual_5_labels_draft.csv': MANUAL_FIELDS, 'auto_495_labels.csv': AUTO_FIELDS}
    for name, rows in outputs.items():
        temp = OUT / (name + '.tmp')
        write_csv(temp, label_fields.get(name, tuple(rows[0])), rows)
        with temp.open(encoding='utf-8-sig', newline='') as stream:
            assert sum(1 for _ in csv.DictReader(stream)) == len(rows)
        temp.replace(OUT / name)
    summary = {
        'seed': SEED, 'range': [MIN_ID, MAX_ID], 'max_bib_file_bytes': MAX_BIB_BYTES,
        'eligible_before_parse': len(eligible), 'skipped_after_shuffle': dict(skipped),
        'manual_papers': len(manual_papers), 'manual_entries': len(manual),
        'manual_entries_by_paper': {aid: len(by_paper[aid]) for aid in MANUAL},
        'manual_statuses': dict(collections.Counter(row['label_status'] for row in manual)),
        'manual_human_verified': sum(row['human_verified'].lower() == 'true' for row in manual),
        'auto_papers': len(auto_papers), 'auto_entries': len(auto_labels),
        'auto_cited_entries': sum(row['is_cited'] == 'true' for row in auto_bibtex),
        'auto_statuses': dict(collections.Counter('matched' if row['groundtruth_arxiv_id'] else 'none'
                                                for row in auto_labels)),
        'auto_rules': dict(auto_rules),
        'matcher_branch_commit': '73f06ee8012cad4173e63535082b33ad63498d68',
        'threshold': THRESHOLD,
    }
    (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n',
                                      encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
