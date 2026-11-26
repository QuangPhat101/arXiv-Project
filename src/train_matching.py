"""Train and evaluate Logistic Regression (baseline) and XGBoost (upgraded) citation matchers.

Designed to run both on Kaggle (auto-detecting /kaggle/input/*) and locally.
Fits on automatic labels and evaluates on separate, verified source papers.
"""

from __future__ import annotations

import argparse
import difflib
import json
import math
import os
import random
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.matching import extract_last_names, normalize_title
from src.prepare_dataset import SCHEMA_VERSION, SEED

MAX_TRAIN_PAIRS_PER_PAPER = 50_000

FEATURE_NAMES: List[str] = [
    "exact_title",
    "token_cosine",
    "raw_seq_ratio",
    "char_ngram_tfidf",
    "author_jaccard",
    "year_diff",
    "year_score",
    "roman_mismatch",
]

ROMAN_NUMERALS: Dict[str, int] = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5,
    "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10,
}


def _extract_part_numbers(title: str) -> Set[int]:
    parts: Set[int] = set()
    norm = str(title or "").lower()
    for match in re.finditer(r"\b(?:part|volume|vol|phase)\s*([ivx\d]+)\b", norm):
        val = match.group(1).strip()
        if val in ROMAN_NUMERALS:
            parts.add(ROMAN_NUMERALS[val])
        elif val.isdigit():
            parts.add(int(val))
    for match in re.finditer(r"(?:[:\-\s]|^)\s*([ivx]+)\s*$", norm):
        val = match.group(1).strip()
        if val in ROMAN_NUMERALS:
            parts.add(ROMAN_NUMERALS[val])
    return parts


def _char_ngrams(norm_text: str, n_min: int = 3, n_max: int = 4) -> Counter:
    if not norm_text:
        return Counter()
    if len(norm_text) < n_min:
        return Counter([norm_text])
    grams: List[str] = []
    for n in range(n_min, n_max + 1):
        if len(norm_text) >= n:
            grams.extend(norm_text[i : i + n] for i in range(len(norm_text) - n + 1))
    return Counter(grams)


def _to_author_list(raw: Any) -> List[str]:
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return []
    if hasattr(raw, "tolist"):
        raw = raw.tolist()
    if isinstance(raw, list):
        return [str(x) for x in raw if x is not None]
    text = str(raw).strip()
    if not text or text.lower() in ("nan", "none", "[]"):
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except Exception:
            pass
    return [text]


def _parse_ref_year(raw: Any) -> Optional[int]:
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return None
    text = str(raw).strip()
    m = re.match(r"^((?:19|20)\d{2})", text)
    return int(m.group(1)) if m else None


def _precompute_text_item(
    title: str,
    authors: Any,
    year: Optional[int],
    idf_dict: Dict[str, float],
) -> Dict[str, Any]:
    norm = normalize_title(title)
    words = Counter(norm.split()) if norm else Counter()
    word_mag = math.sqrt(sum(v * v for v in words.values()))

    grams = _char_ngrams(norm)
    ngram_vec = {k: float(c) * idf_dict.get(k, 1.0) for k, c in grams.items()}
    ngram_mag = math.sqrt(sum(v * v for v in ngram_vec.values()))

    return {
        "norm": norm,
        "words": words,
        "word_mag": word_mag,
        "ngram_vec": ngram_vec,
        "ngram_mag": ngram_mag,
        "surnames": extract_last_names(_to_author_list(authors)),
        "parts": _extract_part_numbers(title),
        "year": year,
    }


def _cosine_dict(vec_a: Dict[str, float], mag_a: float, vec_b: Dict[str, float], mag_b: float) -> float:
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    if len(vec_a) > len(vec_b):
        vec_a, vec_b = vec_b, vec_a
    dot = sum(val * vec_b[k] for k, val in vec_a.items() if k in vec_b)
    return float(min(1.0, dot / (mag_a * mag_b))) if dot > 0.0 else 0.0


