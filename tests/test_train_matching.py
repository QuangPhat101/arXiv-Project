import numpy as np
import pyarrow as pa

from src.export_predictions import PREDICTIONS_SCHEMA, rank_paper
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
