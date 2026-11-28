"""Hand-labeling helper for 5 papers (Khanh).

  python export_khanh/label_review.py build      -> export_khanh/review_khanh.xlsx (open in Excel, check column B)
  python export_khanh/label_review.py finalize   -> export_khanh/hand_labeled_5_papers_khanh.csv (same format as Bao)

Column B `nhan_cuoi` = the arXiv ID you decide is the cited paper, or `none` if no reference matches.
Three tiers by title similarity of the best candidate:
  KHOP       (>= 0.90)  pre-filled with cand_1: glance and fix if wrong
  CHAC_NONE  (<  0.60)  pre-filled with none:  glance and fix if wrong
  CAN_XEM    (between)  left EMPTY: you decide
finalize refuses to run while any `nhan_cuoi` is empty. xlsx avoids Excel's locale-dependent CSV separator.
"""
import csv
import json
import subprocess
import sys
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

HERE = Path(__file__).resolve().parent
PAPERS = ['2503.02783', '2503.03355', '2503.03509', '2503.05695', '2503.06704']
DATA = HERE.parent.parent / 'data'
CANDS = HERE / 'candidates' / 'candidates_all.csv'
REVIEW = HERE / 'review_khanh.xlsx'
FINAL = HERE / 'hand_labeled_5_papers_khanh.csv'
SURE, CLEARLY_NOT = 0.9, 0.6  # title-similarity tier bounds

# Decisions made while reading the low-similarity rows (title changed or truncated between bib and S2).
NOTES = {
    ('2503.02783', 'deepseekai2025deepseekr1incentivizingreasoningcapability'): ('2501.12948', 'Cung bai DeepSeek-R1; S2 dung ten ban Nature'),
    ('2503.06704', 'N3_JanusII'): ('2408.00424', 'Cung tieu de; ten tren S2 bi dinh rac LaTeX'),
    ('2503.06704', '5D_N4_curved_DW'): ('hep-th/0412081', 'Bib bi cat tieu de "N=4 ``Fake"; S2: "N = 4 fake supergravity" (Zagermann 2005)'),
}
COLUMNS = ['trang_thai', 'nhan_cuoi', 'goi_y', 'citation_title', 'cand1_title', 'cand1_arxiv_id', 'cand1_title_sim',
           'cand2_title', 'cand2_arxiv_id', 'cand2_title_sim', 'cand3_title', 'cand3_arxiv_id', 'cand3_title_sim',
           'citation_authors', 'citation_year', 'ly_do', 'paper_arxiv_id', 'citation_key']
WIDTHS = {'trang_thai': 11, 'nhan_cuoi': 15, 'goi_y': 15, 'citation_title': 55, 'cand1_title': 55, 'cand2_title': 40,
          'cand3_title': 40, 'citation_authors': 30, 'ly_do': 30}
FILL = {'CAN_XEM': 'FFF2CC', 'CHAC_NONE': 'F2F2F2', 'KHOP': 'E2F0D9'}
ORDER = {'CAN_XEM': 0, 'CHAC_NONE': 1, 'KHOP': 2}


def tier(r):
    sim = float(r.get('cand1_title_sim') or 0)
    note = NOTES.get((r['paper_arxiv_id'], r['citation_key']))
    if note:
        return 'CAN_XEM', note[0], note[1], ''
    if sim >= SURE:
        return 'KHOP', r['cand1_arxiv_id'], f'tieu de trung {sim:.2f}', r['cand1_arxiv_id']
    if sim < CLEARLY_NOT:
        return 'CHAC_NONE', 'none', f'ung vien tot nhat chi giong {sim:.2f}', 'none'
    return 'CAN_XEM', 'none', f'ung vien tot nhat giong {sim:.2f}: tu quyet', ''


def build():
    if REVIEW.exists():
        sys.exit(f'{REVIEW.name} already exists; delete it first if you really want to start over.')
    if not CANDS.exists():
        subprocess.run([sys.executable, str(HERE / 'label_prep.py'), str(DATA), str(CANDS.parent), ','.join(PAPERS)],
                       check=True, cwd=HERE.parent)
    with open(CANDS, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        status, suggestion, reason, final = tier(r)
        out.append({**{c: r.get(c, '') for c in COLUMNS}, 'trang_thai': status, 'goi_y': suggestion,
                    'ly_do': reason, 'nhan_cuoi': final})
    out.sort(key=lambda r: (r['paper_arxiv_id'], ORDER[r['trang_thai']], r['citation_key']))

    wb = Workbook()
    ws = wb.active
    ws.title = 'gan_nhan'
    ws.append(COLUMNS)
    for r in out:
        ws.append([r[c] for c in COLUMNS])
        for cell in ws[ws.max_row]:
            cell.fill = PatternFill('solid', fgColor=FILL[r['trang_thai']])
            cell.alignment = Alignment(wrap_text=True, vertical='top')
        ws.cell(ws.max_row, 2).font = Font(bold=True, color='C00000')
    for i, c in enumerate(COLUMNS, 1):
        ws.cell(1, i).font = Font(bold=True)
        ws.column_dimensions[ws.cell(1, i).column_letter].width = WIDTHS.get(c, 12)
    ws.freeze_panes = 'C2'
    ws.auto_filter.ref = ws.dimensions
    wb.save(REVIEW)
    counts = {t: sum(r['trang_thai'] == t for r in out) for t in ORDER}
    print(f'{REVIEW.name}: {len(out)} rows {counts}; only CAN_XEM rows are empty')


def finalize():
    ws = load_workbook(REVIEW, read_only=True).active
    it = ws.iter_rows(values_only=True)
    head = list(next(it))
    rows = [{k: ('' if v is None else str(v)) for k, v in zip(head, row)} for row in it if any(row)]
    empty = [f"{r['paper_arxiv_id']} {r['citation_key']}" for r in rows if not r['nhan_cuoi'].strip()]
    if empty:
        sys.exit(f'{len(empty)} rows still have empty nhan_cuoi, e.g. {empty[:5]}')
    titles = {p: json.loads((DATA / p / 'metadata.json').read_text(encoding='utf-8')).get('title', '') for p in PAPERS}
    valid = {p: {x['ref_arxiv_id'] for x in json.loads((DATA / p / 'references.json').read_text(encoding='utf-8'))
                 if x.get('ref_arxiv_id')} for p in PAPERS}
    out, per_paper = [], {}
    for r in rows:
        label = r['nhan_cuoi'].strip()
        gt = '' if label.lower() == 'none' else label
        if gt and gt not in valid[r['paper_arxiv_id']]:
            sys.exit(f"{r['paper_arxiv_id']} {r['citation_key']}: {gt} is not in that paper's references.json")
        per_paper[r['paper_arxiv_id']] = per_paper.get(r['paper_arxiv_id'], 0) + bool(gt)
        out.append({'paper_arxiv_id': r['paper_arxiv_id'], 'paper_title': titles[r['paper_arxiv_id']],
                    'citation_key': r['citation_key'], 'citation_title': r['citation_title'],
                    'citation_authors': r['citation_authors'], 'citation_year': r['citation_year'],
                    'groundtruth_arxiv_id': gt})
    short = {p: n for p, n in per_paper.items() if n < 20}
    if short:
        sys.exit(f'Papers with fewer than 20 arXiv-matched citations: {short}')
    with open(FINAL, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print(f'{FINAL.name}: {len(out)} rows; matched per paper: {per_paper}')


if __name__ == '__main__':
    {'build': build, 'finalize': finalize}[sys.argv[1]]()
