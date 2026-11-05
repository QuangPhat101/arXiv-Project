# arXiv Data Science Project: Milestone 1 (Data Crawling)

Kho lưu trữ mã nguồn thu thập dữ liệu thuộc đồ án môn Nhập môn Khoa học Dữ liệu, HCMUS.

## 1. Cấu trúc thư mục

```text
.
├── .gitignore               # Loại bỏ tệp dữ liệu, cache và thư mục tạm
├── README.md                # Tài liệu kỹ thuật và hướng dẫn sử dụng
├── plan.md                  # Kế hoạch thực hiện chi tiết
├── src/
│   ├── crawler.py           # Điều phối quy trình thu thập dữ liệu (tuần tự và song song)
│   ├── discovery.py         # Trích xuất metadata và danh sách phiên bản bài viết
│   ├── downloader.py        # Tải tệp nén mã nguồn từ export.arxiv.org, hỗ trợ HTTP Range resume
│   ├── extractor.py         # Giải nén archive, lọc lấy tệp .tex và .bib
│   ├── references.py        # Thu thập trích dẫn từ Semantic Scholar API với cơ chế jitter
│   ├── profiler.py          # Thu thập telemetry, theo dõi RAM, phân bổ phase và đo lường benchmark
│   ├── utils.py             # Điều phối rate limit thread-safe, retry và ghi log
│   └── requirements.txt     # Danh sách thư viện phụ thuộc
└── tests/
    └── test_parallel_crawler.py # Kiểm thử đơn vị cho pipeline song song và concurrency
```

Báo cáo kết quả đồ án nằm ở kho lưu trữ Jupyter Book riêng và xuất bản qua GitHub Pages. Kho lưu trữ này quản lý mã nguồn công cụ và bộ kiểm thử.

## 2. Kiến trúc và quy trình xử lý

Chương trình có hai chế độ chạy: chạy tuần tự (baseline) để đo đối chứng và chạy song song ba giai đoạn (Producer-Consumer) để lấy dữ liệu nhanh hơn.

```text
[ Giai đoạn 1: Discovery Producer ]
            |
            | download_queue (Queue, maxsize=20, PaperDownloadJob)
            v
[ Giai đoạn 2: Download Workers Pool ]
            |
            | extract_s2_queue (Queue, maxsize=10, PaperProcessJob)
            v
[ Giai đoạn 3: Extract + S2 Workers Pool ]
```

Quy trình thực thi gồm các bước:

1. Kiểm tra checkpoint:
   - Cấp phiên bản: đọc tệp `.complete` trong từng thư mục phiên bản (`v1/`, `v2/`) để kiểm tra trạng thái trích xuất và số byte.
   - Cấp bài viết: đọc `checkpoint.txt` để bỏ qua các bài đã có đủ metadata, references và mã nguồn các phiên bản.
2. Giai đoạn 1 (Discovery Producer):
   - Gom các mã arXiv chưa có metadata cục bộ thành từng lô 100 bài (`--batch-size`) rồi gọi `discover_papers_batch` để lấy thông tin.
   - Đóng gói dữ liệu thành `PaperDownloadJob` và đưa vào `download_queue`.
3. Giai đoạn 2 (Download Workers Pool):
   - Nhóm worker tải mã nguồn từng phiên bản từ `export.arxiv.org/src/{versioned_id}` qua `requests.Session` dùng chung theo từng luồng.
   - Giãn cách tối thiểu giữa các lượt tải được quản lý qua `arxiv_rate_limiter`.
   - Nếu mạng chập chờn ngắt giữa chừng, worker giữ lại tệp tạm `.part`. Lần thử sau sẽ gửi header `Range: bytes={existing_bytes}-` để tải tiếp phần còn lại (HTTP 206 Partial Content).
   - Đóng gói dữ liệu và thời gian tải thành `PaperProcessJob` rồi chuyển sang `extract_s2_queue`.
