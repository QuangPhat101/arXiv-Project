"""Citation Matching Model & Evaluation Module.

Implements Hybrid Citation Matching combining:
1. Raw sequence matching (SequenceMatcher) - captures contiguous word/char ordering.
2. Character n-gram TF-IDF cosine similarity - robust against word reordering, typos, spacing.
3. Author surname overlap (Jaccard similarity).
4. Publication year delta scoring (with tolerance for preprint vs publication latency).
5. Roman numeral / Part mismatch penalty (e.g. Part I vs Part II).
"""

from __future__ import annotations

import difflib
import math
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple

ROMAN_NUMERALS: Dict[str, int] = {
    "i": 1,
    "ii": 2,
    "iii": 3,
    "iv": 4,
    "v": 5,
    "vi": 6,
    "vii": 7,
    "viii": 8,
    "ix": 9,
    "x": 10,
}


def normalize_title(text: str) -> str:
    """Lowercase and strip non-alphanumeric characters for clean string matching."""
    if not text:
        return ""
    text = re.sub(r"[^a-zA-Z0-9\s]", " ", str(text).lower())
    return " ".join(text.split())


def compute_raw_similarity(title_a: str, title_b: str) -> float:
    """Compute character-level raw sequence similarity using difflib.SequenceMatcher.
    
    Preserves strict word ordering and character sequence contiguity.
    """
    norm_a = normalize_title(title_a)
    norm_b = normalize_title(title_b)
    if not norm_a or not norm_b:
        return 0.0
    if norm_a == norm_b:
        return 1.0
    return float(difflib.SequenceMatcher(None, norm_a, norm_b).ratio())


def extract_char_ngrams(text: str, n_min: int = 3, n_max: int = 4) -> Counter:
    """Extract character n-grams from normalized text."""
    norm = normalize_title(text)
    if not norm:
        return Counter()
    if len(norm) < n_min:
        return Counter([norm])

    ngrams: List[str] = []
    for n in range(n_min, n_max + 1):
        if len(norm) >= n:
            ngrams.extend(norm[i : i + n] for i in range(len(norm) - n + 1))
    return Counter(ngrams)


def build_idf_dict(corpus_titles: List[str], n_min: int = 3, n_max: int = 4) -> Dict[str, float]:
    """Compute smooth inverse document frequency (IDF) for char n-grams over corpus titles."""
    num_docs = len(corpus_titles)
    if num_docs == 0:
        return {}

    df_counter: Counter = Counter()
    for t in corpus_titles:
        unique_ngrams = set(extract_char_ngrams(t, n_min, n_max).keys())
        df_counter.update(unique_ngrams)

    idf_dict: Dict[str, float] = {}
    for ngram, df in df_counter.items():
        # Standard smoothed IDF: ln((1 + N) / (1 + df)) + 1.0
        idf_dict[ngram] = math.log((1.0 + num_docs) / (1.0 + df)) + 1.0

    return idf_dict


def compute_char_ngram_similarity(
    title_a: str,
    title_b: str,
    n_min: int = 3,
    n_max: int = 4,
    idf_dict: Optional[Dict[str, float]] = None,
) -> float:
    """Compute TF-IDF cosine similarity using character n-grams (3-gram to 4-gram).
    
    Robust to word reordering, missing whitespaces ('Qwen2. 5' vs 'Qwen2.5'), and typos.
    Downweights common stop-patterns when idf_dict is provided.
    """
    count_a = extract_char_ngrams(title_a, n_min, n_max)
    count_b = extract_char_ngrams(title_b, n_min, n_max)

    if not count_a or not count_b:
        return 0.0

    # Build weighted vectors
    vec_a: Dict[str, float] = {}
    for k, count in count_a.items():
        weight = float(count) * (idf_dict.get(k, 1.0) if idf_dict else 1.0)
        vec_a[k] = weight

    vec_b: Dict[str, float] = {}
    for k, count in count_b.items():
        weight = float(count) * (idf_dict.get(k, 1.0) if idf_dict else 1.0)
        vec_b[k] = weight

    common = set(vec_a.keys()) & set(vec_b.keys())
    if not common:
        return 0.0

    dot_product = sum(vec_a[k] * vec_b[k] for k in common)
    mag_a = math.sqrt(sum(v * v for v in vec_a.values()))
    mag_b = math.sqrt(sum(v * v for v in vec_b.values()))

    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return float(min(1.0, dot_product / (mag_a * mag_b)))


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


