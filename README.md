# arXiv Data Science Project: Milestone 1 (Data Crawling)

Dự án thu thập dữ liệu bài báo khoa học từ kho lưu trữ mở arXiv và trích xuất trích dẫn từ Semantic Scholar, thuộc môn học Nhập môn Khoa học Dữ liệu tại Trường Đại học Khoa học Tự nhiên, ĐHQG-HCM (HCMUS).

## 1. Giới thiệu tổng quan

Hệ thống cung cấp giải pháp thu thập tự động cho tập bài báo theo dải mã arXiv được phân công:
- Khám phá metadata: Truy vấn API arXiv để lấy tiêu đề, tác giả, ngày công bố và danh sách tất cả các phiên bản từ v1 đến vN.
- Tải mã nguồn LaTeX: Thu thập toàn bộ các phiên bản mã nguồn thô từ export mirror chính thức của arXiv.
- Trích xuất chọn lọc: Giải nén và chỉ giữ lại các tệp `.tex` và `.bib`, loại bỏ hình ảnh và tệp nhị phân để tiết kiệm hơn 90% dung lượng lưu trữ.
- Thu thập trích dẫn: Tích hợp với Semantic Scholar Graph API để lấy thông tin các bài báo được trích dẫn.
- Xử lý song song: Hỗ trợ đường ống Producer-Consumer đa luồng, tối ưu hóa thời gian chờ mạng trong khi vẫn tuân thủ nghiêm ngặt các quy định về tần suất truy vấn.

## 2. Cấu trúc thư mục

```text
.
├── src/
│   ├── crawler.py           # Điểm vào chính, điều phối toàn bộ quy trình thu thập
│   ├── discovery.py         # Truy vấn metadata và phiên bản từ arXiv API
│   ├── downloader.py        # Tải mã nguồn bài báo, hỗ trợ tiếp tục tải khi gián đoạn
│   ├── extractor.py         # Giải nén chọn lọc tệp LaTeX, phòng chống lỗ hổng Zip Slip
│   ├── references.py        # Lấy dữ liệu trích dẫn từ Semantic Scholar API
│   ├── profiler.py          # Đo lường tài nguyên CPU, RAM và thời gian thực thi
│   ├── utils.py             # Bộ điều phối rate limit, retry và cấu hình logger
│   └── requirements.txt     # Danh sách thư viện phụ thuộc
├── tests/
│   └── test_parallel_crawler.py # Bộ kiểm thử cho luồng xử lý và an toàn đa luồng
├── plan.md                  # Kế hoạch thực hiện chi tiết của nhóm
└── README.md                # Tài liệu kỹ thuật dự án
```

## 3. Cài đặt môi trường

Yêu cầu Python từ phiên bản 3.10 trở lên.

```bash
# 1. Khởi tạo môi trường ảo
python -m venv venv

# Kích hoạt trên Windows:
.\venv\Scripts\activate
# Kích hoạt trên Linux hoặc macOS:
source venv/bin/activate

# 2. Cài đặt các thư viện cần thiết
pip install -r src/requirements.txt
```

## 4. Hướng dẫn sử dụng

### 4.1. Lệnh chạy nhanh (Khuyến nghị)

Chạy thu thập dữ liệu với chế độ song song bằng cờ `--parallel`:

```bash
# Chạy theo dải số thứ tự trong tháng
python src/crawler.py --month 2505 --start 10666 --end 15665 --output ./data --parallel

# Hoặc chạy trực tiếp với mã arXiv đầy đủ
python src/crawler.py --start 2506.05788 --end 2506.10787 --output ./data --parallel
```

### 4.2. Chế độ tuần tự đối chứng (Baseline)

Dùng cho việc đo lường hiệu năng đối chứng giữa bản tuần tự gốc và bản song song:

```bash
python src/crawler.py --month 2505 --start 10666 --end 10765 --output ./data_baseline --baseline --profile --stats-file ./baseline_stats.json
```

