"""Unified dataset preparation pipeline for Milestone 3 citation matching.

Standardizes all four member handoffs (Phat, Khoi, Bao, Khanh) into an identical
per-member Parquet layout under data/members/<member>/ (labels.parquet,
bibtex.parquet, references.parquet), then merges them into one canonical
training dataset (labels.parquet, references.parquet, partitions.csv, summary.json).

Usage:
    python src/prepare_dataset.py
    python src/prepare_dataset.py --output-dir kaggle_dataset --sync-dir data/group_training_seed42
"""

from __future__ import annotations

import argparse
import ast
import csv
import io
import json
import random
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SEED = 42
GROUP_AUTO_TARGET = 1_998
SCHEMA_VERSION = 2

PHAT_DIR = ROOT / "data/phat_labels_seed42_2026_11_26"
KHOI_DIR = ROOT / "parquet_khoi/khoi_model_training_handoff_CONFIRMED"
BAO_DIR = ROOT / "parquet_bao/bao_label_handoff"

MEMBER_SOURCES: Dict[str, Dict[str, Any]] = {
    "phat": {
        "git_ref": None,
        "manual_csv": PHAT_DIR / "manual_5_review.csv",
        "auto_csv": PHAT_DIR / "auto_495_labels.csv",
        "extra_auto_csv": PHAT_DIR / "auto_extra_labels.csv",
        "bibtex_sources": [PHAT_DIR / "bibtex_selected_500.csv", PHAT_DIR / "bibtex_extra.csv"],
        "ref_parquets": [],
        "ref_json_dirs": [ROOT / "data/data", ROOT / "data"],
    },
    "khoi": {
        "git_ref": "origin/feat/khoi-seed42-label-handoff",
        "manual_csv": (
            KHOI_DIR / "manual_5_reviewed.csv"
            if (KHOI_DIR / "manual_5_reviewed.csv").is_file()
            else "data/khoi_labels_seed42_2026_11_25/manual_5_approved.csv"
        ),
        "auto_csv": (
            KHOI_DIR / "auto_495_labels.csv"
            if (KHOI_DIR / "auto_495_labels.csv").is_file()
            else "data/khoi_labels_seed42_2026_11_25/auto_495_labels.csv"
        ),
        "bibtex_sources": [
            KHOI_DIR / "bibtex_selected_500.csv",
            ("origin/feat/khoi-seed42-label-handoff", "data/khoi_labels_seed42_2026_11_25/bibtex_selected_500.csv"),
        ],
        "ref_parquets": [],
        "ref_json_dirs": [KHOI_DIR / "references_json"],
    },
    "bao": {
        "manual_finalized": True,
        "git_ref": "origin/feat/m3-hybrid-citation-matching-bao",
        "manual_csv": (
            BAO_DIR / "hand_labeled_5_papers_bao.csv"
            if (BAO_DIR / "hand_labeled_5_papers_bao.csv").is_file()
            else "export_bao/hand_labeled_5_papers_bao.csv"
        ),
        "auto_csv": (
            BAO_DIR / "auto_labeled_bao.csv"
            if (BAO_DIR / "auto_labeled_bao.csv").is_file()
            else "export_bao/auto_labeled_bao.csv"
        ),
        "bibtex_sources": [BAO_DIR / "bibtex_500_bao.parquet", BAO_DIR / "bibtex_selected_500.csv"],
        "ref_parquets": [BAO_DIR / "references_500_bao.parquet"],
        "ref_json_dirs": [BAO_DIR / "references_json"],
    },
    "khanh": {
        "manual_finalized": True,
        "git_ref": "origin/labels/khanh-auto-labeling",
        "manual_csv": "export_khanh/hand_labeled_5_papers_khanh.csv",
        "auto_csv": "export_khanh/auto_labeled_khanh.csv",
        "bibtex_sources": [ROOT / "parquet_Khanh/bibtex_khanh_500.parquet"],
        "ref_parquets": [ROOT / "parquet_Khanh/references_khanh_500.parquet"],
        "ref_json_dirs": [],
    },
}

