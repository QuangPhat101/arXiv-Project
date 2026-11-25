"""Milestone 3 500-Paper Labeling Pipeline.

Implements team agreed rules (Khánh & Bảo):
1. Paper selection:
   - 5 golden hand-labeled papers + 495 auto-labeled papers (seed=42).
   - Filter out papers with .bib > 5MB (e.g. ACL anthology).
   - Filter out papers without any arXiv references.
   - Filter out papers without .tex files.
2. Entry selection:
   - Only keep entries actually cited (\\cite) in the paper across all versions (v1..vN).
   - Drop entries without a title.
   - Synchronize bibtex table and predictions table.
3. Labeling rules:
   - arXiv eprint priority (eprint/url in bibtex matching candidate ref_arxiv_id).
   - Hybrid score: 0.35 raw + 0.35 ngram TF-IDF + 0.20 author + 0.10 year - roman penalty + exact bonus.
   - Threshold 0.75: cand_1 score >= 0.75 -> assigned_label = cand_1, else 'none'.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

# Add repo root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.bibtex_parser import (
    parse_version_bibtex,
    build_cross_version_citation_map,
)
from src.matching import CitationMatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("m3_labeling")

HAND_LABELED_5_PIDS = ["2503.21991", "2503.22575", "2503.23011", "2503.23573", "2504.01018"]
CITE_RE = re.compile(r"\\cite[a-zA-Z]*\*?(?:\[[^\]]*\]){0,2}\{([^}]*)\}")


def select_495_papers(data_dir: Path, seed: int = 42) -> List[str]:
    """Deterministically select 495 papers based on filtering criteria."""
    all_pids = sorted([p.name for p in data_dir.iterdir() if p.is_dir() and p.name.startswith("25")])
    hand_set = set(HAND_LABELED_5_PIDS)

    eligible = []
    for pid in all_pids:
        if pid in hand_set:
            continue

        p_dir = data_dir / pid

        # 1. Reject if any .bib > 5MB
        if any(f.stat().st_size > 5 * 1024 * 1024 for f in p_dir.rglob("*.bib")):
            continue

        # 2. Reject if no arXiv references
        ref_path = p_dir / "references.json"
        if not ref_path.exists():
            continue
        try:
            refs = json.loads(ref_path.read_text(encoding="utf-8"))
            if not any(bool(r.get("ref_arxiv_id")) for r in refs):
                continue
        except Exception:
            continue

        # 3. Reject if no .tex files
        if not list(p_dir.rglob("*.tex")):
            continue

        eligible.append(pid)

    logger.info(f"Total eligible papers found: {len(eligible)} / {len(all_pids)}")
    rng = random.Random(seed)
    sampled = sorted(rng.sample(eligible, 495))
    return sampled


def get_cited_canonical_keys(p_dir: Path, key_map: Dict[Tuple[int, str], str]) -> Set[str]:
    """Scan all .tex files across all versions and extract cited canonical keys."""
    cited = set()
    v_dirs = sorted(
        [v for v in p_dir.iterdir() if v.is_dir() and v.name.startswith("v")],
        key=lambda x: int(x.name[1:]) if x.name[1:].isdigit() else 0,
    )
    for v_dir in v_dirs:
        v_num = int(v_dir.name[1:]) if v_dir.name[1:].isdigit() else 1
        for tex_file in v_dir.glob("*.tex"):
            content = tex_file.read_text(encoding="utf-8", errors="ignore")
            for m in CITE_RE.finditer(content):
                for raw_k in m.group(1).split(","):
                    k = raw_k.strip()
                    if k:
                        canon = key_map.get((v_num, k), k)
                        cited.add(canon)
    return cited


def process_paper_labeling(
    pid: str,
    data_dir: Path,
    matcher: CitationMatcher,
    is_hand_labeled: bool = False,
    hand_labeled_dict: Optional[Dict[str, str]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Process a single paper: parse cited entries, rank, and label."""
    p_dir = data_dir / pid
    ref_path = p_dir / "references.json"
    refs = json.loads(ref_path.read_text(encoding="utf-8")) if ref_path.exists() else []

    v_dirs = sorted(
        [v for v in p_dir.iterdir() if v.is_dir() and v.name.startswith("v")],
        key=lambda x: int(x.name[1:]) if x.name[1:].isdigit() else 0,
    )

    # 1. Parse BibTeX across versions
    entries_by_v = {}
    for v_dir in v_dirs:
        v_num = int(v_dir.name[1:]) if v_dir.name[1:].isdigit() else 1
        entries_by_v[v_num] = parse_version_bibtex(v_dir, pid)

    key_map = build_cross_version_citation_map(entries_by_v)

    # 2. Merge entries across versions
    merged: Dict[str, Dict[str, Any]] = {}
    for v_num, entries in sorted(entries_by_v.items()):
        for e in entries:
            orig_k = e["citation_key"]
            canon_k = key_map.get((v_num, orig_k), orig_k)
            if canon_k not in merged:
                ec = dict(e)
                ec["citation_key"] = canon_k
                merged[canon_k] = ec
            else:
                for k, v in e.items():
                    if k != "citation_key" and v is not None and not merged[canon_k].get(k):
                        merged[canon_k][k] = v

    # 3. Filter to cited entries with non-empty title
    cited_keys = get_cited_canonical_keys(p_dir, key_map)
    filtered_bibtex = [
        e for e in merged.values()
        if (e["citation_key"] in cited_keys or is_hand_labeled) and e.get("title")
    ]

    # 4. Rank and label
    labels = matcher.match_and_label(
        filtered_bibtex,
        refs,
        top_k=5,
        threshold=0.75,
        require_arxiv_id=True,
    )

    pred_records = []
    for entry, l in zip(filtered_bibtex, labels):
        key = entry["citation_key"]
        
        # If hand-labeled ground truth exists, use it
        if is_hand_labeled and hand_labeled_dict and key in hand_labeled_dict:
            gt_id = hand_labeled_dict[key]
        else:
            gt_id = l["assigned_label"]

        pred_records.append({
            "arxiv_id": str(pid),
            "partition": "train",
            "citation_key": str(key),
            "groundtruth_arxiv_id": str(gt_id),
            "cand_1": l.get("cand_1"),
            "cand_2": l.get("cand_2"),
            "cand_3": l.get("cand_3"),
            "cand_4": l.get("cand_4"),
            "cand_5": l.get("cand_5"),
            "score_1": l.get("score_1", 0.0),
        })

    return filtered_bibtex, pred_records


