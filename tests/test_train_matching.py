import numpy as np

from src.train_matching import _process_paper_chunk, evaluate_queries, tune_threshold


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
    assert metrics["mrr@5"] == 0.25
    assert metrics["hit@5"] == 0.25