LABEL_COLUMNS = [
    "paper_arxiv_id",
    "citation_key",
    "groundtruth_arxiv_id",
    "label_status",
    "usable_label",
    "label_kind",
]
BIBTEX_COLUMNS = [
    "arxiv_id",
    "citation_key",
    "title",
    "authors",
    "year",
    "entry_type",
    "doi",
    "journal",
    "url",
    "is_cited",
]
REF_COLUMNS = [
    "arxiv_id",
    "ref_arxiv_id",
    "ref_title",
    "ref_authors",
    "ref_submission_date",
    "ref_s2_id",
]


def read_csv_source(git_ref: Optional[str], path: Path | str) -> List[Dict[str, str]]:
    """Read CSV from local path if present, otherwise from a git branch/commit."""
    local_path = path if isinstance(path, Path) else ROOT / path
    if local_path.is_file():
        raw = local_path.read_bytes()
    elif git_ref:
        raw = subprocess.check_output(["git", "show", f"{git_ref}:{path}"], cwd=ROOT)
    else:
        raise FileNotFoundError(f"CSV source not found: {path}")
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline="")))


def parse_authors(raw: Any) -> List[str]:
    """Normalize author lists from ndarray, list, JSON, Python literal, or semicolon text."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return []
    if hasattr(raw, "tolist"):
        raw = raw.tolist()
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    text = str(raw).strip()
    if not text or text.lower() in ("nan", "none", "[]"):
        return []
    if text.startswith("[") and text.endswith("]"):
        for loader in (json.loads, ast.literal_eval):
            try:
                parsed = loader(text)
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                pass
        quoted = re.findall(r"['\"]([^'\"]+)['\"]", text)
        if quoted:
            return [q.strip() for q in quoted if q.strip()]
    if ";" in text:
        return [p.strip() for p in text.split(";") if p.strip()]
    return [text]


def parse_year(raw: Any) -> Optional[int]:
    """Parse valid 4-digit publication year."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    text = str(raw).strip()
    if not text or text.lower() in ("nan", "none"):
        return None
    match = re.match(r"^((?:19|20)\d{2})(?:\.0+)?$", text)
    if match:
        return int(match.group(1))
    try:
        val = float(text)
        if val.is_integer() and 1800 <= val <= 2100:
            return int(val)
    except ValueError:
        pass
    return None


def _clean_str(val: Any) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    text = str(val).strip()
    return "" if text.lower() in ("nan", "none") else text


def _standardize_member_labels(member: str, cfg: Dict[str, Any]) -> Tuple[pd.DataFrame, set[str]]:
    rows: List[Dict[str, Any]] = []
    member_papers: set[str] = set()
    seen = set()
    sources = [("manual", cfg["manual_csv"], 5), ("auto", cfg["auto_csv"], 495)]
    extra = cfg.get("extra_auto_csv")
    if extra is not None and extra.is_file():
        sources.append(("auto", extra, GROUP_AUTO_TARGET - 4 * 495))
    for kind, source, expected in sources:
        raw_rows = read_csv_source(cfg["git_ref"], source)
        papers = {r["paper_arxiv_id"].strip() for r in raw_rows}
        if len(papers) != expected or member_papers & papers or "" in papers:
            raise ValueError(f"{member}/{source}: expected {expected} distinct new papers, got {len(papers)}")
        member_papers.update(papers)
        for r in raw_rows:
            aid, key = r["paper_arxiv_id"].strip(), r["citation_key"].strip()
            if not key or (aid, key) in seen:
                raise ValueError(f"{member}/{source}: invalid or duplicate citation key {aid}/{key}")
            seen.add((aid, key))
            gt = _clean_str(r.get("groundtruth_arxiv_id"))
            status = _clean_str(r.get("label_status")).lower() or ("matched" if gt else "none")
            if status == "no_match":
                status = "none"
            if status not in ("matched", "none", "unresolved", "needs_review"):
                raise ValueError(f"{member}/{aid}/{key}: unexpected label status {status!r}")
            external = _clean_str(r.get("external_arxiv_id"))
            if kind == "manual" and status == "none" and external:
                gt, status = external, "matched"
            if status == "matched" and not gt:
                raise ValueError(f"{member}/{aid}/{key}: matched label requires an arXiv ID")
            if status == "none" and gt:
                raise ValueError(f"{member}/{aid}/{key}: no-match label has an arXiv ID")
            verified = _clean_str(r.get("human_verified")).lower() == "true"
            if "human_verified" not in r:
                verified = cfg.get("manual_finalized", False)
            usable = status in ("matched", "none") and (kind == "auto" or verified)
            rows.append({
                "paper_arxiv_id": aid,
                "citation_key": key,
                "groundtruth_arxiv_id": gt if status == "matched" else "",
                "label_status": status,
                "usable_label": bool(usable),
                "label_kind": kind,
            })
    return pd.DataFrame(rows, columns=LABEL_COLUMNS), member_papers


