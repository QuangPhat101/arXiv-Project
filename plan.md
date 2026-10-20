# Phân Công Công Việc - Milestone 1: Data Crawling

Deadline: Tối 6/11/2026

---

## Mục tiêu Milestone 1

Cào dữ liệu từ arXiv: với mỗi paper trong dải ID được giao, lấy tất cả version, tải source LaTeX (chỉ giữ `.tex` và `.bib`, bỏ figure), lấy metadata, và cào reference qua Semantic Scholar. Kết quả cuối cùng gồm 2 bảng `papers` và `references`, một Jupyter Book report, và source code trên GitHub.

---

## Những gì cần làm (tổng thể)

### A. Source Code - Tool cào dữ liệu

Viết 1 bộ tool Python gồm các module:

```
<group-repo>/
├── src/
│   ├── crawler.py          # script chính, điều phối flow, nhận tham số dải ID
│   ├── discovery.py         # resolve ID -> metadata + detect số version
│   ├── downloader.py        # tải source từ export.arxiv.org
│   ├── extractor.py         # giải nén tar.gz, chỉ giữ .tex/.bib
│   ├── references.py        # query Semantic Scholar lấy references
│   ├── utils.py             # rate limiter, retry, logging
│   └── requirements.txt
└── README.md
```

`discovery.py` - Dùng `arxiv` (v4.x), query `arxiv.Search(id_list=[...])` qua `arxiv.Client().results(search)`. Từ `.entry_id` (chứa suffix version mới nhất, VD: `2505.10666v3` -> 3 version), parse ra list versioned IDs. Trích metadata: `title`, `authors`, `published`, `updated`, `journal_ref`. Lưu `metadata.json`.

`downloader.py` - Với mỗi versioned ID, tải từ `https://export.arxiv.org/src/{versioned_id}`. Set `User-Agent` mô tả. KHÔNG dùng `arxiv.org` (bị 403). Tuân thủ 3s delay.

`extractor.py` - Giải nén archive, chỉ giữ `.tex` và `.bib`. Xử lý: tar.gz (dùng `tarfile`, extract selective), gzip single-file, PDF-only (tạo thư mục rỗng). Không chỉnh nội dung `.tex` - giữ nguyên `\includegraphics`, `figure` environment.

`references.py` - Query `GET https://api.semanticscholar.org/graph/v1/paper/arXiv:{base_id}`, fields: `references.title`, `references.authors`, `references.year`, `references.publicationDate`, `references.venue`, `references.externalIds`. Trích `ref_arxiv_id` từ `externalIds.ArXiv`, `ref_s2_id` từ `paperId`. Lưu tất cả references vào `references.json`. Rate limit: 1 req/s, xử lý 429 bằng exponential backoff.

`utils.py` - Rate limiter dùng chung (3s arXiv, 1s Semantic Scholar). Retry với exponential backoff. Logging. Đây là module ảnh hưởng hiệu năng nhiều nhất - rate limit chiếm >90% thời gian chạy, nên viết thông minh (chỉ delay khi cần, không delay thừa).

`crawler.py` - Script chính, nhận tham số:
```bash
python crawler.py --month 2505 --start 10666 --end 15665 --output ./data
```
Flow: Generate IDs -> Discovery -> Download từng version -> Extract -> References. Có checkpoint/resume. Thứ tự gọi module và cách pipeline ảnh hưởng lớn đến performance.

### B. Cào dữ liệu - Mỗi người cào dải ID của mình

| Thành viên | Tháng | Start ID | End ID |
|:-----------|:------|:---------|:-------|
| Khôi (Member1) | 2025-06 | 5788 | 10787 |
| Phát (Member2) | 2025-05 | 10666 | 15665 |
| Bảo (Member3) | 2025-03 -> 2025-04 | 21914 | 2522 |
| Khánh (Member4) | 2025-03 | 1914 | 6913 |

Cấu trúc output mỗi paper:
```
2505-10666/
├── metadata.json
├── references.json
├── v1/
│   ├── main.tex
│   └── refs.bib
├── v2/
│   └── main.tex
└── ...
```

### C. Tổng hợp data - 2 bảng cuối cùng

Bảng `papers`:

| Column | Type |
|:-------|:-----|
| `arxiv_id` | string, non-null |
| `title` | string |
| `authors` | list of strings |
| `submission_date` | ISO string |
| `revised_dates` | list of strings |
| `venue` | string, nullable |

Bảng `references` (chỉ giữ row có `ref_arxiv_id`):

| Column | Type |
|:-------|:-----|
| `arxiv_id` | string, non-null (citing paper) |
| `ref_arxiv_id` | string, non-null |
| `ref_title` | string |
| `ref_authors` | list of strings |
| `ref_submission_date` | string |
| `ref_s2_id` | string (Semantic Scholar ID) |

### D. Report - Jupyter Book (GitHub Pages)

Repo riêng, deploy GitHub Pages. Link `github.io` nộp Moodle, không đổi sau nộp.