def _compute_pair_features(
    cit: Dict[str, Any],
    ref: Dict[str, Any],
    seq_matcher: difflib.SequenceMatcher,
) -> List[float]:
    norm_a, norm_b = cit["norm"], ref["norm"]
    if norm_a and norm_a == norm_b:
        exact_title = 1.0
        raw_seq = 1.0
    elif norm_a and norm_b:
        exact_title = 0.0
        seq_matcher.set_seq1(norm_a)
        # Skip expensive O(N^2) longest-contiguous-block matching when char bag overlap is tiny
        qr = seq_matcher.quick_ratio()
        raw_seq = float(seq_matcher.ratio()) if qr >= 0.25 else float(qr)
    else:
        exact_title = 0.0
        raw_seq = 0.0

    token_cos = _cosine_dict(cit["words"], cit["word_mag"], ref["words"], ref["word_mag"])
    ngram_cos = _cosine_dict(cit["ngram_vec"], cit["ngram_mag"], ref["ngram_vec"], ref["ngram_mag"])

    sa, sb = cit["surnames"], ref["surnames"]
    author_jaccard = float(len(sa & sb) / len(sa | sb)) if (sa and sb) else 0.0

    ya, yb = cit["year"], ref["year"]
    if ya is not None and yb is not None:
        diff = abs(int(ya) - int(yb))
        year_diff = min(diff / 10.0, 1.0)
        if diff == 0:
            year_score = 1.0
        elif diff == 1:
            year_score = 0.90
        elif diff == 2:
            year_score = 0.60
        else:
            year_score = float(max(0.0, 1.0 - 0.20 * diff))
    else:
        year_diff = 1.0
        year_score = 0.50

    pa, pb = cit["parts"], ref["parts"]
    roman_mismatch = 1.0 if (pa and pb and not (pa & pb)) else 0.0

    return [
        exact_title,
        token_cos,
        raw_seq,
        ngram_cos,
        author_jaccard,
        year_diff,
        year_score,
        roman_mismatch,
    ]


def _process_paper_chunk(
    task: Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]], bool],
) -> Dict[str, Any]:
    """Build pairwise feature matrices for all labeled citations in one paper."""
    aid, label_rows, ref_rows, keep_queries = task

    ref_titles = [str(r.get("ref_title") or "") for r in ref_rows if r.get("ref_title")]
    num_docs = len(ref_titles)
    idf_dict: Dict[str, float] = {}
    if num_docs > 0:
        df_counter: Counter = Counter()
        for t in ref_titles:
            df_counter.update(set(_char_ngrams(normalize_title(t)).keys()))
        idf_dict = {g: math.log((1.0 + num_docs) / (1.0 + df)) + 1.0 for g, df in df_counter.items()}

    ref_ids: List[str] = []
    encoded_refs: List[Dict[str, Any]] = []
    seq_matchers: List[difflib.SequenceMatcher] = []
    for r in ref_rows:
        ref_id = str(r.get("ref_arxiv_id") or "").strip()
        if not ref_id:
            continue
        ref_ids.append(ref_id)
        enc = _precompute_text_item(
            str(r.get("ref_title") or ""),
            r.get("ref_authors"),
            _parse_ref_year(r.get("ref_submission_date")),
            idf_dict,
        )
        encoded_refs.append(enc)
        seq_matchers.append(difflib.SequenceMatcher(None, "", enc["norm"]))

    x_blocks: List[np.ndarray] = []
    y_blocks: List[np.ndarray] = []
    queries: List[Dict[str, Any]] = []

    for row in label_rows:
        cit_year = row.get("citation_year")
        cit_year_int = int(cit_year) if cit_year is not None and not pd.isna(cit_year) else None
        cit_enc = _precompute_text_item(
            str(row.get("citation_title") or ""),
            row.get("citation_authors"),
            cit_year_int,
            idf_dict,
        )
        gt = str(row.get("groundtruth_arxiv_id") or "").strip()
        candidate_ids = ref_ids if row["bibtex_source"] == "m2_bibtex" else []
        mat = np.asarray(
            [
                _compute_pair_features(cit_enc, ref_enc, sm)
                for ref_enc, sm in zip(encoded_refs, seq_matchers)
            ] if candidate_ids else [],
            dtype=np.float32,
        ).reshape(-1, len(FEATURE_NAMES))
        targets = np.fromiter((rid == gt for rid in candidate_ids), dtype=np.uint8)

        x_blocks.append(mat)
        y_blocks.append(targets)
        if keep_queries:
            queries.append({
                "paper_arxiv_id": aid,
                "citation_key": row["citation_key"],
                "label_kind": row["label_kind"],
                "member": row["member"],
                "groundtruth_arxiv_id": gt,
                "ref_ids": candidate_ids,
                "gt_in_pool": gt in ref_ids if gt else False,
                "bibtex_available": row["bibtex_source"] == "m2_bibtex",
                "features": mat,
            })

    return {
        "x": np.vstack(x_blocks) if x_blocks else np.empty((0, len(FEATURE_NAMES)), dtype=np.float32),
        "y": np.concatenate(y_blocks) if y_blocks else np.empty((0,), dtype=np.uint8),
        "queries": queries,
    }