def _standardize_member_bibtex(cfg: Dict[str, Any], member_papers: set[str]) -> pd.DataFrame:
    records: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for src in cfg["bibtex_sources"]:
        if isinstance(src, tuple):
            git_ref, path_str = src
            raw_rows = read_csv_source(git_ref, path_str)
        elif isinstance(src, Path) and src.is_file() and src.suffix == ".parquet":
            raw_rows = pd.read_parquet(src).to_dict(orient="records")
        elif isinstance(src, Path) and src.is_file() and src.suffix == ".csv":
            raw_rows = read_csv_source(None, src)
        else:
            continue

        for r in raw_rows:
            aid = _clean_str(r.get("arxiv_id"))
            ckey = _clean_str(r.get("citation_key"))
            if not aid or not ckey or aid not in member_papers:
                continue
            key = (aid, ckey)
            if key in records:
                continue
            records[key] = {
                "arxiv_id": aid,
                "citation_key": ckey,
                "title": _clean_str(r.get("title")),
                "authors": parse_authors(r.get("authors")),
                "year": parse_year(r.get("year")),
                "entry_type": _clean_str(r.get("entry_type")),
                "doi": _clean_str(r.get("doi")),
                "journal": _clean_str(r.get("journal")),
                "url": _clean_str(r.get("url")),
                "is_cited": {"true": True, "false": False}.get(_clean_str(r.get("is_cited")).lower()),
            }

    df = pd.DataFrame(list(records.values()), columns=BIBTEX_COLUMNS)
    if not df.empty:
        df["year"] = df["year"].astype("Int64")
    else:
        df["year"] = pd.Series(dtype="Int64")
    return df


def _standardize_member_references(cfg: Dict[str, Any], member_papers: set[str]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str]] = set()
    covered: set[str] = set()

    for pq_path in cfg["ref_parquets"]:
        if not pq_path.is_file():
            continue
        for r in pd.read_parquet(pq_path).to_dict(orient="records"):
            aid = _clean_str(r.get("arxiv_id"))
            ref_aid = _clean_str(r.get("ref_arxiv_id"))
            if not aid or aid not in member_papers or not ref_aid:
                continue
            key = (aid, ref_aid)
            if key in seen:
                continue
            seen.add(key)
            covered.add(aid)
            rows.append({
                "arxiv_id": aid,
                "ref_arxiv_id": ref_aid,
                "ref_title": _clean_str(r.get("ref_title")),
                "ref_authors": parse_authors(r.get("ref_authors")),
                "ref_submission_date": _clean_str(r.get("ref_submission_date")),
                "ref_s2_id": _clean_str(r.get("ref_s2_id")),
            })

    for aid in sorted(member_papers - covered):
        ref_file = None
        for base in cfg["ref_json_dirs"]:
            cand = base / aid / "references.json"
            if cand.is_file():
                ref_file = cand
                break
        if not ref_file:
            continue
        raw_refs = json.loads(ref_file.read_text(encoding="utf-8"))
        if not isinstance(raw_refs, list):
            raise ValueError(f"Expected a list of references in {ref_file}")
        for r in raw_refs:
            if not isinstance(r, dict):
                continue
            ref_aid = _clean_str(r.get("ref_arxiv_id"))
            if not ref_aid:
                continue
            key = (aid, ref_aid)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "arxiv_id": aid,
                "ref_arxiv_id": ref_aid,
                "ref_title": _clean_str(r.get("ref_title")),
                "ref_authors": parse_authors(r.get("ref_authors")),
                "ref_submission_date": _clean_str(r.get("ref_submission_date")),
                "ref_s2_id": _clean_str(r.get("ref_s2_id")),
            })

    return pd.DataFrame(rows, columns=REF_COLUMNS)


