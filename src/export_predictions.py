"""Rank the BibTeX entries of selected source papers and write M3 Parquet."""

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from src.train_matching import FEATURE_NAMES, _process_paper_chunk, predict_logreg_probs


TOP_COLUMNS = [f"cand_{rank}" for rank in range(1, 6)]
PREDICTIONS_SCHEMA = pa.schema([
    pa.field("arxiv_id", pa.string(), nullable=False),
    pa.field("partition", pa.dictionary(pa.int8(), pa.string()), nullable=False),
    pa.field("citation_key", pa.string(), nullable=False),
    pa.field("groundtruth_arxiv_id", pa.string()),
    *[pa.field(column, pa.string()) for column in TOP_COLUMNS],
])

_XGB_MODEL_CACHE = {}


def load_model_spec(model_path: Path, model_type: str = "auto"):
    payload = json.loads(model_path.read_text(encoding="utf-8"))
    resolved = model_type
    if resolved == "auto":
        if "learner" in payload:
            resolved = "xgboost"
        elif "raw_coefficients" in payload:
            resolved = "logreg"
        else:
            raise ValueError(f"Unrecognized model format in {model_path}")

    if resolved == "logreg":
        if payload.get("features") != FEATURE_NAMES:
            raise ValueError("Logistic Regression model features do not match this pipeline")
        return {"model_type": "logreg", **payload}

    if resolved == "xgboost":
        import xgboost as xgb

        clf = xgb.XGBClassifier()
        clf.load_model(str(model_path))
        if int(getattr(clf, "n_features_in_", len(FEATURE_NAMES))) != len(FEATURE_NAMES):
            raise ValueError("XGBoost model feature count does not match this pipeline")
        return {"model_type": "xgboost", "model_path": str(model_path.resolve())}

    raise ValueError(f"Unsupported model_type: {model_type}")


def score_features(model_spec, features: np.ndarray) -> np.ndarray:
    if len(features) == 0:
        return np.empty(0, dtype=np.float64)
    model_type = model_spec.get("model_type", "logreg")
    if model_type == "logreg":
        return predict_logreg_probs(model_spec, features)
    if model_type == "xgboost":
        model_path = model_spec["model_path"]
        clf = _XGB_MODEL_CACHE.get(model_path)
        if clf is None:
            import xgboost as xgb

            clf = xgb.XGBClassifier()
            clf.load_model(model_path)
            clf.set_params(n_jobs=1)
            _XGB_MODEL_CACHE[model_path] = clf
        return clf.predict_proba(features)[:, 1].astype(np.float64, copy=False)
    raise ValueError(f"Unsupported model_type: {model_type}")


def rank_paper(task):
    aid, partition, entries, refs, model = task
    features = _process_paper_chunk((aid, entries, refs, True))
    scores = score_features(model, features["x"])
    rows = []
    offset = 0
    for query in features["queries"]:
        end = offset + len(query["ref_ids"])
        order = np.argsort(-scores[offset:end], kind="stable")[:5]
        offset = end
        top = [query["ref_ids"][index] for index in order]
        rows.append({
            "arxiv_id": aid,
            "partition": partition,
            "citation_key": query["citation_key"],
            "groundtruth_arxiv_id": query["groundtruth_arxiv_id"] if query["gt_in_pool"] else None,
            **dict(zip(TOP_COLUMNS, top)),
        })
    return rows


