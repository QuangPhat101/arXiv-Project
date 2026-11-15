import unittest
from src.matching import (
    normalize_title,
    compute_author_overlap,
    CitationMatcher,
    evaluate_mrr_at_k,
)


class TestMatching(unittest.TestCase):
    def test_normalize_title(self):
        raw = "Attention Is All You Need!"
        self.assertEqual(normalize_title(raw), "attention is all you need")

    def test_compute_author_overlap(self):
        authors_a = ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"]
        authors_b = ["A. Vaswani", "N. Shazeer"]
        overlap = compute_author_overlap(authors_a, authors_b)
        self.assertGreater(overlap, 0.4)

    def test_rank_and_mrr(self):
        c = [{"title": "BERT: Pre-training of Deep Bidirectional Transformers", "authors": ["Jacob Devlin"], "year": 2018}]
        pool = [
            {"ref_title": "Attention Is All You Need", "ref_authors": ["Vaswani"], "ref_year": 2017, "ref_arxiv_id": "1706.03762"},
            {"ref_title": "BERT: Pre-training of Deep Bidirectional Transformers", "ref_authors": ["Devlin"], "ref_year": 2018, "ref_arxiv_id": "1810.04805"},
        ]
        matcher = CitationMatcher()
        ranked = matcher.rank_candidates(c, pool, top_k=5)
        self.assertEqual(ranked[0][0], "1810.04805")

        metrics = evaluate_mrr_at_k(ranked, ["1810.04805"], k=5)
        self.assertEqual(metrics["mrr@5"], 1.0)
        self.assertEqual(metrics["hit@1"], 1.0)


if __name__ == "__main__":
    unittest.main()
