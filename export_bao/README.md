---
license: cc-by-4.0
task_categories:
- text-classification
- feature-extraction
language:
- en
tags:
- arxiv
- scientific-papers
- citation-matching
size_categories:
- 1K<n<10K
---

# arXiv Dataset (Bảo's Partition: 2503.21914 -> 2504.02522)

This dataset contains parsed and normalized metadata, full section/sentence hierarchy, citations, and citation-matching prediction tables for 5,000 arXiv papers.

## Summary of Tables

| Table | File | Rows | Schema Highlights |
|:---|:---|---:|:---|
| `papers` | `papers.parquet` | 5,000 | `arxiv_id`, `title`, `authors`, `submission_date`, `revised_dates`, `venue` |
| `references` | `references.parquet` | 96,371 | `arxiv_id`, `ref_arxiv_id`, `ref_title`, `ref_authors`, `ref_submission_date`, `ref_s2_id` |
| `elements` | `elements.parquet` | 1,942,333 | `element_id`, `arxiv_id`, `kind`, `content` |
| `hierarchy` | `hierarchy.parquet` | 2,838,177 | `arxiv_id`, `version`, `element_id`, `parent_id` |
| `bibtex` | `bibtex.parquet` | 1,182,768 | `arxiv_id`, `citation_key`, `entry_type`, `title`, `authors`, `year`, `doi`, `journal`, `url` |
| `predictions` | `predictions.parquet` | 1,182,768 | `arxiv_id`, `partition` (train/valid/test), `citation_key`, `groundtruth_arxiv_id`, `cand_1`..`cand_5` |

## Data Curation & Pipeline
- **LaTeX Parsing**: Robust TeX tokenization, macro expansion (`\input`, `\include`), and sentence splitting preserving formulas, citations, and abbreviations.
- **Citation Key Alignment**: Normalized string matching and Jaccard deduplication across multiple revisions.
- **Reference Filtering**: Retained only verified arXiv-keyed citations from Semantic Scholar API.