def _fit_logreg_numpy(x_scaled: np.ndarray, y: np.ndarray, reg_c: float = 1.0) -> Tuple[float, np.ndarray]:
    """Fallback L2-regularized logistic regression solver using Newton-Raphson."""
    n_samples, n_features = x_scaled.shape
    design = np.column_stack((np.ones(n_samples, dtype=np.float64), x_scaled.astype(np.float64)))
    targets = y.astype(np.float64)
    penalty = np.diag([0.0] + [1.0 / reg_c] * n_features)
    weights = np.zeros(n_features + 1, dtype=np.float64)
    for _ in range(80):
        prob = 1.0 / (1.0 + np.exp(-np.clip(design @ weights, -40.0, 40.0)))
        grad = design.T @ (prob - targets) + penalty @ weights
        hessian = design.T @ ((prob * (1.0 - prob))[:, None] * design) + penalty
        step = np.linalg.solve(hessian, grad)
        weights -= step
        if np.linalg.norm(step) < 1e-7:
            break
    return float(weights[0]), weights[1:]


def train_logistic_regression(x_train: np.ndarray, y_train: np.ndarray) -> Dict[str, Any]:
    """Train Logistic Regression baseline and export both scaled and raw coefficients."""
    mean = x_train.mean(axis=0).astype(np.float64)
    scale = x_train.std(axis=0).astype(np.float64)
    scale[scale == 0.0] = 1.0
    x_scaled = (x_train.astype(np.float64) - mean) / scale

    try:
        from sklearn.linear_model import LogisticRegression

        clf = LogisticRegression(C=1.0, max_iter=1000, solver="lbfgs", random_state=42)
        clf.fit(x_scaled, y_train)
        intercept = float(clf.intercept_[0])
        coef = clf.coef_[0].astype(np.float64)
        backend = "scikit-learn"
    except ImportError:
        intercept, coef = _fit_logreg_numpy(x_scaled, y_train, reg_c=1.0)
        backend = "numpy-newton"

    # Algebraic conversion back to unscaled feature space: intercept + sum(coef * (x - mean)/scale)
    raw_coef = coef / scale
    raw_intercept = float(intercept - np.sum(coef * mean / scale))

    return {
        "backend": backend,
        "features": FEATURE_NAMES,
        "intercept": intercept,
        "coefficients": coef.tolist(),
        "scaler_mean": mean.tolist(),
        "scaler_scale": scale.tolist(),
        "raw_intercept": raw_intercept,
        "raw_coefficients": raw_coef.tolist(),
    }


def predict_logreg_probs(model_info: Dict[str, Any], features: np.ndarray) -> np.ndarray:
    raw_coef = np.asarray(model_info["raw_coefficients"], dtype=np.float64)
    logits = float(model_info["raw_intercept"]) + features.astype(np.float64) @ raw_coef
    return 1.0 / (1.0 + np.exp(-np.clip(logits, -40.0, 40.0)))


def train_xgboost(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_valid: np.ndarray,
    y_valid: np.ndarray,
    use_gpu: bool = False,
    workers: int = 4,
) -> Any:
    """Train upgraded XGBoost classifier with early stopping on validation logloss."""
    import xgboost as xgb

    kwargs: Dict[str, Any] = {
        "n_estimators": 500,
        "max_depth": 5,
        "learning_rate": 0.05,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 5,
        "reg_lambda": 1.0,
        "eval_metric": "logloss",
        "early_stopping_rounds": 30,
        "tree_method": "hist",
        "n_jobs": workers,
        "random_state": 42,
    }
    if use_gpu:
        kwargs["device"] = "cuda"

    model = xgb.XGBClassifier(**kwargs)
    model.fit(x_train, y_train, eval_set=[(x_valid, y_valid)], verbose=False)
    return model


