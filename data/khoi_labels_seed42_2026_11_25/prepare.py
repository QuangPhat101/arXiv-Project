"""Rebuild Khoi's seed-42 citation labels without modifying repository source."""

from __future__ import annotations

import collections
import csv
import importlib.util
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
sys.path.insert(0, str(ROOT))
from src.bibtex_parser import build_cross_version_citation_map, parse_version_bibtex
from src.parser import BIB_RE, CITE_RE, expand_inputs, extract_body, find_main_tex
from src.run_m2_pipeline import process_single_paper

spec = importlib.util.spec_from_file_location('matching_bao_snapshot', OUT / 'matching_bao_snapshot.py')
bao = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bao)
matcher = bao.CitationMatcher()
MANUAL = ['2506.05796', '2506.05802', '2506.05806', '2506.05810', '2506.05843']
MIN_ID, MAX_ID = '2506.05788', '2506.10787'
MAX_BIB_BYTES = 5_000_000
SEED = 42
THRESHOLD = 0.75


def json_text(x):
    return json.dumps(x, ensure_ascii=False, separators=(',', ':'))


def valid_pool(paper):
    try:
        refs = json.loads((paper / 'references.json').read_text())
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
        status, rule = 'matched', 'explicit_arxiv_id' if len(hits) == 1 else 'explicit_arxiv_id_multiple_select_best'
    elif ranked and ranked[0][0] >= THRESHOLD:
        status, label, rule = 'matched', ranked[0][1], 'hybrid_score_ge_0.75'
    else:
        status, label, rule = 'none', '', 'hybrid_score_lt_0.75'
    return status, label, rule, ranked[:5], sorted(explicit)


