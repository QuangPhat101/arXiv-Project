import numpy as np
import pandas as pd
import pyarrow as pa

from src.export_predictions import PREDICTIONS_SCHEMA, load_model_spec, rank_paper, score_features
from src.prepare_dataset import automatic_labels, reconcile_reviewed_labels
from src.train_matching import FEATURE_NAMES, _process_paper_chunk, evaluate_queries, tune_threshold


def test_mrr_counts_matches_with_no_candidate_or_bibtex():
    labels = [
        {
            "citation_key": key,
            "citation_title": "Reference title",
            "bibtex_source": bibtex_source,
            "groundtruth_arxiv_id": groundtruth,
            "label_kind": "manual",
            "member": "phat",
        }
        for key, bibtex_source, groundtruth in (
            ("known", "m2_bibtex", "2401.00001"),
            ("out_of_pool", "m2_bibtex", "2401.00002"),
            ("missing_bibtex", "missing", "2401.00001"),
            ("no_match", "m2_bibtex", ""),
        )
    ]
    refs = [{"ref_arxiv_id": "2401.00001", "ref_title": "Reference title"}]
    queries = _process_paper_chunk(("2501.00001", labels, refs, True))["queries"]
    queries.extend(_process_paper_chunk(("2501.00002", labels[:1], [], True))["queries"])
    for query in queries:
        query["score"] = np.ones(len(query["ref_ids"]))

    threshold, _ = tune_threshold(queries, "score")
    metrics = evaluate_queries(queries, "score", threshold)

    assert metrics["positive_queries"] == 4
    assert metrics["positives_in_pool"] == 2
    assert metrics["queries_missing_bibtex"] == 1
    assert metrics["mrr@5"] == 0.20
    assert metrics["mrr@5_matched"] == 0.25
    assert metrics["hit@5"] == 0.25


def test_export_predictions_keeps_only_ground_truth_from_same_paper_pool():
    entries = [
        {
            "citation_key": key,
            "citation_title": "Reference title",
            "bibtex_source": "m2_bibtex",
            "groundtruth_arxiv_id": target,
            "label_kind": None,
            "member": None,
        }
        for key, target in (("known", "2401.00001"), ("outside_pool", "2401.00002"))
    ]
    refs = [{"ref_arxiv_id": "2401.00001", "ref_title": "Reference title"}]
    model = {"raw_coefficients": [1.0] * len(FEATURE_NAMES), "raw_intercept": 0.0}

    rows = rank_paper(("2501.00001", "test", entries, refs, model))
    result = pa.Table.from_pylist(rows, schema=PREDICTIONS_SCHEMA)

    assert pa.types.is_dictionary(result.schema.field("partition").type)
    assert result["groundtruth_arxiv_id"].to_pylist() == ["2401.00001", None]
    assert result["cand_1"].to_pylist() == ["2401.00001", "2401.00001"]
    assert result["cand_2"].to_pylist() == [None, None]


def test_release_labels_preserve_reviewed_key_identity_and_use_same_paper_pool():
    entries = pd.DataFrame([
        {"arxiv_id": "paper", "citation_key": "first", "title": "Shared title", "authors": ["Alice Smith"],
         "url": "https://arxiv.org/abs/2201.01000"},
        {"arxiv_id": "paper", "citation_key": "second", "title": "Shared title", "authors": ["Bob Jones"]},
    ])
    references = pd.DataFrame([
        {"arxiv_id": "paper", "ref_arxiv_id": "2201.01000", "ref_title": "Shared title", "ref_authors": ["Alice Smith"]},
        {"arxiv_id": "other", "ref_arxiv_id": "2202.01000", "ref_title": "Shared title", "ref_authors": ["Bob Jones"]},
    ])
    automatic = list(automatic_labels(entries.to_dict("records"), references, "auto_m2"))
    assert [row["groundtruth_arxiv_id"] for row in automatic] == ["2201.01000", ""]
    assert all(row["usable_label"] for row in automatic)

    reviewed = pd.DataFrame([{
        "paper_arxiv_id": "paper", "citation_key": "old", "citation_title": "Shared title",
        "citation_authors": ["Bob Jones"], "label_status": "none", "groundtruth_arxiv_id": "",
        "usable_label": True, "label_kind": "manual", "label_provenance": "human",
    }])
    changes = pd.DataFrame([{"arxiv_id": "paper", "source_key": "old", "citation_key": key}
                            for key in ("first", "second")])
    manual, decisions = reconcile_reviewed_labels(reviewed, entries, changes)
    assert manual["citation_key"].tolist() == ["second"]
    assert manual["label_provenance"].tolist() == ["human"]
    assert decisions[0]["decision"] == "renamed"
    assert decisions[0]["label_status"] == "none"


def test_export_predictions_supports_xgboost_and_empty_features(tmp_path):
    try:
        import xgboost as xgb
    except ImportError:
        return

    rng = np.random.default_rng(42)
    x_pos = np.ones((20, len(FEATURE_NAMES)), dtype=np.float32)
    x_neg = np.zeros((20, len(FEATURE_NAMES)), dtype=np.float32)
    x_train = np.vstack([x_pos, x_neg]) + rng.normal(0.0, 0.05, size=(40, len(FEATURE_NAMES))).astype(np.float32)
    y_train = np.array([1] * 20 + [0] * 20, dtype=np.uint8)
    clf = xgb.XGBClassifier(n_estimators=5, max_depth=2, random_state=42)
    clf.fit(x_train, y_train)
    model_path = tmp_path / "xgboost_model.json"
    clf.save_model(str(model_path))

    spec = load_model_spec(model_path)
    assert spec["model_type"] == "xgboost"
    assert score_features(spec, np.empty((0, len(FEATURE_NAMES)), dtype=np.float32)).size == 0

    entries = [
        {
            "citation_key": "k1",
            "citation_title": "Attention Is All You Need",
            "citation_authors": ["Ashish Vaswani"],
            "citation_year": 2017,
            "bibtex_source": "m2_bibtex",
            "groundtruth_arxiv_id": "1706.03762",
            "label_kind": None,
            "member": None,
        },
        {
            "citation_key": "k_empty",
            "citation_title": "",
            "citation_authors": [],
            "citation_year": None,
            "bibtex_source": "missing",
            "groundtruth_arxiv_id": "",
            "label_kind": None,
            "member": None,
        },
    ]
    refs = [
        {"ref_arxiv_id": "1706.03762", "ref_title": "Attention Is All You Need", "ref_authors": ["Ashish Vaswani"], "ref_submission_date": "2017-06-12"},
        {"ref_arxiv_id": "2005.14165", "ref_title": "Language Models are Few-Shot Learners", "ref_authors": ["Tom Brown"], "ref_submission_date": "2020-05-28"},
    ]
    rows = rank_paper(("2501.00001", "test", entries, refs, spec))
    assert rows[0]["cand_1"] == "1706.03762"
    assert rows[0]["groundtruth_arxiv_id"] == "1706.03762"
    assert rows[1]["groundtruth_arxiv_id"] is None
    assert "cand_1" not in rows[1]