def score_heuristic(features: np.ndarray) -> np.ndarray:
    """Compute original repo heuristic score (src/matching.py weights)."""
    # FEATURE_NAMES indices: 0=exact_title, 1=token_cosine, 4=author_jaccard, 5=year_diff
    return (
        5.0 * features[:, 0]
        + 3.0 * features[:, 1]
        + 2.0 * features[:, 4]
        - 0.5 * features[:, 5]
    )


def tune_threshold(
    queries: List[Dict[str, Any]],
    score_key: str,
    candidates: Optional[Sequence[float]] = None,
) -> Tuple[float, float]:
    """Tune abstention threshold on validation set to maximize end-to-end accuracy."""
    if candidates is None:
        candidates = np.linspace(0.0, 1.0, 101)
    best_t = 0.5
    best_acc = -1.0
    for t in candidates:
        correct = 0
        for q in queries:
            scores = q[score_key]
            pred = ""
            if scores.size:
                top_idx = int(np.argmax(scores))
                if scores[top_idx] >= t:
                    pred = q["ref_ids"][top_idx]
            if pred == q["groundtruth_arxiv_id"]:
                correct += 1
        acc = correct / len(queries) if queries else 0.0
        if acc > best_acc:
            best_acc = acc
            best_t = float(t)
    return best_t, best_acc


def evaluate_queries(
    queries: List[Dict[str, Any]],
    score_key: str,
    threshold: Optional[float] = None,
) -> Dict[str, Any]:
    """Compute ranking metrics (MRR@5, Hit@1, Hit@5) and optional thresholded end-to-end metrics."""
    rr_pos: List[float] = []
    hit1_pos = 0
    hit5_pos = 0
    e2e_correct = 0
    tp = 0
    fp = 0
    fn = 0
    none_total = 0
    none_correct = 0

    for q in queries:
        scores = q[score_key]
        order = np.argsort(-scores, kind="stable")
        top5 = [q["ref_ids"][i] for i in order[:5]]
        gt = q["groundtruth_arxiv_id"]

        if gt:
            if gt in top5:
                rank = top5.index(gt) + 1
                rr_pos.append(1.0 / rank)
                if rank == 1:
                    hit1_pos += 1
                hit5_pos += 1
            else:
                rr_pos.append(0.0)

        if threshold is not None:
            pred = top5[0] if order.size and scores[order[0]] >= threshold else ""
            if pred == gt:
                e2e_correct += 1
            if not gt:
                none_total += 1
                if not pred:
                    none_correct += 1
            if pred and gt and pred == gt:
                tp += 1
            else:
                if pred:
                    fp += 1
                if gt:
                    fn += 1

    pos_n = len(rr_pos)
    result: Dict[str, Any] = {
        "total_queries": len(queries),
        "positive_queries": pos_n,
        "positives_in_pool": sum(q["gt_in_pool"] for q in queries),
        "queries_missing_bibtex": sum(not q["bibtex_available"] for q in queries),
        "mrr@5": float(np.mean(rr_pos)) if pos_n else None,
        "hit@1": float(hit1_pos / pos_n) if pos_n else None,
        "hit@5": float(hit5_pos / pos_n) if pos_n else None,
    }
    if threshold is not None and queries:
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
        result.update({
            "threshold": threshold,
            "e2e_accuracy": float(e2e_correct / len(queries)),
            "matched_precision": float(prec),
            "matched_recall": float(rec),
            "matched_f1": float(f1),
            "none_accuracy": float(none_correct / none_total) if none_total else None,
        })
    return result


def evaluate_by_subset(
    queries: List[Dict[str, Any]],
    score_key: str,
    threshold: Optional[float] = None,
) -> Dict[str, Any]:
    out = {"all": evaluate_queries(queries, score_key, threshold)}
    for member in sorted({q["member"] for q in queries}):
        out[member] = evaluate_queries([q for q in queries if q["member"] == member], score_key, threshold)
    return out