4. Giai đoạn 3 (Extract + S2 Workers Pool):
   - Gọi `extractor.extract_tex_bib` để giải nén tệp `.tex` và `.bib`. Xóa tệp nén tạm ngay sau khi giải nén xong. Nếu bài nộp dạng PDF thuần (arXiv trả về 404), worker đánh dấu trạng thái `PDF_ONLY`.
   - Lấy danh sách trích dẫn từ Semantic Scholar qua `references.get_references`. Khi gặp mã 429, hệ thống áp dụng exponential backoff kết hợp thêm thời gian ngẫu nhiên (jitter) để tránh các luồng cùng gửi yêu cầu vào một thời điểm.
   - Cập nhật số liệu bài viết, ghi log qua `print_lock` và ghi nhận mã bài báo vào `checkpoint.txt` dưới khóa `state_lock`.

### Giao tiếp giữa các module

- [discovery.py](file:///c:/Users/QuangPhat/Documents/HCMUS/Third/Data%20Science/Project/src/discovery.py): Dùng thư viện `arxiv` phiên bản 4.x. Hỗ trợ truy vấn đơn lẻ `discover_paper` và truy vấn theo lô `discover_papers_batch`.
- [downloader.py](file:///c:/Users/QuangPhat/Documents/HCMUS/Third/Data%20Science/Project/src/downloader.py): Tải gói mã nguồn qua `https://export.arxiv.org/src/{versioned_id}` kèm User-Agent nhóm. Dùng tệp tạm `.part` và cờ `allow_resume` để nối tiếp luồng tải khi mạng đứt quãng.
- [extractor.py](file:///c:/Users/QuangPhat/Documents/HCMUS/Third/Data%20Science/Project/src/extractor.py): Trả về các giá trị `ExtractionResult.SUCCESS`, `ExtractionResult.PDF_ONLY`, hoặc `ExtractionResult.FAILED`. Kiểm tra đường dẫn để ngăn lỗi Zip Slip và giữ nguyên cú pháp nội dung tệp LaTeX.
- [references.py](file:///c:/Users/QuangPhat/Documents/HCMUS/Third/Data%20Science/Project/src/references.py): Đồng bộ thời gian chờ Semantic Scholar qua `_s2_lock`. Chế độ song song tăng `max_retries` lên 10 và bật cờ `use_jitter`.
- [utils.py](file:///c:/Users/QuangPhat/Documents/HCMUS/Third/Data%20Science/Project/src/utils.py): Lớp `RateLimiter` bọc `time.monotonic()` trong `threading.Lock()` để dùng an toàn trên nhiều luồng.
- [profiler.py](file:///c:/Users/QuangPhat/Documents/HCMUS/Third/Data%20Science/Project/src/profiler.py): Lớp `CrawlerProfiler` chạy nền để ghi nhận RAM qua `psutil`, đo thời gian từng giai đoạn (discovery, download, extract, s2_references, rate_limit_sleep), thống kê lỗi và xuất tệp JSON benchmark.
- [crawler.py](file:///c:/Users/QuangPhat/Documents/HCMUS/Third/Data%20Science/Project/src/crawler.py): Nhận tham số dòng lệnh và điều phối sang `run_parallel_pipeline` hoặc `run_sequential_pipeline`.

## 3. Cài đặt môi trường

Yêu cầu Python từ phiên bản 3.10 trở lên.

```bash
# 1. Tạo môi trường ảo
python -m venv venv

# Kích hoạt trên Windows:
.\venv\Scripts\activate
# Kích hoạt trên Linux hoặc macOS:
source venv/bin/activate

# 2. Cài đặt các thư viện phụ thuộc
pip install -r src/requirements.txt
```

## 4. Hướng dẫn chạy chương trình

### 4.1. Chạy chế độ song song

Chế độ song song dùng các worker pool riêng biệt để vừa tải mạng vừa giải nén và lấy trích dẫn:

```bash
# Chạy với cờ --parallel (mặc định 3 download workers)
python src/crawler.py --month 2505 --start 10666 --end 15665 --output ./data --parallel

# Hoặc truyền trực tiếp chuỗi arXiv ID đầy đủ
python src/crawler.py --start 2506.05788 --end 2506.10787 --output ./data --parallel

# Tùy chỉnh số lượng luồng cho từng giai đoạn
python src/crawler.py --month 2505 --start 10666 --end 15665 --download-workers 3 --s2-workers 2 --output ./data
```

### 4.2. Chạy chế độ tuần tự đối chứng (Baseline)

Dùng để so sánh hiệu năng giữa phiên bản đơn luồng và đa luồng:

```bash
python src/crawler.py --month 2505 --start 10666 --end 10765 --output ./data_baseline --baseline --profile --profile-output ./baseline_stats.json
```

### 4.3. Dải ID xuyên hai tháng

Khi dải bài kéo dài qua hai tháng (từ cuối tháng 03/2025 sang đầu tháng 04/2025), dùng thêm `--start-month-max` để giới hạn số bài thực tế của tháng đầu:

```bash
python src/crawler.py --month 2503 --start 21914 --end-month 2504 --end 2522 --start-month-max 26500 --output ./data --parallel
```

### 4.4. Bảng tham số dòng lệnh

| Tham số | Giá trị mặc định | Mô tả |
| :--- | :--- | :--- |
| `--start` | Bắt buộc | Số thứ tự bắt đầu (ví dụ: `10666`) hoặc mã arXiv đầy đủ (`2506.05788`) |
| `--end` | Bắt buộc | Số thứ tự kết thúc (ví dụ: `15665`) hoặc mã arXiv đầy đủ (`2506.10787`) |
| `--month` | `None` | Mã tháng 4 chữ số (ví dụ: `2505`). Tự động nhận diện nếu `--start` là mã đầy đủ |
| `--end-month` | `None` | Mã tháng kết thúc cho dải bài xuyên tháng (ví dụ: `2504`) |
| `--output`, `--output-dir` | `./data` | Thư mục lưu kết quả |
| `--parallel` | `False` | Bật chế độ chạy đường ống song song 3 giai đoạn |
| `--baseline` | `False` | Bật chế độ tuần tự gốc để đo đối chứng |
| `--n-workers` | `1` | Số lượng luồng worker tải mã nguồn |
| `--download-workers` | `None` | Số luồng tải mã nguồn riêng biệt (ghi đè `--n-workers`) |
| `--s2-workers` | `None` | Số luồng trích dẫn S2 và giải nén (mặc định: `min(n_workers, 4)`) |
| `--batch-size` | `100` | Số lượng bài viết gom nhóm mỗi lượt truy vấn metadata |
| `--s2-api-key` | `None` | Khóa API Semantic Scholar |
| `--no-resume` | `False` | Bỏ qua checkpoint và chạy lại từ đầu |
| `--profile` | `False` | Bật theo dõi RAM định kỳ và đo thời gian từng phần |
| `--profile-output`, `--stats-file` | `None` | Đường dẫn lưu tệp JSON kết quả đo lường profiler |
| `--log-file` | `None` | Đường dẫn lưu tệp log |

## 5. Kiểm thử hệ thống

Các ca kiểm thử đơn vị đặt trong thư mục `tests/` dùng để xác thực an toàn luồng, cơ chế cách ly lỗi và luồng Producer-Consumer:

```bash
python -m pytest tests/test_parallel_crawler.py -v
```

## 6. Quy định phối hợp nhóm

1. Mỗi thành viên làm việc trên nhánh tính năng riêng theo mẫu `feat/<tên-tính-năng>`.
2. Không commit thư mục dữ liệu `data/`, các tệp cache và tệp tạm vào Git.
3. Tạo Pull Request vào nhánh `main` và kiểm tra toàn bộ unit test trước khi gộp code.
