import unittest
from src.matching import (
    normalize_title,
    compute_author_overlap,
    compute_raw_similarity,
    compute_char_ngram_similarity,
    compute_year_score,
    detect_roman_mismatch,
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

    def test_compute_raw_similarity(self):
        s1 = "Attention Is All You Need"
        s2 = "Attention Is All You Need"
        self.assertAlmostEqual(compute_raw_similarity(s1, s2), 1.0)

        # SequenceMatcher is sensitive to word reordering on longer sentences
        order1 = "Convolutional neural network for video super resolution"
        order2 = "Video super resolution with convolutional neural network"
        self.assertLess(compute_raw_similarity(order1, order2), 0.60)

    def test_compute_char_ngram_similarity_permutation_and_typo(self):
        # Char n-gram handles word reordering much better than raw sequence matcher
        order1 = "Video super-resolution with CNN"
        order2 = "CNN for video super-resolution"
        ngram_sim = compute_char_ngram_similarity(order1, order2)
        self.assertGreater(ngram_sim, 0.70)

        # Char n-gram handles spacing / glued words like Qwen2. 5 vs Qwen2.5
        glued1 = "Qwen2. 5: A New LLM Foundation"
        glued2 = "Qwen2.5: A New LLM Foundation"
        sim_typo = compute_char_ngram_similarity(glued1, glued2)
        self.assertGreater(sim_typo, 0.85)

    def test_compute_year_score(self):
        self.assertEqual(compute_year_score(2023, 2023), 1.0)
        self.assertGreaterEqual(compute_year_score(2023, 2024), 0.90)  # 1-year preprint delay tolerance
        self.assertLess(compute_year_score(2018, 2024), 0.50)
        self.assertEqual(compute_year_score(2023, None), 0.50)  # neutral fallback

    def test_detect_roman_mismatch(self):
        t1 = "Autonomous Driving: Part I Fundamentals"
        t2 = "Autonomous Driving: Part II Advanced Methods"
        t3 = "Autonomous Driving: Part I Fundamentals"
        self.assertTrue(detect_roman_mismatch(t1, t2))
        self.assertFalse(detect_roman_mismatch(t1, t3))

    def test_hybrid_ranking_handles_reordered_title_and_roman_numerals(self):
        c = [{
            "title": "Autonomous Driving Part I",
            "authors": ["John Doe"],
            "year": 2022
        }]
        pool = [
            # Candidate 1: Part II (should be penalized by roman mismatch)
            {"ref_title": "Autonomous Driving Part II", "ref_authors": ["John Doe"], "ref_year": 2022, "ref_arxiv_id": "2201.00002"},
            # Candidate 2: Part I (exact match)
            {"ref_title": "Autonomous Driving Part I", "ref_authors": ["John Doe"], "ref_year": 2022, "ref_arxiv_id": "2201.00001"},
        ]
        matcher = CitationMatcher()
        ranked = matcher.rank_candidates(c, pool, top_k=2)
        self.assertEqual(ranked[0][0], "2201.00001")

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