def run_500_labeling_pipeline(
    data_dir: Path,
    export_dir: Path,
    seed: int = 42,
    num_workers: int = 4,
) -> None:
    """Run full 500-paper labeling pipeline."""
    export_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()

    # 1. Load hand-labeled ground truths
    hand_csv = export_dir / "hand_labeled_5_papers_bao.csv"
    hand_gt_map: Dict[str, Dict[str, str]] = {}
    if hand_csv.exists():
        df_hand = pd.read_csv(hand_csv, dtype=str)
        for _, row in df_hand.iterrows():
            pid = str(row["paper_arxiv_id"]).strip()
            ckey = str(row["citation_key"]).strip()
            gt = str(row["groundtruth_arxiv_id"]).strip()
            if pid not in hand_gt_map:
                hand_gt_map[pid] = {}
            hand_gt_map[pid][ckey] = gt

    # 2. Select 495 papers deterministically
    sampled_495 = select_495_papers(data_dir, seed=seed)
    all_500 = HAND_LABELED_5_PIDS + sampled_495
    logger.info(f"Starting labeling for {len(all_500)} papers (5 hand-labeled + {len(sampled_495)} auto)...")

    matcher = CitationMatcher(threshold=0.75)

    all_bibtex: List[Dict[str, Any]] = []
    all_predictions: List[Dict[str, Any]] = []

    hand_stats = {"papers": 0, "entries": 0, "matched": 0, "none": 0}
    auto_stats = {"papers": 0, "entries": 0, "matched": 0, "none": 0}

    for idx, pid in enumerate(all_500, start=1):
        is_hand = (pid in HAND_LABELED_5_PIDS)
        h_dict = hand_gt_map.get(pid) if is_hand else None

        bibs, preds = process_paper_labeling(
            pid=pid,
            data_dir=data_dir,
            matcher=matcher,
            is_hand_labeled=is_hand,
            hand_labeled_dict=h_dict,
        )

        all_bibtex.extend(bibs)
        all_predictions.extend(preds)

        matched_c = sum(1 for p in preds if p["groundtruth_arxiv_id"] != "none")
        none_c = len(preds) - matched_c

        if is_hand:
            hand_stats["papers"] += 1
            hand_stats["entries"] += len(preds)
            hand_stats["matched"] += matched_c
            hand_stats["none"] += none_c
        else:
            auto_stats["papers"] += 1
            auto_stats["entries"] += len(preds)
            auto_stats["matched"] += matched_c
            auto_stats["none"] += none_c

        if idx % 50 == 0 or idx == len(all_500):
            logger.info(f"Progress: [{idx}/{len(all_500)}] papers processed ({len(all_predictions)} total entries)")

    elapsed = time.perf_counter() - t0

    # Convert to DataFrames and Export
    df_bib = pd.DataFrame(all_bibtex)
    df_pred = pd.DataFrame(all_predictions)

    bib_parquet = export_dir / "m3_bibtex_500_papers_bao.parquet"
    pred_parquet = export_dir / "m3_predictions_500_papers_bao.parquet"
    pred_csv = export_dir / "m3_predictions_500_papers_bao.csv"

    df_bib.to_parquet(bib_parquet, index=False)
    df_pred.to_parquet(pred_parquet, index=False)
    df_pred.to_csv(pred_csv, index=False)

    logger.info("=" * 60)
    logger.info("MILESTONE 3 500-PAPER LABELING SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Hand-labeled (5 papers) : {hand_stats['entries']} entries | {hand_stats['matched']} matched | {hand_stats['none']} none")
    logger.info(f"Auto-labeled (495 papers): {auto_stats['entries']} entries | {auto_stats['matched']} matched | {auto_stats['none']} none")
    total_entries = hand_stats["entries"] + auto_stats["entries"]
    total_matched = hand_stats["matched"] + auto_stats["matched"]
    total_none = hand_stats["none"] + auto_stats["none"]
    logger.info(f"TOTAL (500 papers)      : {total_entries} entries | {total_matched} matched | {total_none} none")
    logger.info(f"Total Time Elapsed      : {elapsed:.2f} s ({elapsed / len(all_500):.2f} s/paper)")
    logger.info(f"Saved BibTeX to: {bib_parquet}")
    logger.info(f"Saved Predictions to: {pred_parquet} & {pred_csv}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="M3 500-Paper Labeling Pipeline")
    parser.add_argument("--data-dir", type=Path, default=Path("data"), help="Path to data directory")
    parser.add_argument("--export-dir", type=Path, default=Path("export_bao"), help="Path to export directory")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--workers", type=int, default=4, help="Number of worker processes")
    args = parser.parse_args()

    run_500_labeling_pipeline(
        data_dir=args.data_dir,
        export_dir=args.export_dir,
        seed=args.seed,
        num_workers=args.workers,
    )