def extract_last_names(authors: List[str]) -> Set[str]:
    """Extract set of normalized lowercase surnames from author strings."""
    surnames = set()
    for a in authors:
        a_clean = re.sub(r"[^a-zA-Z\s]", "", str(a).strip())
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
    return float(len(set_a & set_b) / len(set_a | set_b))


def compute_year_score(year_a: Optional[int], year_b: Optional[int]) -> float:
    """Score publication year agreement with soft tolerance for preprint vs conference delay."""
    if year_a is None or year_b is None:
        return 0.5  # Neutral fallback when publication year is missing

    diff = abs(int(year_a) - int(year_b))
    if diff == 0:
        return 1.0
    if diff == 1:
        return 0.90  # 1-year discrepancy is common between arXiv preprint and conference proceedings
    if diff == 2:
        return 0.60
    return float(max(0.0, 1.0 - 0.20 * diff))


def _extract_part_numbers(title: str) -> Set[int]:
    """Extract Part/Volume/Phase numerical indicators (both Roman and Arabic) from title."""
    parts = set()
    norm = str(title).lower()

    # Match patterns like 'part i', 'part 2', 'volume iii', 'phase 1'
    for match in re.finditer(r"\b(?:part|volume|vol|phase)\s*([ivx\d]+)\b", norm):
        val = match.group(1).strip()
        if val in ROMAN_NUMERALS:
            parts.add(ROMAN_NUMERALS[val])
        elif val.isdigit():
            parts.add(int(val))

    # Match standalone Roman numerals at end of title or after delimiters (: -)
    for match in re.finditer(r"(?:[:\-–—\s]|^)\s*([ivx]+)\s*$", norm):
        val = match.group(1).strip()
        if val in ROMAN_NUMERALS:
            parts.add(ROMAN_NUMERALS[val])

    return parts


def detect_roman_mismatch(title_a: str, title_b: str) -> bool:
    """Detect if title_a and title_b have contradictory Part/Volume Roman numerals."""
    parts_a = _extract_part_numbers(title_a)
    parts_b = _extract_part_numbers(title_b)

    if parts_a and parts_b:
        # Both specify a part number, check for disjoint contradiction
        return not bool(parts_a & parts_b)
    return False


