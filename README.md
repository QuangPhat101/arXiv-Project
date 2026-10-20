# arXiv Data Science Project — Milestone 1: Data Crawling

Kho lưu trữ mã nguồn cho đồ án môn học Nhập môn Khoa học Dữ liệu (HCMUS).

---

## 1. Cấu trúc thư mục (Repository Structure)

Cấu trúc repo tuân thủ đặc tả yêu cầu của đồ án:

```text
.
├── .gitignore               # Chặn commit dữ liệu thô, binary, cache
├── README.md                # Hướng dẫn thiết lập môi trường và chạy mã nguồn
├── id.md                    # Phân bổ dải ID arXiv cho từng thành viên
├── crawling.md              # Yêu cầu kỹ thuật chi tiết của Milestone 1
├── index.md                 # Tổng quan và logistics đồ án
├── src/
│   ├── __init__.py
│   ├── config.py            # Cấu hình tham số (endpoints, batch size, rate limits)
│   ├── discovery.py         # Entry discovery & version resolving (arXiv API)
│   ├── scraper.py           # Tải mã nguồn .tar.gz và lọc bỏ figure (.tex & .bib only)
│   ├── references.py        # Trích xuất trích dẫn qua Semantic Scholar API
│   ├── benchmark.py         # Đo đạc thời gian chạy (wall time) và bộ nhớ (RAM, Disk)
│   ├── pipeline.py          # Script chạy end-to-end cho 1 dải ID
│   └── requirements.txt     # Danh sách thư viện phụ thuộc
└── data/                    # Thư mục lưu dữ liệu cục bộ (ĐÃ BỊ CHẶN BỞI .gitignore)
```

> [!NOTE]
> Báo cáo của đồ án được duy trì trong một kho lưu trữ **Jupyter Book** độc lập và host trên GitHub Pages theo quy định môn học. Repo này chỉ phục vụ lưu trữ source code.

---

## 2. Quy định làm việc với GitHub (Git & GitHub Rules)

Để đảm bảo điểm số tiêu chí **Source Code** và phản ánh đúng tiến độ làm việc nhóm:

1. **Không commit dữ liệu và file nhị phân:**
   - Tuyệt đối **không** commit các thư mục dữ liệu (`data/`, `downloads/`, `.tar.gz`, file `.parquet`, file ảnh).
   - Repo chỉ chứa file mã nguồn (`.py`, `.ipynb`, `.md`, `.txt`, `.yml`).

2. **Quy tắc nhánh (Branching Strategy):**
   - Nhánh `main`: Chỉ chứa mã nguồn ổn định, đã kiểm thử.
   - Nhánh chức năng / thành viên: Mỗi thành viên tạo nhánh riêng khi phát triển:
     - `feat/member1-crawling`
     - `feat/member2-crawling`
     - `feat/discovery`
     - `feat/scraper`
     - `feat/references`
   - Hợp nhất code qua Pull Request (PR) có ít nhất 1 thành viên khác review.

3. **Lịch sử commit (Commit History):**
   - Commit thường xuyên, đều đặn qua từng giai đoạn để minh chứng quá trình làm việc nhóm.
   - Format commit message: `type(scope): description` (ví dụ: `feat(scraper): add tar extraction filter for tex and bib`, `fix(discovery): handle month rollover for member 3`).

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
# Chạy crawler cho dải ID cụ thể (ví dụ: Member 4)
python -m src.pipeline --start-month 2025-03 --start-id 1914 --end-month 2025-03 --end-id 6913

# Chạy kèm benchmark tài nguyên (RAM, CPU, Disk)
python -m src.benchmark --run-pipeline
```