```
<report-repo>/
├── myst.yml                  # Config Jupyter Book v2 (thay _config.yml + _toc.yml)
├── milestone1/
│   ├── intro.md              # Giới thiệu project
│   ├── implementation.md     # Kiến trúc tool, pipeline, edge cases
│   ├── statistics.ipynb      # Thống kê data (tables + charts, auto-generate)
│   └── performance.ipynb     # Benchmark (tables + charts, auto-generate)
└── README.md
```

Nội dung bắt buộc:

1. Implementation: scraping hoạt động ra sao, tools/libraries dùng, flow xử lý, edge cases.

2. Thống kê (figures/tables tự generate, KHÔNG screenshot):
   - Số paper crawl thành công, overall success rate.
   - Kích thước trung bình paper (bytes) trước/sau bỏ figure.
   - Số references trung bình mỗi paper.
   - Tỷ lệ thành công cào reference metadata.

3. Performance - đo trên Google Colab CPU-only:
   - Running time: tổng 1 paper, trung bình mỗi paper, tổng entry discovery.
   - Memory: peak RAM (`psutil`), average RAM (sample định kỳ), max disk, final output size.

### E. Tiêu chí chấm điểm

1. Report: đủ thông tin, figures/tables tự generate?
2. Source Code: sạch, đọc được, chạy được?
3. Discovery & Crawling: đúng phương pháp, đủ version coverage?
4. Resulted Data: tỷ lệ thành công, data đúng format?
5. Scraper's Performance: hiệu năng so với nhóm khác?

---

## Phân công

### Phát 

1. Dựng skeleton toàn bộ repo code

Tạo repo GitHub public, tạo sẵn các file `.py` với skeleton: tên hàm, docstring, tham số, return type - chưa implement logic. Push lên để 3 người kia clone về code.

2. Code `crawler.py`

Script chính điều phối toàn bộ flow:
- Nhận tham số `--month`, `--start`, `--end`, `--output`.
- Generate list base IDs từ range.
- Với mỗi ID: gọi `discovery.discover_paper()` -> với mỗi version gọi `downloader.download_source()` -> `extractor.extract_tex_bib()` -> gọi `references.get_references()`.
- Checkpoint/resume: ghi file tracking paper đã xong, skip khi chạy lại. VD: kiểm tra thư mục đã tồn tại hoặc lưu `completed.txt`.
- Log tổng kết: thành công / fail / lý do fail.
- Thiết kế pipeline thông minh: thứ tự gọi, xen kẽ hay tuần tự, xử lý error không dừng cả pipeline.

3. Dựng khung Jupyter Book

Tạo repo report riêng, config `myst.yml`, tạo file trống, build thử (`jupyter-book build --html`).

4. Cào data phần mình

Chạy tool cho dải `2025-05: 10666 -> 15665`.

5. Viết phần report

Viết `implementation.md`: kiến trúc tool, pipeline flow, rate limit, retry, checkpoint, quyết định kỹ thuật.

6. Review & merge PR

---

### Khôi 

1. Code `utils.py`

Module quan trọng nhất cho hiệu năng:
- Rate limiter dùng chung: đảm bảo khoảng cách tối thiểu giữa requests (3s arXiv, 1s Semantic Scholar). Viết thông minh - chỉ delay khi cần, tính thời gian đã trôi qua từ request trước, nếu đủ rồi thì không sleep thêm.
- Retry với exponential backoff: gặp 429/403/timeout -> chờ 2s, 4s, 8s,... tối đa N lần rồi skip + log.
- Logging: ghi tiến trình, paper thành công/fail, lý do fail.

2. Code `downloader.py`

- Implement hàm tải source từ `https://export.arxiv.org/src/{versioned_id}`.
- Dùng `urllib.request` hoặc `requests`.
- Set `User-Agent` header (VD: `ArxivCrawler/1.0 (HCMUS-DS-project)`).
- Gọi rate limiter từ `utils.py`.
- Xử lý lỗi: 404 (không tồn tại), 403 (bị block), timeout -> retry hoặc skip + log.
- Lưu file vào thư mục tạm.

3. Cào data phần mình

Chạy tool cho dải `2025-06: 5788 -> 10787`.

4. Benchmark performance trên Google Colab

Chạy benchmark trên Colab CPU-only với ~100-200 paper:
- Running time: `time.time()` đo tổng 1 paper, trung bình, riêng phase discovery.
- Peak RAM: `psutil.Process().memory_info().rss` hoặc `/usr/bin/time -v`.
- Average RAM: thread phụ sample `psutil` mỗi 5s, tính trung bình.
- Disk: `shutil.disk_usage()` hoặc `!du -sh ./data`.
- Final output size: tổng dung lượng output.

Khôi viết `utils.py` nên hiểu rõ rate limiter ảnh hưởng performance ra sao -> phân tích benchmark sâu hơn.

5. Viết phần report

Viết `performance.ipynb`: bảng + biểu đồ benchmark (tự generate), phân tích bottleneck.

---

### Bảo

1. Code `discovery.py`

