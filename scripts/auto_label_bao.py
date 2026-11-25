"""Automatic citation labelling for Bao's range following Khanh's exact pipeline & rules.

Uses the group's hybrid CitationMatcher (src/matching.py, Bao) and src/parser.py + src/bibtex_parser.py.

Rule:
  - Rank every arXiv reference of the paper with CitationMatcher.compute_hybrid_score.
  - If the raw bib entry states exactly 1 arXiv ID that is in the paper's arXiv references -> assign that ID ('bib_arxiv_id').
  - Otherwise, assign cand_1 if its score >= 0.75, else None ('score').
  - Reference year is taken from ref_submission_date[:4].

Usage:
  python scripts/auto_label_bao.py check       -> accuracy on export_bao/hand_labeled_5_papers_bao.csv
  python scripts/auto_label_bao.py sample 495  -> export_bao/auto_labeled_bao.csv (+ parquet/bibtex tables)
"""
from __future__ import annotations

import csv
import json
import random
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.bibtex_parser import build_cross_version_citation_map, parse_version_bibtex
from src.matching import CitationMatcher, build_idf_dict
from src.parser import CITE_RE, expand_inputs, extract_body, find_main_tex

DATA = PROJECT_ROOT / "data"
EXPORT_DIR = PROJECT_ROOT / "export_bao"
MANUAL = {"2503.21991", "2503.22575", "2503.23011", "2503.23573", "2504.01018"}
OUT_CSV = EXPORT_DIR / "auto_labeled_bao.csv"
THRESHOLD = 0.75
SEED = 42
MATCHER = CitationMatcher()

AID = re.compile(
    r"(?:arxiv[:\s/]*|eprint\s*=\s*[{\"]\s*|abs/)((?:\d{4}\.\d{4,5})|(?:[a-z\-]+(?:\.[A-Z]{2})?/\d{7}))",
    re.I,
)
ENTRY_START = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,")
BIBITEM = re.compile(r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}")


def year(v):
    s = str(v or "")[:4]
    return int(s) if s.isdigit() else None


def cited_keys(vdir: Path) -> set[str]:
    main = find_main_tex(vdir)
    if main is None:
        return set()
    body = extract_body(expand_inputs(main, main.parent))
    return {k.strip() for m in CITE_RE.finditer(body) for k in m.group(2).split(",") if k.strip()}


def raw_entries_of_version(vdir: Path) -> dict[str, str]:
    """citation_key -> raw text of its bib entry / bibitem in one version dir."""
    out: dict[str, str] = {}
    for f in [*vdir.rglob("*.bib"), *vdir.rglob("*.bbl"), *vdir.rglob("*.tex")]:
        t = f.read_text(encoding="utf-8", errors="ignore")
        for m in ENTRY_START.finditer(t):
            depth, i = 0, t.index("{", m.start())
            for j in range(i, min(len(t), i + 20000)):
                depth += {"{": 1, "}": -1}.get(t[j], 0)
                if depth == 0:
                    out.setdefault(m.group(1), t[m.start() : j + 1])
                    break
        items = list(BIBITEM.finditer(t))
        for a, b in zip(items, items[1:] + [None]):
            end = b.start() if b else (t.find(r"\end{thebibliography}", a.end()) % (len(t) + 1) or len(t))
            out.setdefault(a.group(1), t[a.end() : end])
    return out


def load_paper(paper: Path):
    """Return (title, arXiv refs, cited bib entries merged over ALL versions) or None."""
    versions = sorted((v for v in paper.glob("v*") if v.name[1:].isdigit()), key=lambda v: int(v.name[1:]))
    if not versions or not (paper / "references.json").exists():
        return None
    if any(f.stat().st_size > 5_000_000 for v in versions for f in v.rglob("*.bib")):
        return None
    refs = [r for r in json.loads((paper / "references.json").read_text(encoding="utf-8")) if r.get("ref_arxiv_id")]
    by_version, raw = {}, {}
    for v in versions:
        n = int(v.name[1:])
        keys = cited_keys(v)
        by_version[n] = [e for e in parse_version_bibtex(v, paper.name) if e["citation_key"] in keys and e.get("title")]
        raw[n] = raw_entries_of_version(v)
    if not refs or not any(by_version.values()):
        return None
    canon = build_cross_version_citation_map(by_version)
    merged = {}
    for n in sorted(by_version, reverse=True):  # newest version first: its title/authors win
        for e in by_version[n]:
            key = canon.get((n, e["citation_key"]), e["citation_key"])
            m = merged.setdefault(key, {**e, "citation_key": key, "bib_ids": set()})
            m["bib_ids"] |= {re.sub(r"v\d+$", "", x) for x in AID.findall(raw[n].get(e["citation_key"], ""))}
    title = json.loads((paper / "metadata.json").read_text(encoding="utf-8")).get("title", "")
    return title, refs, list(merged.values())