def write_csv(path, fields, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main():
    old = DATA / 'khoi_labels_handoff_2026_11_25' / 'manual_5_agent_proposals_REVIEW.csv'
    with old.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        manual_fields = reader.fieldnames
        manual_rows = list(reader)
    assert len(manual_rows) == 211 and {r['paper_arxiv_id'] for r in manual_rows} == set(MANUAL)
    for r in manual_rows:
        r['human_verified'] = 'true'
        r['label_source'] = 'human_approved_manual'
    write_csv(OUT / 'manual_5_approved.csv', manual_fields, manual_rows)

    eligible = sorted(p for p in DATA.iterdir() if p.is_dir() and MIN_ID <= p.name <= MAX_ID and p.name not in MANUAL and valid_pool(p))
    random.Random(SEED).shuffle(eligible)
    chosen = []
    auto_rows = []
    bib_rows = []
    manifest = []
    skipped = collections.Counter()
    label_counts = collections.Counter()
    for paper in eligible:
        if len(chosen) == 495:
            break
        try:
            res = process_single_paper(str(paper))
            if res['errors']:
                skipped['m2_errors'] += 1
                continue
            cited, raw_ids = cited_keys_and_raw_ids(paper)
        except Exception:
            skipped['parse_exception'] += 1
            continue
        entries = [e for e in res['bibtex'] if e['citation_key'] in cited and (e.get('title') or '').strip()]
        if not entries:
            skipped['no_cited_titled_entry'] += 1
            continue
        refs = [r for r in res['references'] if r.get('ref_arxiv_id')]
        if not refs:
            skipped['no_normalized_refs'] += 1
            continue
        ref_ids = {r['ref_arxiv_id'] for r in refs}
        idf = bao.build_idf_dict([r.get('ref_title') or '' for r in refs if r.get('ref_title')])
        chosen.append(paper.name)
        manifest.append({'paper_arxiv_id': paper.name, 'label_source': 'auto_hybrid_seed42',
                         'merged_bib_entries': len(res['bibtex']), 'cited_keys': len(cited),
                         'retained_entries': len(entries), 'reference_candidates': len(refs)})
        for e in entries:
            status, label, rule, top5, explicit = choose_label(e, refs, idf, raw_ids.get(e['citation_key'], set()))
            assert not label or label in ref_ids
            auto_rows.append({
                'paper_arxiv_id': paper.name, 'citation_key': e['citation_key'],
                'groundtruth_arxiv_id': label, 'label_source': 'auto_hybrid_seed42',
                'label_status': status, 'human_verified': 'false', 'match_rule': rule,
                'best_score': round(top5[0][0], 6) if top5 else '',
                'explicit_arxiv_ids': json_text(explicit),
                'top5_candidates_json': json_text([{'ref_arxiv_id': rid, 'score': round(score, 6)} for score, rid in top5]),
            })
            bib_rows.append({**e, 'authors': json_text(e.get('authors') or []), 'is_cited': 'true'})
            label_counts[status] += 1
        if len(chosen) % 50 == 0:
            print('selected', len(chosen), 'auto papers;', len(auto_rows), 'entries', flush=True)
    assert len(chosen) == 495
    assert len({(r['paper_arxiv_id'], r['citation_key']) for r in auto_rows}) == len(auto_rows)
    assert len({(r['arxiv_id'], r['citation_key']) for r in bib_rows}) == len(bib_rows) == len(auto_rows)
    assert {(r['paper_arxiv_id'], r['citation_key']) for r in auto_rows} == {(r['arxiv_id'], r['citation_key']) for r in bib_rows}
    assert not set(chosen) & set(MANUAL)
    assert all(MIN_ID <= aid <= MAX_ID for aid in chosen)
    write_csv(OUT / 'auto_495_labels.csv', list(auto_rows[0]), auto_rows)
    write_csv(OUT / 'bibtex_auto_495_cited.csv', list(bib_rows[0]), bib_rows)
    manual_bib_rows = []
    for aid in MANUAL:
        cited, _ = cited_keys_and_raw_ids(DATA / aid)
        for e in process_single_paper(str(DATA / aid))['bibtex']:
            manual_bib_rows.append({**e, 'authors': json_text(e.get('authors') or []),
                                    'is_cited': str(e['citation_key'] in cited).lower(),
                                    'label_source': 'human_approved_manual'})
    assert len(manual_bib_rows) == len(manual_rows)
    assert {(r['arxiv_id'], r['citation_key']) for r in manual_bib_rows} == {(r['paper_arxiv_id'], r['citation_key']) for r in manual_rows}
    combined_bib_rows = manual_bib_rows + [{**r, 'label_source': 'auto_hybrid_seed42'} for r in bib_rows]
    write_csv(OUT / 'bibtex_selected_500.csv', list(combined_bib_rows[0]), combined_bib_rows)
    write_csv(OUT / 'selected_papers.csv', list(manifest[0]),
              [{'paper_arxiv_id': aid, 'label_source': 'human_approved_manual', 'merged_bib_entries': '',
                'cited_keys': '', 'retained_entries': sum(r['paper_arxiv_id'] == aid for r in manual_rows),
                'reference_candidates': ''} for aid in MANUAL] + manifest)
    # Read back every output and check row/key alignment.
    for name, expected in [('manual_5_approved.csv', len(manual_rows)), ('auto_495_labels.csv', len(auto_rows)),
                           ('bibtex_auto_495_cited.csv', len(bib_rows)), ('bibtex_selected_500.csv', len(combined_bib_rows)),
                           ('selected_papers.csv', 500)]:
        with (OUT / name).open(encoding='utf-8-sig', newline='') as f:
            assert sum(1 for _ in csv.DictReader(f)) == expected
    summary = {
        'seed': SEED, 'selection': 'sorted eligible IDs then random.Random(42).shuffle; take first 495 with cited titled entries and no M2 errors',
        'range': [MIN_ID, MAX_ID], 'max_bib_file_bytes': MAX_BIB_BYTES,
        'eligible_before_parse': len(eligible), 'skipped_after_shuffle': dict(skipped),
        'manual_papers': 5, 'manual_entries': len(manual_rows),
        'manual_statuses': dict(collections.Counter(r['label_status'] for r in manual_rows)),
        'manual_entries_without_detected_cite': sum(r['is_cited'] == 'false' for r in manual_bib_rows),
        'auto_papers': 495, 'auto_entries': len(auto_rows), 'auto_statuses': dict(label_counts),
        'auto_rules': dict(collections.Counter(r['match_rule'] for r in auto_rows)),
        'matcher_branch_commit': '73f06ee8012cad4173e63535082b33ad63498d68',
        'threshold': THRESHOLD,
        'rules': 'Explicit arXiv ID from eprint/arXiv URL/prefix in same-paper pool wins; when multiple explicit IDs hit pool, select highest Bao hybrid score among those IDs; otherwise highest Bao hybrid score >=0.75; below threshold none. Reference year from ref_submission_date[:4].',
        'manual_legacy_note': 'Previously approved 211 manual entries retained verbatim except verification/source flags; some are uncited under the new source scan, so bibtex_auto_495_cited.csv covers only auto papers.',
    }
    (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    (OUT / 'README.md').write_text(
        '# Khôi — nhãn seed 42\n\n'
        '`manual_5_approved.csv`: giữ 211 quyết định Khôi đã duyệt từ bộ cũ; chỉ đổi `human_verified=true` và nguồn. '
        '`auto_495_labels.csv`: 495 bài chọn ngẫu nhiên seed 42, mọi BibTeX entry có tiêu đề được `\\cite` trong bất kỳ version nào; '
        '`bibtex_auto_495_cited.csv`: bảng BibTeX lọc khớp từng khóa với nhãn auto. '
        '`bibtex_selected_500.csv`: bảng BibTeX khớp khóa với toàn bộ nhãn 5 + 495 bài, có cờ `is_cited`. '
        '`selected_papers.csv`: danh sách 5 + 495; `summary.json`: thống kê và cấu hình.\n\n'
        'Matcher dùng snapshot nguyên bản từ `origin/feat/m3-hybrid-citation-matching-bao` commit `73f06ee`; '
        'năm reference lấy từ `ref_submission_date[:4]`. ID arXiv ghi rõ trong `.bib` hoặc URL và thuộc reference pool '
        'được ưu tiên; còn lại chọn ứng viên điểm hybrid cao nhất nếu >=0,75, ngược lại `none`. '
        'Mỗi entry chỉ xét references của bài chứa nó. File `.bib` >5.000.000 byte và bài không có reference arXiv bị loại.\n\n'
        'Lưu ý: phần manual được giữ theo quyết định Khôi, kể cả các entry không thấy `\\cite` trong lần quét source mới. '
        'Các dòng manual `unresolved` cũng được giữ nguyên; đó chưa phải ground truth có ID/none cho mô hình. '
        'Không có model, MRR hay predictions trong bộ này. Chạy lại bằng `python prepare.py` từ repo root.\n'
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