def export_predictions(dataset_dir, bibtex_paths, model_path, output_path, splits, workers, model_type="auto"):
    model = load_model_spec(model_path, model_type=model_type)
    partitions = pd.read_csv(dataset_dir / "partitions.csv", dtype={"paper_arxiv_id": str})
    if partitions["paper_arxiv_id"].duplicated().any():
        raise ValueError("Source papers must have a single partition")
    selected = partitions[partitions["partition"].isin(splits)].set_index("paper_arxiv_id")["partition"]
    if selected.empty:
        raise ValueError("No source papers found in the selected partitions")

    paper_ids = selected.index.tolist()
    bibtex = pd.concat([
        pd.read_parquet(path, columns=["arxiv_id", "citation_key", "title", "authors", "year"],
                        filters=[("arxiv_id", "in", paper_ids)])
        for path in bibtex_paths
    ], ignore_index=True)
    keys = ["arxiv_id", "citation_key"]
    if bibtex.empty or bibtex.duplicated(keys).any() or bibtex[keys].isna().any().any():
        raise ValueError("Selected BibTeX inputs must contain unique, non-null paper and citation keys")
    missing_papers = set(paper_ids) - set(bibtex["arxiv_id"])
    if missing_papers:
        raise ValueError(f"BibTeX missing for {len(missing_papers)} selected papers: {sorted(missing_papers)[:5]}")

    labels = pd.read_parquet(dataset_dir / "labels.parquet", filters=[("paper_arxiv_id", "in", paper_ids)])
    usable = labels[labels["usable_label"]].rename(columns={"paper_arxiv_id": "arxiv_id"})
    missing_keys = pd.MultiIndex.from_frame(usable[keys]).difference(pd.MultiIndex.from_frame(bibtex[keys]))
    if len(missing_keys):
        raise ValueError(f"BibTeX missing for {len(missing_keys)} usable label keys: {missing_keys[:5].tolist()}")
    known = usable[usable["label_status"].eq("matched")]
    bibtex = bibtex.merge(known[[*keys, "groundtruth_arxiv_id"]], on=keys, how="left", validate="one_to_one")
    bibtex = bibtex.rename(columns={"title": "citation_title", "authors": "citation_authors", "year": "citation_year"})
    bibtex["groundtruth_arxiv_id"] = bibtex["groundtruth_arxiv_id"].fillna("")
    bibtex["citation_title"] = bibtex["citation_title"].fillna("")
    bibtex["bibtex_source"] = np.where(bibtex["citation_title"].str.strip().ne(""), "m2_bibtex", "missing")
    bibtex["label_kind"] = None
    bibtex["member"] = None

    references = pd.read_parquet(dataset_dir / "references.parquet", filters=[("arxiv_id", "in", paper_ids)])
    if references.duplicated(["arxiv_id", "ref_arxiv_id"]).any():
        raise ValueError("References contain duplicate IDs within a source paper")
    refs_by_paper = {aid: rows.to_dict("records") for aid, rows in references.groupby("arxiv_id")}
    tasks = [
        (aid, selected[aid], entries.iloc[start:start + 128].to_dict("records"), refs_by_paper.get(aid, []), model)
        for aid, entries in bibtex.groupby("arxiv_id", sort=True)
        for start in range(0, len(entries), 128)
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output_path.parent) as temp:
        pending = Path(temp) / output_path.name
        with pq.ParquetWriter(pending, PREDICTIONS_SCHEMA) as writer, ProcessPoolExecutor(max_workers=workers) as pool:
            buffer = []
            for index, rows in enumerate(pool.map(rank_paper, tasks), start=1):
                buffer.extend(rows)
                if len(buffer) >= 10_000 or index == len(tasks):
                    writer.write_table(pa.Table.from_pylist(buffer, schema=PREDICTIONS_SCHEMA))
                    buffer.clear()
                if index % 100 == 0 or index == len(tasks):
                    print(f"Ranked {index}/{len(tasks)} batches", flush=True)
        pending.replace(output_path)
    print(f"Wrote {len(bibtex)} rows to {output_path}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=Path("kaggle_dataset"))
    parser.add_argument("--bibtex", type=Path, nargs="+", help="M2 BibTeX Parquet files or directories")
    parser.add_argument("--model", type=Path, required=True, help="Saved logreg_model.json or xgboost_model.json")
    parser.add_argument("--model-type", choices=("auto", "logreg", "xgboost"), default="auto")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--splits", nargs="+", choices=("train", "valid", "test"), default=["train", "valid", "test"])
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    args = parser.parse_args()
    bibtex = args.bibtex or sorted(Path("data/members").glob("*/bibtex.parquet"))
    if not bibtex:
        parser.error("Pass --bibtex with the processed BibTeX Parquet files")
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    export_predictions(args.dataset_dir, bibtex, args.model, args.output, args.splits, args.workers, model_type=args.model_type)


if __name__ == "__main__":
    main()