def standardize_all_members(members_dir: Path) -> None:
    """Export uniform {labels,bibtex,references}.parquet for every member."""
    for member, cfg in MEMBER_SOURCES.items():
        out_dir = members_dir / member
        out_dir.mkdir(parents=True, exist_ok=True)
        labels_df, papers = _standardize_member_labels(member, cfg)
        bibtex_df = _standardize_member_bibtex(cfg, papers)
        refs_df = _standardize_member_references(cfg, papers)
        missing = papers - set(refs_df["arxiv_id"])
        if missing:
            raise ValueError(f"{member}: {len(missing)} papers lack candidate references, including {sorted(missing)[:5]}")

        labels_df.to_parquet(out_dir / "labels.parquet", index=False)
        bibtex_df.to_parquet(out_dir / "bibtex.parquet", index=False)
        refs_df.to_parquet(out_dir / "references.parquet", index=False)


def build_unified_dataset(
    members_dir: Path,
    output_dir: Path,
    sync_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Merge standardized member tables into one canonical training dataset."""
    output_dir.mkdir(parents=True, exist_ok=True)

    all_labels: List[Dict[str, Any]] = []
    all_refs: List[pd.DataFrame] = []
    partitions: Dict[str, Dict[str, Any]] = {}
    bibtex_lookup: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for member in MEMBER_SOURCES:
        m_dir = members_dir / member
        lbl_df = pd.read_parquet(m_dir / "labels.parquet")
        bib_df = pd.read_parquet(m_dir / "bibtex.parquet")
        ref_df = pd.read_parquet(m_dir / "references.parquet")

        if not ref_df.empty:
            all_refs.append(ref_df)
        available_refs = set(ref_df["arxiv_id"].unique()) if not ref_df.empty else set()

        for rec in bib_df.to_dict(orient="records"):
            bibtex_lookup[(rec["arxiv_id"], rec["citation_key"])] = {
                "title": _clean_str(rec.get("title")),
                "authors": parse_authors(rec.get("authors")),
                "year": parse_year(rec.get("year")),
                "is_cited": rec.get("is_cited"),
            }

        for kind in ("manual", "auto"):
            sub = lbl_df[lbl_df["label_kind"] == kind]
            papers = sorted(sub["paper_arxiv_id"].unique())
            if partitions.keys() & set(papers):
                raise ValueError(f"Overlapping papers in {member}/{kind}")
            random.Random(SEED).shuffle(papers)
            for idx, aid in enumerate(papers):
                partitions[aid] = {
                    "paper_arxiv_id": aid,
                    "member": member,
                    "label_kind": kind,
                    "partition": "train" if kind == "auto" else ("valid" if idx < 2 else "test"),
                    "references_available": aid in available_refs,
                }

        for rec in lbl_df.to_dict(orient="records"):
            rec["member"] = member
            rec["partition"] = partitions[rec["paper_arxiv_id"]]["partition"]
            rec["references_available"] = rec["paper_arxiv_id"] in available_refs
            all_labels.append(rec)

    auto_papers = sum(record["label_kind"] == "auto" for record in partitions.values())
    if auto_papers != GROUP_AUTO_TARGET:
        raise ValueError(
            f"Expected {GROUP_AUTO_TARGET} automatic papers, got {auto_papers}. "
            "Generate the supplemental Phat labels as described in README.md."
        )

    refs_merged = pd.concat(all_refs, ignore_index=True) if all_refs else pd.DataFrame(columns=REF_COLUMNS)
    ref_pair_set = set(zip(refs_merged["arxiv_id"], refs_merged["ref_arxiv_id"])) if not refs_merged.empty else set()

    resolution_counts = {"m2_bibtex": 0, "missing": 0}
    final_labels: List[Dict[str, Any]] = []
    for item in all_labels:
        aid = item["paper_arxiv_id"]
        ckey = item["citation_key"]
        bib = bibtex_lookup.get((aid, ckey))
        if bib and bib["title"]:
            title = bib["title"]
            authors = bib["authors"]
            year = bib["year"]
            src = "m2_bibtex"
        else:
            title, authors, year = "", [], None
            src = "missing"
        resolution_counts[src] += 1

        gt = _clean_str(item.get("groundtruth_arxiv_id"))
        has_refs = bool(item["references_available"])
        final_labels.append({
            "paper_arxiv_id": aid,
            "citation_key": ckey,
            "citation_title": title,
            "citation_authors": authors,
            "citation_year": year,
            "groundtruth_arxiv_id": gt,
            "label_status": item["label_status"],
            "usable_label": bool(item["usable_label"]),
            "references_available": has_refs,
            "gt_in_pool": ((aid, gt) in ref_pair_set) if (has_refs and gt) else False,
            "member": item["member"],
            "label_kind": item["label_kind"],
            "partition": item["partition"],
            "bibtex_source": src,
            "is_cited": bib["is_cited"] if bib else None,
        })

    labels_out = pd.DataFrame(final_labels)
    labels_out["citation_year"] = labels_out["citation_year"].astype("Int64")
    partitions_out = pd.DataFrame(list(partitions.values()))

    labels_out.to_parquet(output_dir / "labels.parquet", index=False)
    refs_merged.to_parquet(output_dir / "references.parquet", index=False)
    partitions_out.to_csv(output_dir / "partitions.csv", index=False, encoding="utf-8-sig")

    coverage = {}
    for member in MEMBER_SOURCES:
        m_parts = partitions_out[partitions_out["member"] == member]
        m_lbls = labels_out[labels_out["member"] == member]
        usable_refs = m_lbls[m_lbls["usable_label"] & m_lbls["references_available"]]
        manual = m_lbls[m_lbls["label_kind"] == "manual"]
        manual_counts = {}
        for aid, group in manual.groupby("paper_arxiv_id"):
            usable = group[group["usable_label"]]
            manual_counts[aid] = {
                "usable_labels": len(usable),
                "usable_arxiv_matches": int((usable["label_status"] == "matched").sum()),
            }
        coverage[member] = {
            "total_papers": int(len(m_parts)),
            "papers_with_references": int(m_parts["references_available"].sum()),
            "manual_papers": manual_counts,
            "usable_rows_with_refs": int(len(usable_refs)),
            "usable_matched_with_refs": int((usable_refs["label_status"] == "matched").sum()),
            "usable_none_with_refs": int((usable_refs["label_status"] == "none").sum()),
        }

    summary = {
        "schema_version": SCHEMA_VERSION,
        "seed": SEED,
        "total_papers": int(len(partitions_out)),
        "papers_with_references": int(partitions_out["references_available"].sum()),
        "partition_papers": {
            part: int((partitions_out["partition"] == part).sum())
            for part in ("train", "valid", "test")
        },
        "total_label_rows": int(len(labels_out)),
        "usable_label_rows": int(labels_out["usable_label"].sum()),
        "total_reference_rows": int(len(refs_merged)),
        "auto_papers": auto_papers,
        "auto_papers_target": GROUP_AUTO_TARGET,
        "bibtex_resolution": resolution_counts,
        "coverage": coverage,
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    if sync_dir is not None and sync_dir.resolve() != output_dir.resolve():
        sync_dir.mkdir(parents=True, exist_ok=True)
        for fname in ("labels.parquet", "references.parquet", "partitions.csv", "summary.json"):
            shutil.copy2(output_dir / fname, sync_dir / fname)

    print(json.dumps(summary, indent=2))
    return summary


def write_training_archive(output_dir: Path) -> None:
    archive = output_dir / "m3_training_code.zip"
    temp = archive.with_suffix(".tmp")
    with ZipFile(temp, "w", ZIP_DEFLATED) as bundle:
        for filename in ("__init__.py", "matching.py", "prepare_dataset.py", "train_matching.py", "requirements-m3.txt"):
            relative_path = Path("src") / filename
            bundle.write(ROOT / relative_path, relative_path.as_posix())
    temp.replace(archive)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--members-dir", type=Path, default=ROOT / "data/members")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "kaggle_dataset")
    parser.add_argument("--sync-dir", type=Path, default=ROOT / "data/group_training_seed42")
    args = parser.parse_args()

    standardize_all_members(args.members_dir)
    build_unified_dataset(args.members_dir, args.output_dir, args.sync_dir)
    write_training_archive(args.output_dir)


if __name__ == "__main__":
    main()