### 4.3. Dải bài xuyên tháng

Khi dải ID kéo dài qua hai tháng liên tiếp, sử dụng `--end-month` kết hợp `--start-month-max` để giới hạn số bài thực tế của tháng bắt đầu:

```bash
python src/crawler.py --month 2503 --start 21914 --end-month 2504 --end 2522 --start-month-max 26500 --output ./data --parallel
```

### 4.4. Bảng tham số dòng lệnh

| Tham số | Giá trị mặc định | Mô tả |
| :--- | :--- | :--- |
| `--start` | Bắt buộc | Số thứ tự bắt đầu (ví dụ: `10666`) hoặc mã arXiv đầy đủ (`2506.05788`) |
| `--end` | Bắt buộc | Số thứ tự kết thúc (ví dụ: `15665`) hoặc mã arXiv đầy đủ (`2506.10787`) |
| `--month` | `None` | Mã tháng 4 chữ số (ví dụ: `2505`). Tự động trích xuất nếu `--start` là mã đầy đủ |
| `--end-month` | `None` | Mã tháng kết thúc cho dải bài xuyên tháng (ví dụ: `2504`) |
| `--output`, `--output-dir` | `./data` | Thư mục lưu trữ dữ liệu đầu ra |
| `--parallel` | `False` | Bật chế độ chạy đường ống song song 3 giai đoạn |
| `--baseline` | `False` | Bật chế độ tuần tự gốc để đo benchmark đối chứng |
| `--n-workers` | `1` | Số lượng luồng worker tải mã nguồn |
| `--download-workers` | `None` | Số luồng tải mã nguồn riêng biệt (ghi đè `--n-workers`) |
| `--s2-workers` | `None` | Số luồng lấy trích dẫn S2 và giải nén (mặc định: `min(n_workers, 4)`) |
| `--batch-size` | `100` | Số lượng bài viết gom nhóm trong mỗi lượt truy vấn metadata |
| `--s2-api-key` | `None` | Khóa API của Semantic Scholar |
| `--no-resume` | `False` | Bỏ qua dữ liệu checkpoint và chạy lại từ đầu |
| `--profile` | `False` | Kích hoạt bộ đo lường tài nguyên RAM và phân bổ thời gian |
| `--profile-output`, `--stats-file` | `None` | Đường dẫn lưu tệp JSON kết quả đo lường profiler |
| `--log-file` | `None` | Đường dẫn ghi tệp nhật ký hệ thống |

## 5. Cấu trúc dữ liệu đầu ra

Mỗi bài báo sau khi thu thập thành công được tổ chức trong thư mục riêng biệt:

```text
data/2505.10666/
├── metadata.json       # Thông tin bài báo: tiêu đề, tác giả, ngày nộp, các phiên bản
├── references.json     # Danh sách các bài báo được trích dẫn từ Semantic Scholar
├── v1/                 # Mã nguồn phiên bản 1 (chỉ lưu tệp .tex và .bib)
│   ├── main.tex
│   └── refs.bib
├── v2/                 # Mã nguồn phiên bản 2
└── ...
```

Trạng thái hoàn thành được quản lý tự động qua `checkpoint.txt` và các tệp kiểm tra trạng thái trong từng phiên bản, giúp hệ thống tiếp tục công việc bình thường sau khi bị gián đoạn.

## 6. Kiểm thử

Dự án cung cấp bộ kiểm thử đơn vị tự động bao phủ các trường hợp biên, giải nén an toàn và an toàn đa luồng:

```bash
python -m pytest tests/ -v
```

## 7. Báo cáo đồ án

Báo cáo phân tích dữ liệu, thống kê tập ngữ liệu và đánh giá hiệu năng chi tiết được duy trì tại kho lưu trữ Jupyter Book riêng:
- Trang báo cáo: [arXiv-Report](https://quangphat101.github.io/arXiv-Report/)
- Mã nguồn báo cáo: [GitHub Repository](https://github.com/QuangPhat101/arXiv-Report)