def ranked(entry, refs, idf):
    scored = [
        (
            MATCHER.compute_hybrid_score(
                entry.get("title", ""),
                entry.get("authors") or [],
                year(entry.get("year")),
                r.get("ref_title", ""),
                r.get("ref_authors") or [],
                year(r.get("ref_submission_date")),
                idf,
            ),
            r["ref_arxiv_id"],
        )
        for r in refs
    ]
    return sorted(scored, reverse=True)


def label_paper(refs, entries):
    """Yield (entry, label, best_score, method, top5_ids)."""
    idf = build_idf_dict([r.get("ref_title", "") for r in refs])
    ref_ids = {r["ref_arxiv_id"] for r in refs}
    for e in entries:
        rk = ranked(e, refs, idf)
        best_score, best_id = rk[0]
        top5 = [cand_id for _, cand_id in rk[:5]]
        while len(top5) < 5:
            top5.append(None)
        stated = sorted(e.get("bib_ids", set()) & ref_ids)
        if len(stated) == 1:
            yield e, stated[0], best_score, "bib_arxiv_id", top5
        else:
            yield e, (best_id if best_score >= THRESHOLD else None), best_score, "score", top5


def check():
    hand = EXPORT_DIR / "hand_labeled_5_papers_bao.csv"
    with open(hand, encoding="utf-8-sig") as f:
        gold = {(r["paper_arxiv_id"], r["citation_key"]): r["groundtruth_arxiv_id"] or None for r in csv.DictReader(f)}
    hit = total = 0
    for pid in sorted(MANUAL):
        loaded = load_paper(DATA / pid)
        if loaded is None:
            continue
        _, refs, entries = loaded
        for e, label, score, method, _ in label_paper(refs, entries):
            key = (pid, e["citation_key"])
            if key in gold:
                total += 1
                hit += label == gold[key]
                if label != gold[key]:
                    print(f"  auto {label} vs hand {gold[key]} | score {score:.2f} ({method}) | {pid} {e['citation_key']}")
    print(f"accuracy on hand labels: {hit}/{total} = {hit / total:.1%}")


def _process_one_paper(paper_str: str):
    """Worker helper: load and label one paper, returning rows or None."""
    p = Path(paper_str)
    loaded = load_paper(p)
    if loaded is None:
        return None
    title, refs, entries = loaded
    out_rows, pred_rows, bib_rows = [], [], []
    for e, label, score, method, top5 in label_paper(refs, entries):
        out_rows.append(
            {
                "paper_arxiv_id": p.name,
                "paper_title": title,
                "citation_key": e["citation_key"],
                "citation_title": e.get("title"),
                "citation_authors": e.get("authors"),
                "citation_year": e.get("year"),
                "groundtruth_arxiv_id": label or "",
                "best_score": round(score, 4),
                "method": method,
            }
        )
        pred_rows.append(
            {
                "arxiv_id": p.name,
                "partition": "train",
                "citation_key": e["citation_key"],
                "groundtruth_arxiv_id": label or "none",
                "cand_1": top5[0],
                "cand_2": top5[1],
                "cand_3": top5[2],
                "cand_4": top5[3],
                "cand_5": top5[4],
                "score_1": round(score, 4),
                "method": method,
            }
        )
        bib_rows.append({k: v for k, v in e.items() if k != "bib_ids"})
    return out_rows, pred_rows, bib_rows


def sample(n: int):
    t0 = time.perf_counter()
    papers = [p for p in sorted(DATA.glob("25*")) if p.name not in MANUAL]
    random.Random(SEED).shuffle(papers)
    out, pred_rows, bib_rows = [], [], []
    used = 0
    batch_size = 64
    with ProcessPoolExecutor(max_workers=4) as ex:
        for i in range(0, len(papers), batch_size):
            if used >= n:
                break
            batch = [str(p) for p in papers[i : i + batch_size]]
            for res in ex.map(_process_one_paper, batch):
                if res is None:
                    continue
                o_r, p_r, b_r = res
                out.extend(o_r)
                pred_rows.extend(p_r)
                bib_rows.extend(b_r)
                used += 1
                if used % 50 == 0 or used == n:
                    print(f"Progress: [{used}/{n}] papers processed ({len(out)} entries)...", flush=True)
                if used == n:
                    break

    if used < n:
        sys.exit(f"only {used} labelable papers found, asked for {n}")

    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)

    pd.DataFrame(pred_rows).to_parquet(EXPORT_DIR / "predictions_495_auto_bao.parquet", index=False)
    pd.DataFrame(bib_rows).to_parquet(EXPORT_DIR / "bibtex_495_auto_bao.parquet", index=False)

    matched = sum(bool(r["groundtruth_arxiv_id"]) for r in out)
    by_id = sum(r["method"] == "bib_arxiv_id" for r in out)
    elapsed = time.perf_counter() - t0
    print(
        f"{OUT_CSV.name}: {used} papers, {len(out)} entries, {matched} matched ({by_id} via arXiv id in bib), "
        f"{len(out) - matched} none | {elapsed:.1f}s"
    )


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "sample":
        sample(int(sys.argv[2]))
    elif cmd == "check":
        check()
    else:
        sys.exit(f"Unknown command: {cmd}")
