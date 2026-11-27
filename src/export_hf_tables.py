"""Rebuild the five Milestone 1 and 2 Parquet tables for Hugging Face."""

import argparse
import json
import os
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.parquet as pq

from src.aggregate import collect_paper_dirs
from src.run_m2_pipeline import process_single_paper


ARXIV_ID = pa.field("arxiv_id", pa.string(), nullable=False)
STRINGS = pa.list_(pa.string())
CATEGORY = pa.dictionary(pa.int32(), pa.string())
SCHEMAS = {
    "papers": pa.schema([
        ARXIV_ID, ("title", pa.string()), ("authors", STRINGS),
        ("submission_date", pa.string()), ("revised_dates", STRINGS), ("venue", pa.string()),
    ]),
    "references": pa.schema([
        ARXIV_ID, pa.field("ref_arxiv_id", pa.string(), nullable=False),
        ("ref_title", pa.string()), ("ref_authors", STRINGS),
        ("ref_submission_date", pa.string()), ("ref_s2_id", pa.string()),
    ]),
    "elements": pa.schema([
        pa.field("element_id", pa.string(), nullable=False), ARXIV_ID, ("kind", CATEGORY),
        ("content", pa.string()),
    ]),
    "hierarchy": pa.schema([
        ARXIV_ID, ("version", pa.int32()), pa.field("element_id", pa.string(), nullable=False),
        pa.field("parent_id", pa.string(), nullable=False),
    ]),
    "bibtex": pa.schema([
        ARXIV_ID, pa.field("citation_key", pa.string(), nullable=False), ("entry_type", CATEGORY),
        ("title", pa.string()), ("authors", STRINGS), ("year", pa.int32()),
        ("doi", pa.string()), ("journal", pa.string()), ("url", pa.string()),
    ]),
}
PAPERS_PER_SHARD = 250


def append_paper(rows, arxiv_id, paper):
    metadata = paper["paper_meta"]
    if metadata is None or metadata["arxiv_id"] != arxiv_id:
        raise ValueError(f"Missing or inconsistent metadata for {arxiv_id}")
    rows["papers"].append(metadata)

    refs = {}
    for ref in paper["references"]:
        refs.setdefault(ref["ref_arxiv_id"], ref)
    rows["references"].extend(refs.values())

    elements = {element[0]: element for element in paper["elements"]}
    edges = dict.fromkeys(paper["hierarchy"])
    for _, version, element_id, parent_id in edges:
        if element_id not in elements or (parent_id != arxiv_id and parent_id not in elements):
            raise ValueError(f"Dangling hierarchy edge in {arxiv_id} v{version}: {element_id}, {parent_id}")
    rows["elements"].extend(dict(zip(SCHEMAS["elements"].names, row)) for row in elements.values())
    rows["hierarchy"].extend(dict(zip(SCHEMAS["hierarchy"].names, row)) for row in edges)

    entries = paper["bibtex"]
    keys = {row["citation_key"] for row in entries}
    if len(keys) != len(entries) or any(not key for key in keys):
        raise ValueError(f"Invalid or duplicate BibTeX key in {arxiv_id}")
    rows["bibtex"].extend(entries)


def export_tables(data_dirs, output_dir, workers):
    missing_dirs = [str(path) for path in data_dirs if not path.is_dir()]
    if missing_dirs:
        raise ValueError(f"Data directories not found: {missing_dirs}")
    papers = sorted(collect_paper_dirs(data_dirs).items())
    if not papers:
        raise ValueError("No paper directories with metadata.json found")
    if output_dir.exists():
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    row_counts = Counter()
    coverage = Counter()
    errors = []
    missing_references = []
    with TemporaryDirectory(dir=output_dir.parent) as temp, ProcessPoolExecutor(max_workers=workers) as pool:
        staging = Path(temp) / "dataset"
        for table in SCHEMAS:
            (staging / "data" / table).mkdir(parents=True)
        for offset in range(0, len(papers), PAPERS_PER_SHARD):
            batch = papers[offset:offset + PAPERS_PER_SHARD]
            rows = {name: [] for name in SCHEMAS}
            for (arxiv_id, path), paper in zip(batch, pool.map(process_single_paper, (str(p) for _, p in batch))):
                append_paper(rows, arxiv_id, paper)
                coverage.update(version["status"] for version in paper["coverage"])
                errors.extend(paper["errors"])
                if not (path / "references.json").is_file():
                    missing_references.append(arxiv_id)

            for name, schema in SCHEMAS.items():
                table = pa.Table.from_pylist(rows[name], schema=schema)
                shard = staging / "data" / name / f"part-{offset // PAPERS_PER_SHARD:05d}.parquet"
                pq.write_table(table, shard, compression="zstd")
                if not pq.read_schema(shard).equals(schema):
                    raise ValueError(f"Parquet schema changed while writing {shard}")
                row_counts[name] += table.num_rows
            print(f"Exported {offset + len(batch)}/{len(papers)} papers", flush=True)

        (staging / "audit.json").write_text(json.dumps({
            "source_papers": len(papers),
            "rows": dict(row_counts),
            "version_coverage": dict(coverage),
            "papers_missing_references_file": missing_references,
            "errors": errors,
        }, indent=2) + "\n", encoding="utf-8")
        staging.rename(output_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", nargs="+", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    export_tables(args.data_dir, args.output_dir, args.workers)


if __name__ == "__main__":
    main()
