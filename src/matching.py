"""Citation Matching Model & Evaluation Module.

Assigned to: Bảo (Pipeline Prep) & Khôi (Baseline Modeling)
Purpose:
    Match LaTeX/BibTeX citation keys to real arXiv IDs using feature engineering
    (title token similarity, author surname overlap, publication year delta)
    and evaluate Mean Reciprocal Rank (MRR@5) and Hit@K.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple


def normalize_title(text: str) -> str:
    """Lowercase and strip non-alphanumeric characters for clean string matching."""
    if not text:
        return ""
    text = re.sub(r'[^a-zA-Z0-9\s]', '', str(text).lower())
    return " ".join(text.split())


def extract_last_names(authors: List[str]) -> Set[str]:
    """Extract set of normalized lowercase surnames from author strings."""
    surnames = set()
    for a in authors:
        a_clean = re.sub(r'[^a-zA-Z\s]', '', str(a).strip())
        tokens = a_clean.split()
        if tokens:
            surnames.add(tokens[-1].lower())
    return surnames


def compute_author_overlap(authors_a: List[str], authors_b: List[str]) -> float:
    """Compute Jaccard similarity of author last names."""
    set_a = extract_last_names(authors_a)
    set_b = extract_last_names(authors_b)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def compute_token_cosine_similarity(text_a: str, text_b: str) -> float:
    """Compute pure-Python cosine similarity between word frequency vectors of two texts."""
    tokens_a = normalize_title(text_a).split()
    tokens_b = normalize_title(text_b).split()
    if not tokens_a or not tokens_b:
        return 0.0

    count_a = Counter(tokens_a)
    count_b = Counter(tokens_b)

    common = set(count_a.keys()) & set(count_b.keys())
    dot_product = sum(count_a[k] * count_b[k] for k in common)

    mag_a = math.sqrt(sum(v * v for v in count_a.values()))
    mag_b = math.sqrt(sum(v * v for v in count_b.values()))

    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return float(dot_product / (mag_a * mag_b))


class CitationMatcher:
    """Baseline Citation Matcher with weighted heuristic ranking."""

    def extract_features(
        self,
        bib_title: str,
        bib_authors: List[str],
        bib_year: Optional[int],
        ref_title: str,
        ref_authors: List[str],
        ref_year: Optional[int],
    ) -> List[float]:
        """Compute 4 core matching features between a citation entry and a reference."""
        norm_bib_title = normalize_title(bib_title)
        norm_ref_title = normalize_title(ref_title)

        # 1. Exact title match flag
        exact_match = 1.0 if (norm_bib_title and norm_bib_title == norm_ref_title) else 0.0

        # 2. Token cosine similarity
        cosine_sim = compute_token_cosine_similarity(norm_bib_title, norm_ref_title)

        # 3. Author last name overlap
        author_sim = compute_author_overlap(bib_authors, ref_authors)

        # 4. Normalized year diff
        year_diff = 1.0
        if bib_year and ref_year:
            year_diff = min(abs(bib_year - ref_year) / 10.0, 1.0)

        return [exact_match, cosine_sim, author_sim, year_diff]

    def rank_candidates(
        self,
        citation_entries: List[Dict[str, Any]],
        candidate_pool: List[Dict[str, Any]],
        top_k: int = 5,
    ) -> List[List[str]]:
        """Rank candidates for each citation entry and return top_k arXiv IDs."""
        ranked_results = []
        for c in citation_entries:
            scores = []
            for cand in candidate_pool:
                feats = self.extract_features(
                    bib_title=c.get("title", ""),
                    bib_authors=c.get("authors", []),
                    bib_year=c.get("year"),
                    ref_title=cand.get("ref_title", ""),
                    ref_authors=cand.get("ref_authors", []),
                    ref_year=cand.get("ref_year"),
                )
                # Weighted score heuristic
                score = feats[0] * 5.0 + feats[1] * 3.0 + feats[2] * 2.0 - feats[3] * 0.5
                scores.append((cand.get("ref_arxiv_id"), score))

            scores.sort(key=lambda x: x[1], reverse=True)
            top_ids = [s[0] for s in scores[:top_k]]
            while len(top_ids) < top_k:
                top_ids.append(None)
            ranked_results.append(top_ids)
        return ranked_results


def evaluate_mrr_at_k(predictions: List[List[str]], ground_truths: List[Optional[str]], k: int = 5) -> Dict[str, float]:
    """Calculate Mean Reciprocal Rank (MRR@K) and Hit@1, Hit@K."""
    reciprocal_ranks = []
    hit_1 = 0
    hit_k = 0
    valid_count = 0

    for preds, gt in zip(predictions, ground_truths):
        if not gt:
            continue
        valid_count += 1
        rr = 0.0
        for rank, cand in enumerate(preds[:k], start=1):
            if cand == gt:
                rr = 1.0 / rank
                if rank == 1:
                    hit_1 += 1
                hit_k += 1
                break
        reciprocal_ranks.append(rr)

    if valid_count == 0:
        return {"mrr@k": 0.0, "hit@1": 0.0, f"hit@{k}": 0.0, "count": 0}

    return {
        f"mrr@{k}": float(sum(reciprocal_ranks) / valid_count),
        "hit@1": float(hit_1 / valid_count),
        f"hit@{k}": float(hit_k / valid_count),
        "evaluated_citations": valid_count,
    }
