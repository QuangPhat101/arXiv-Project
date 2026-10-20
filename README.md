# arXiv Data Science Project — Milestone 1: Data Crawling

Kho lưu trữ mã nguồn cho đồ án môn học Nhập môn Khoa học Dữ liệu (HCMUS).

---

## 1. Cấu trúc thư mục (Repository Structure)

```text
.
├── .gitignore               # Chặn commit dữ liệu thô, binary, cache
├── README.md                # Hướng dẫn thiết lập môi trường và chạy mã nguồn
├── plan.md                  # Phân công công việc nhóm
├── src/
│   ├── crawler.py           # Script chính điều phối pipeline
│   ├── discovery.py         # Entry discovery & version resolving (arXiv API)
│   ├── downloader.py        # Tải source archive từ export.arxiv.org
│   ├── extractor.py         # Giải nén tar.gz, chỉ giữ .tex & .bib
│   ├── references.py        # Trích xuất trích dẫn qua Semantic Scholar API
│   ├── utils.py             # Rate limiter, retry, logging
│   └── requirements.txt     # Danh sách thư viện phụ thuộc
└── data/                    # Thư mục lưu dữ liệu cục bộ (ĐÃ BỊ CHẶN BỞI .gitignore)
```

> [!NOTE]
> Báo cáo của đồ án được duy trì trong một kho lưu trữ **Jupyter Book** độc lập và host trên GitHub Pages theo quy định môn học. Repo này chỉ phục vụ lưu trữ source code.

---

## 2. Quy định làm việc với GitHub (Git & GitHub Rules)

1. **Không commit dữ liệu và file nhị phân:**
   - Tuyệt đối **không** commit các thư mục dữ liệu (`data/`, `downloads/`, `.tar.gz`, file `.parquet`, file ảnh).
   - Repo chỉ chứa file mã nguồn (`.py`, `.ipynb`, `.md`, `.txt`, `.yml`).

2. **Quy tắc nhánh (Branching Strategy):**
   - Nhánh `main`: Chỉ chứa mã nguồn ổn định, đã kiểm thử.
   - Mỗi thành viên tạo nhánh riêng khi phát triển, hợp nhất qua Pull Request (PR) có review.

3. **Lịch sử commit (Commit History):**
   - Commit thường xuyên, đều đặn để minh chứng quá trình làm việc nhóm.
   - Format commit message: `type(scope): description` (ví dụ: `feat(downloader): add retry on 429`, `fix(discovery): handle cross-month range`).

---

## 3. Cài đặt môi trường (Setup)

Yêu cầu: **Python 3.10+**

```bash
# 1. Tạo môi trường ảo
python -m venv venv

# Kích hoạt trên Windows:
.\venv\Scripts\activate
# Kích hoạt trên Linux/macOS:
source venv/bin/activate

# 2. Cài đặt dependencies
pip install -r src/requirements.txt
```

---

## 4. Hướng dẫn chạy mã nguồn (Execution)

Chạy pipeline crawl dữ liệu theo dải ID được giao:

```bash
python src/crawler.py --month 2505 --start 10666 --end 15665 --output ./data
```