class CitationMatcher:
    """Hybrid Citation Matcher combining raw sequence matching, char n-gram TF-IDF,
    author surname overlap, year delta, and Roman numeral tie-breaking.
    """

    def __init__(
        self,
        weight_raw: float = 0.35,
        weight_ngram: float = 0.35,
        weight_author: float = 0.20,
        weight_year: float = 0.10,
        penalty_roman: float = 0.35,
    ) -> None:
        self.weight_raw = weight_raw
        self.weight_ngram = weight_ngram
        self.weight_author = weight_author
        self.weight_year = weight_year
        self.penalty_roman = penalty_roman

    def compute_hybrid_score(
        self,
        bib_title: str,
        bib_authors: List[str],
        bib_year: Optional[int],
        ref_title: str,
        ref_authors: List[str],
        ref_year: Optional[int],
        idf_dict: Optional[Dict[str, float]] = None,
    ) -> float:
        """Compute composite hybrid score between a citation entry and a candidate reference."""
        # 1. Raw string SequenceMatcher
        raw_sim = compute_raw_similarity(bib_title, ref_title)

        # 2. Character n-gram TF-IDF cosine similarity
        ngram_sim = compute_char_ngram_similarity(bib_title, ref_title, idf_dict=idf_dict)

        # 3. Author surname Jaccard overlap
        author_sim = compute_author_overlap(bib_authors, ref_authors)

        # 4. Publication year agreement score
        year_score = compute_year_score(bib_year, ref_year)

        # 5. Roman numeral / Part mismatch penalty
        is_roman_conflict = detect_roman_mismatch(bib_title, ref_title)
        roman_penalty = self.penalty_roman if is_roman_conflict else 0.0

        # Exact title shortcut bonus
        exact_bonus = 0.10 if (raw_sim >= 0.98 and ngram_sim >= 0.98) else 0.0

        total_score = (
            self.weight_raw * raw_sim
            + self.weight_ngram * ngram_sim
            + self.weight_author * author_sim
            + self.weight_year * year_score
            + exact_bonus
            - roman_penalty
        )
        return float(total_score)

    def extract_features(
        self,
        bib_title: str,
        bib_authors: List[str],
        bib_year: Optional[int],
        ref_title: str,
        ref_authors: List[str],
        ref_year: Optional[int],
    ) -> List[float]:
        """Feature extraction for backward compatibility and analysis."""
        norm_bib = normalize_title(bib_title)
        norm_ref = normalize_title(ref_title)
        exact_match = 1.0 if (norm_bib and norm_bib == norm_ref) else 0.0
        raw_sim = compute_raw_similarity(bib_title, ref_title)
        ngram_sim = compute_char_ngram_similarity(bib_title, ref_title)
        author_sim = compute_author_overlap(bib_authors, ref_authors)
        year_score = compute_year_score(bib_year, ref_year)
        roman_mismatch = 1.0 if detect_roman_mismatch(bib_title, ref_title) else 0.0

        return [exact_match, raw_sim, ngram_sim, author_sim, year_score, roman_mismatch]

    def rank_candidates(
        self,
        citation_entries: List[Dict[str, Any]],
        candidate_pool: List[Dict[str, Any]],
        top_k: int = 5,
        require_arxiv_id: bool = True,
    ) -> List[List[Optional[str]]]:
        """Rank candidates for each citation entry and return top_k arXiv IDs.
        
        Args:
            citation_entries: List of citation dictionaries (title, authors, year).
            candidate_pool: Candidate references from Semantic Scholar or metadata.
            top_k: Number of ranked candidate arXiv IDs to return.
            require_arxiv_id: When True, filters candidate pool to entries with valid arXiv IDs.
        """
        # Build candidate pool to rank
        pool_to_rank = candidate_pool
        if require_arxiv_id:
            valid_pool = [c for c in candidate_pool if c.get("ref_arxiv_id")]
            if valid_pool:
                pool_to_rank = valid_pool

        # Precompute IDF dictionary over candidate titles
        candidate_titles = [c.get("ref_title", "") for c in pool_to_rank if c.get("ref_title")]
        idf_dict = build_idf_dict(candidate_titles) if candidate_titles else None

        ranked_results: List[List[Optional[str]]] = []
        for c in citation_entries:
            scores: List[Tuple[Optional[str], float]] = []
            for cand in pool_to_rank:
                score = self.compute_hybrid_score(
                    bib_title=c.get("title", ""),
                    bib_authors=c.get("authors", []),
                    bib_year=c.get("year"),
                    ref_title=cand.get("ref_title", ""),
                    ref_authors=cand.get("ref_authors", []),
                    ref_year=cand.get("ref_year"),
                    idf_dict=idf_dict,
                )
                scores.append((cand.get("ref_arxiv_id"), score))

            scores.sort(key=lambda x: x[1], reverse=True)
            top_ids: List[Optional[str]] = [s[0] for s in scores[:top_k]]
            while len(top_ids) < top_k:
                top_ids.append(None)
            ranked_results.append(top_ids)

        return ranked_results


def evaluate_mrr_at_k(
    predictions: List[List[Optional[str]]],
    ground_truths: List[Optional[str]],
    k: int = 5,
) -> Dict[str, float]:
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