def resolve_dataset_dir(explicit_dir: Optional[Path]) -> Path:
    """Locate dataset directory locally or under /kaggle/input."""
    if explicit_dir is not None:
        return explicit_dir
    for local_cand in (ROOT / "kaggle_dataset", ROOT / "data/group_training_seed42"):
        if (local_cand / "labels.parquet").is_file() and (local_cand / "references.parquet").is_file():
            return local_cand
    kaggle_input = Path("/kaggle/input")
    if kaggle_input.is_dir():
        candidates = [p.parent for p in kaggle_input.rglob("labels.parquet")
                      if (p.parent / "references.parquet").is_file()
                      and (p.parent / "summary.json").is_file()]
        if len(candidates) == 1:
            return candidates[0]
        if candidates:
            raise ValueError(f"Multiple Kaggle datasets found. Pass --dataset-dir: {sorted(candidates)}")
    raise FileNotFoundError("Could not locate labels.parquet and references.parquet. Pass --dataset-dir.")


def run_training(
    dataset_dir: Path,
    output_dir: Path,
    workers: int = 4,
    use_gpu: bool = False,
    logreg_only: bool = False,
) -> Dict[str, Any]:
    if workers < 1:
        raise ValueError("workers must be at least 1")
    manifest = json.loads((dataset_dir / "summary.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Dataset uses an old schema. Rebuild it with src/prepare_dataset.py.")
    if not logreg_only:
        try:
            import xgboost  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("Install xgboost or use --logreg-only for a baseline run.") from exc
    labels_df = pd.read_parquet(dataset_dir / "labels.parquet")
    refs_df = pd.read_parquet(dataset_dir / "references.parquet")
    if len(labels_df) != manifest["total_label_rows"] or len(refs_df) != manifest["total_reference_rows"]:
        raise ValueError("Dataset files disagree with summary.json. Rebuild the dataset.")
    if labels_df.duplicated(["paper_arxiv_id", "citation_key"]).any():
        raise ValueError("Dataset contains duplicate labels")
    split_counts = labels_df.groupby("paper_arxiv_id")["partition"].nunique(dropna=False)
    auto = labels_df["label_kind"].eq("auto")
    manual = labels_df["label_kind"].eq("manual")
    train_rows = labels_df["partition"].eq("train")
    holdout_rows = labels_df["partition"].isin(("valid", "test"))
    if (split_counts != 1).any() or not ((auto & train_rows) | (manual & holdout_rows)).all():
        raise ValueError("Split disjoint source papers into automatic train and manual valid/test")
    if refs_df.duplicated(["arxiv_id", "ref_arxiv_id"]).any() or not refs_df["ref_arxiv_id"].map(bool).all():
        raise ValueError("Dataset contains duplicate or empty candidate IDs")

    refs_by_paper: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for rec in refs_df.to_dict(orient="records"):
        refs_by_paper[str(rec["arxiv_id"])].append(rec)
    pool = {(aid, rec["ref_arxiv_id"]) for aid, refs in refs_by_paper.items() for rec in refs}

    labels_by_split: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
        "train": defaultdict(list),
        "valid": defaultdict(list),
        "test": defaultdict(list),
    }
    usable_labels = labels_df[labels_df["usable_label"] & labels_df["label_status"].isin(("matched", "none"))]
    skipped_train: Counter = Counter()
    for rec in usable_labels.to_dict(orient="records"):
        split = rec["partition"]
        aid = rec["paper_arxiv_id"]
        gt = rec["groundtruth_arxiv_id"]
        if split == "train":
            if pd.notna(rec["is_cited"]) and not rec["is_cited"]:
                skipped_train["not_cited"] += 1
                continue
            if rec["bibtex_source"] != "m2_bibtex":
                skipped_train["missing_bibtex"] += 1
                continue
            if not refs_by_paper.get(aid) or (gt and (aid, gt) not in pool):
                skipped_train["missing_pool_or_match"] += 1
                continue
        labels_by_split[split][aid].append(rec)
    for split, papers in labels_by_split.items():
        if not papers or not any(row["groundtruth_arxiv_id"] for rows in papers.values() for row in rows):
            raise ValueError(f"{split} needs usable citations with known matches")

    capped_papers = {}
    for aid, rows in labels_by_split["train"].items():
        candidate_count = len(refs_by_paper[aid])
        query_limit = max(1, MAX_TRAIN_PAIRS_PER_PAPER // candidate_count)
        if len(rows) <= query_limit:
            continue
        sampled = random.Random(SEED).sample(sorted(rows, key=lambda row: row["citation_key"]), query_limit)
        labels_by_split["train"][aid] = sampled
        capped_papers[aid] = {"total_queries": len(rows), "used_queries": len(sampled), "candidates": candidate_count}
    print(f"Capped automatic training papers: {capped_papers}", flush=True)
    print(f"Excluded automatic training labels: {dict(skipped_train)}", flush=True)

    split_data: Dict[str, Dict[str, Any]] = {}
    for split in ("train", "valid", "test"):
        keep_queries = split != "train"
        tasks = [
            (aid, rows, refs_by_paper.get(aid, []), keep_queries)
            for aid, rows in sorted(labels_by_split[split].items())
        ]
        x_list, y_list, q_list = [], [], []
        if tasks:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                for idx, res in enumerate(pool.map(_process_paper_chunk, tasks, chunksize=8), start=1):
                    if len(res["y"]) > 0:
                        x_list.append(res["x"])
                        y_list.append(res["y"])
                    if keep_queries:
                        q_list.extend(res["queries"])
                    if idx % 200 == 0 or idx == len(tasks):
                        print(f"[{split}] extracted features for {idx}/{len(tasks)} papers", flush=True)
        query_count = len(q_list) if keep_queries else sum(len(t[1]) for t in tasks)
        split_data[split] = {
            "papers": len(tasks),
            "query_count": query_count,
            "x": np.vstack(x_list) if x_list else np.empty((0, len(FEATURE_NAMES)), dtype=np.float32),
            "y": np.concatenate(y_list) if y_list else np.empty((0,), dtype=np.uint8),
            "queries": q_list,
        }
        print(
            f"[{split}] papers={len(tasks)} queries={query_count} "
            f"pairs={len(split_data[split]['y'])} positives={int(split_data[split]['y'].sum())}",
            flush=True,
        )

    for split in ("train", "valid"):
        targets = split_data[split]["y"]
        if set(np.unique(targets)) != {0, 1}:
            raise ValueError(f"{split} needs both matching and nonmatching candidate pairs")

    output_dir.mkdir(parents=True, exist_ok=True)
    logreg_info = train_logistic_regression(split_data["train"]["x"], split_data["train"]["y"])
    (output_dir / "logreg_model.json").write_text(json.dumps(logreg_info, indent=2) + "\n", encoding="utf-8")

    xgb_model = None if logreg_only else train_xgboost(
        split_data["train"]["x"],
        split_data["train"]["y"],
        split_data["valid"]["x"],
        split_data["valid"]["y"],
        use_gpu=use_gpu,
        workers=workers,
    )
    if xgb_model is not None:
        xgb_model.save_model(str(output_dir / "xgboost_model.json"))
        booster = xgb_model.get_booster()
        gain_raw = booster.get_score(importance_type="gain")
        weight_raw = booster.get_score(importance_type="weight")
        xgb_importances = {
            "features": FEATURE_NAMES,
            "best_iteration": int(getattr(xgb_model, "best_iteration", xgb_model.n_estimators)),
            "gain_importance": {
                name: float(gain_raw.get(f"f{idx}", 0.0)) for idx, name in enumerate(FEATURE_NAMES)
            },
            "split_weight_importance": {
                name: float(weight_raw.get(f"f{idx}", 0.0)) for idx, name in enumerate(FEATURE_NAMES)
            },
            "sklearn_normalized_importance": {
                name: float(val) for name, val in zip(FEATURE_NAMES, xgb_model.feature_importances_)
            },
        }
        (output_dir / "xgboost_feature_importances.json").write_text(
            json.dumps(xgb_importances, indent=2) + "\n", encoding="utf-8"
        )

    # Score valid and test queries for all models
    for split in ("valid", "test"):
        matrices = split_data[split]["x"]
        xgb_scores = xgb_model.predict_proba(matrices)[:, 1] if xgb_model is not None and len(matrices) else None
        offset = 0
        for q in split_data[split]["queries"]:
            feats = q["features"]
            q["score_heuristic"] = score_heuristic(feats)
            q["score_logreg"] = predict_logreg_probs(logreg_info, feats)
            if xgb_model is not None:
                end = offset + len(feats)
                q["score_xgb"] = xgb_scores[offset:end] if xgb_scores is not None else np.empty(0)
                offset = end

    heur_thresh, _ = tune_threshold(split_data["valid"]["queries"], "score_heuristic", np.linspace(-0.5, 10.1, 107))
    logreg_thresh, _ = tune_threshold(split_data["valid"]["queries"], "score_logreg")

    evaluation: Dict[str, Any] = {
        "heuristic_baseline": {
            "valid": evaluate_by_subset(split_data["valid"]["queries"], "score_heuristic", heur_thresh),
            "test": evaluate_by_subset(split_data["test"]["queries"], "score_heuristic", heur_thresh),
        },
        "logistic_regression": {
            "valid": evaluate_by_subset(split_data["valid"]["queries"], "score_logreg", logreg_thresh),
            "test": evaluate_by_subset(split_data["test"]["queries"], "score_logreg", logreg_thresh),
        },
    }
    if xgb_model is not None:
        xgb_thresh, _ = tune_threshold(split_data["valid"]["queries"], "score_xgb")
        evaluation["xgboost"] = {
            "valid": evaluate_by_subset(split_data["valid"]["queries"], "score_xgb", xgb_thresh),
            "test": evaluate_by_subset(split_data["test"]["queries"], "score_xgb", xgb_thresh),
        }

    # Export test query predictions for error analysis
    pred_rows = []
    for q in split_data["test"]["queries"]:
        row: Dict[str, Any] = {
            "paper_arxiv_id": q["paper_arxiv_id"],
            "member": q["member"],
            "label_kind": q["label_kind"],
            "citation_key": q["citation_key"],
            "groundtruth_arxiv_id": q["groundtruth_arxiv_id"],
        }
        for model_name, key, thr in (
            ("heuristic", "score_heuristic", heur_thresh),
            ("logreg", "score_logreg", logreg_thresh),
            *( [("xgb", "score_xgb", xgb_thresh)] if xgb_model is not None else [] ),
        ):
            scores = q[key]
            order = np.argsort(-scores, kind="stable")[:5]
            top_ids = [q["ref_ids"][i] for i in order]
            top_score = float(scores[order[0]]) if order.size else None
            for i in range(5):
                row[f"{model_name}_top{i + 1}"] = top_ids[i] if i < len(top_ids) else ""
            row[f"{model_name}_score"] = round(top_score, 6) if top_score is not None else None
            row[f"{model_name}_pred"] = top_ids[0] if top_ids and top_score >= thr else ""
        pred_rows.append(row)
    pd.DataFrame(pred_rows).to_csv(output_dir / "test_predictions.csv", index=False, encoding="utf-8-sig")

    summary = {
        "dataset_dir": str(dataset_dir),
        "dataset_schema_version": SCHEMA_VERSION,
        "skipped_train_labels": dict(skipped_train),
        "training_pair_budget": {"target_max_pairs_per_paper": MAX_TRAIN_PAIRS_PER_PAPER, "capped_papers": capped_papers},
        "features": FEATURE_NAMES,
        "split_stats": {
            split: {
                "papers": split_data[split]["papers"],
                "queries": split_data[split]["query_count"],
                "pairs": int(len(split_data[split]["y"])),
                "positives": int(split_data[split]["y"].sum()),
            }
            for split in ("train", "valid", "test")
        },
        "evaluation": evaluation,
    }
    (output_dir / "metrics_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary["evaluation"], indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=None, help="Folder with labels.parquet & references.parquet")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs_m3/audited"), help="Where to save models and metrics")
    parser.add_argument("--workers", type=int, default=max(1, min(8, os.cpu_count() or 4)))
    parser.add_argument("--use-gpu", action="store_true", help="Use CUDA for XGBoost if available")
    parser.add_argument("--logreg-only", action="store_true", help="Run the heuristic and logistic baselines only")
    args = parser.parse_args()

    ds_dir = resolve_dataset_dir(args.dataset_dir)
    run_training(
        dataset_dir=ds_dir,
        output_dir=args.output_dir,
        workers=args.workers,
        use_gpu=args.use_gpu,
        logreg_only=args.logreg_only,
    )


if __name__ == "__main__":
    main()