- Dùng `arxiv` (v4.x): `arxiv.Search(id_list=[base_id])` -> `arxiv.Client().results(search)`.
- Đọc `.entry_id` -> parse suffix version (VD: URL chứa `v3` -> `["...v1", "...v2", "...v3"]`).
- Trích metadata: `title`, `authors` (list string), `published` -> `submission_date`, `updated` -> `revised_dates`, `journal_ref` -> `venue` (nullable).
- Lưu `metadata.json`.

2. Code `references.py`

- Query `GET https://api.semanticscholar.org/graph/v1/paper/arXiv:{base_id}`.
- Params: `fields=references.title,references.authors,references.year,references.publicationDate,references.venue,references.externalIds`.
- Parse response: trích `ref_title`, `ref_authors`, `ref_submission_date`, `ref_arxiv_id` (từ `externalIds.ArXiv`), `ref_s2_id` (từ `paperId`).
- Old-format arXiv ID (`hep-th/9901001`) -> giữ nguyên.
- Paper chưa index -> `references.json` rỗng `[]`.
- Rate limit 1 req/s, xử lý 429 bằng retry từ `utils.py`.

3. Cào data phần mình

Chạy tool cho dải `2025-03: 21914 -> 2025-04: 2522`.

Cross 2 tháng: `2503.21914` -> hết tháng 03, rồi `2504.00001` -> `2504.02522`. Phối hợp Phát nếu `crawler.py` cần hỗ trợ.

4. Tổng hợp data 4 người -> 2 bảng

Viết script merge:
- Đọc `metadata.json` × 4 -> bảng `papers` (schema mục C).
- Đọc `references.json` × 4 -> bảng `references` (chỉ row có `ref_arxiv_id`).
- Kiểm tra data quality: trùng, null, format.

5. Tính thống kê

Tổng paper thành công/thất bại, overall success rate, kích thước trung bình, số version trung bình, số ref trung bình, tỷ lệ ref có arXiv ID, tỷ lệ thành công Semantic Scholar.

6. Viết phần report

Viết `statistics.ipynb`: bảng + biểu đồ thống kê (tự generate), phân tích chất lượng data.

---

### Khánh

1. Code `extractor.py`

- Nhận file archive đã tải, giải nén + chỉ giữ `.tex` và `.bib`.
- Kiểm tra loại file:
  - tar.gz: `tarfile.open()`, duyệt members, chỉ extract file đuôi `.tex`/`.bib` vào `v{n}/`.
  - gzip single-file: `gzip.open()`, kiểm tra nếu `.tex` thì lưu.
  - PDF-only / format lạ: tạo `v{n}/` rỗng, log lại.
- Không chỉnh sửa nội dung `.tex`: giữ nguyên `\includegraphics`, `figure`.

2. Cào data phần mình

Chạy tool cho dải `2025-03: 1914 -> 6913`.

3. Deploy Jupyter Book lên GitHub Pages

- Config GitHub Actions auto-build + deploy.
- Đảm bảo link `https://<username>.github.io/<report-repo>` ổn định - nộp Moodle, không đổi.
- Test `jupyter-book build --html` không lỗi.
- Viết `README.md` report repo.

4. Tạo biểu đồ trong report

Viết code generate biểu đồ (`matplotlib`/`plotly`) trong notebook:
- Bar chart: paper thành công vs thất bại, chia 4 thành viên.
- Histogram: phân bố số version.
- Bar chart: kích thước trung bình.
- Bar chart: số references trung bình.
- Pie chart: tỷ lệ ref có arXiv ID vs không.
- Bar/line chart: running time & memory.

Đọc data từ file Bảo tổng hợp, tự generate khi build - KHÔNG screenshot.

5. Viết phần report

Giải thích biểu đồ + document edge cases gặp khi cào.

---


## Timeline

### Tuần 1 (20/10 -> 26/10): Setup & code
- Phát: dựng skeleton 2 repo, push. Code `crawler.py`.
- Khôi: code `utils.py` + `downloader.py`, tạo PR.
- Bảo: code `discovery.py` + `references.py`, tạo PR.
- Khánh: code `extractor.py`, tạo PR.
- Phát: review + merge PR.

### Tuần 2 (27/10 -> 2/11): Cào data
- Tất cả: chạy tool cào data dải ID của mình.
- Khánh: deploy Jupyter Book lên GitHub Pages.

### Tuần 3 (3/11 -> 5/11): Tổng hợp & report
- Bảo: merge data -> 2 bảng, thống kê, viết `statistics.ipynb`.
- Khôi: benchmark Colab, viết `performance.ipynb`.
- Khánh: tạo biểu đồ, viết phần report.
- Phát: viết `implementation.md`, review toàn bộ.

### Tối 6/11: Deadline
- Nộp link repo code + link GitHub Pages lên Moodle.

---

## Quy tắc

- Git: mỗi người branch riêng, PR vào `main` để Phát review.
- Rate limit: 3s arXiv, 1 req/s Semantic Scholar.
- Không commit data vào repo code.
- Giữ nguyên LaTeX: không xóa `\includegraphics`, `figure` trong `.tex`.
- Blockers: báo ngay group chat.
