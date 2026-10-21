# arXiv Data Science Project: Milestone 1 - Thu thập dữ liệu

Kho lưu trữ mã nguồn đồ án môn Nhập môn Khoa học Dữ liệu (HCMUS).

## 1. Cấu trúc thư mục

```text
.
├── .gitignore               # Loại bỏ tệp dữ liệu, cache và thư mục tạm
├── README.md                # Tài liệu kỹ thuật và hướng dẫn sử dụng
├── plan.md                  # Bản phân công công việc chi tiết của nhóm
├── src/
│   ├── crawler.py           # Script chính điều phối quy trình (Phát)
│   ├── discovery.py         # Trích xuất metadata và phiên bản bài viết (Bảo)
│   ├── downloader.py        # Tải tệp nén mã nguồn từ export.arxiv.org (Khôi)
│   ├── extractor.py         # Giải nén archive, lọc lấy .tex và .bib (Khánh)
│   ├── references.py        # Thu thập trích dẫn từ Semantic Scholar (Bảo)
│   ├── utils.py             # Bộ điều phối rate limit, retry và ghi log (Khôi)
│   └── requirements.txt     # Danh sách thư viện phụ thuộc
```

Báo cáo kết quả đồ án được duy trì trong kho lưu trữ Jupyter Book riêng và xuất bản qua GitHub Pages theo yêu cầu môn học. Kho lưu trữ này chỉ chứa mã nguồn công cụ.

## 2. Quy trình xử lý và liên kết giữa các module

Quy trình thu thập dữ liệu gồm các giai đoạn tuần tự và song song:

1. **Kiểm tra checkpoint ban đầu**: Đọc tệp lưu vết để lọc bỏ các bài viết đã hoàn tất đầy đủ cả metadata, trích dẫn và các phiên bản mã nguồn.
2. **Khám phá thông tin (Giai đoạn 1)**: Gọi `discovery.discover_papers_batch` theo từng cụm 50 đến 100 ID để lấy danh sách phiên bản và thông tin bài báo, lưu vào `metadata.json`.
3. **Thu thập nội dung (Giai đoạn 2)**: 
   - Tải tệp nén mã nguồn qua `downloader.download_source` với giãn cách tối thiểu 3 giây.
   - Giải nén có chọn lọc qua `extractor.extract_tex_bib` vào các thư mục `v1/`, `v2/`. Chỉ giữ tệp `.tex` và `.bib`. Nếu bài viết nộp dạng PDF thuần, tạo thư mục rỗng và ghi nhận trạng thái.
   - Gọi `references.get_references` để lấy danh sách trích dẫn từ Semantic Scholar, lưu vào `references.json`.
4. **Xác nhận hoàn tất**: Khi một bài có đầy đủ `metadata.json`, `references.json` và toàn bộ các phiên bản đã được giải nén hợp lệ, ghi mã ID bài viết vào `checkpoint.txt` theo phương thức ghi nguyên tử.

### Quy ước kỹ thuật giữa các module

- **Discovery ([discovery.py](file:///c:/Users/QuangPhat/Documents/HCMUS/Third/Data%20Science/Project/src/discovery.py))**: Dùng thư viện `arxiv`. Truy vấn theo danh sách ID để giảm thời gian chờ mạng. Trả về thông tin bài viết dạng từ điển hoặc `None` nếu bài không tồn tại.
- **Downloader ([downloader.py](file:///c:/Users/QuangPhat/Documents/HCMUS/Third/Data%20Science/Project/src/downloader.py))**: Gửi request đến `https://export.arxiv.org/src/{versioned_id}` kèm User-Agent định danh nhóm. Ghi dữ liệu trực tiếp vào tệp tạm bằng cơ chế stream để tối ưu bộ nhớ. Xử lý mã 404 bằng cách thông báo không có mã nguồn TeX. Khi gặp mã 403, 429 hoặc lỗi mạng tạm thời, thực hiện thử lại theo thuật toán exponential backoff.
- **Extractor ([extractor.py](file:///c:/Users/QuangPhat/Documents/HCMUS/Third/Data%20Science/Project/src/extractor.py))**: Trả về `ExtractionResult.SUCCESS` khi trích xuất được tệp LaTeX, `ExtractionResult.PDF_ONLY` khi bài viết chỉ có PDF, hoặc `ExtractionResult.FAILED` khi tệp nén lỗi. Giữ nguyên nội dung bên trong tệp `.tex`, không xóa thẻ nhúng hình ảnh.
- **References ([references.py](file:///c:/Users/QuangPhat/Documents/HCMUS/Third/Data%20Science/Project/src/references.py))**: Trích xuất thông tin bài viết được trích dẫn. Trả về danh sách rỗng khi gặp mã 404 (bài viết chưa được Semantic Scholar đánh chỉ mục).
- **Utils ([utils.py](file:///c:/Users/QuangPhat/Documents/HCMUS/Third/Data%20Science/Project/src/utils.py))**: Dùng `time.monotonic()` tính khoảng cách giữa hai lượt request liên tiếp. Chỉ tạm dừng đúng khoảng thời gian còn thiếu để đảm bảo giãn cách 3 giây với arXiv và 1 giây với Semantic Scholar.

## 3. Cài đặt môi trường

Yêu cầu Python từ phiên bản 3.10 trở lên.

```bash
# 1. Tạo môi trường ảo
python -m venv venv

# Kích hoạt trên Windows:
.\venv\Scripts\activate
# Kích hoạt trên Linux hoặc macOS:
source venv/bin/activate

# 2. Cài đặt các thư viện cần thiết
pip install -r src/requirements.txt
```

## 4. Hướng dẫn chạy chương trình

### Dải ID trong cùng một tháng

```bash
# Dải của Phát (Tháng 05/2025: 10666 đến 15665)
python src/crawler.py --month 2505 --start 10666 --end 15665 --output ./data

# Dải của Khôi (Tháng 06/2025: 5788 đến 10787)
python src/crawler.py --month 2506 --start 5788 --end 10787 --output ./data

# Dải của Khánh (Tháng 03/2025: 1914 đến 6913)
python src/crawler.py --month 2503 --start 1914 --end 6913 --output ./data
```

### Dải ID xuyên hai tháng

Với dải bài kéo dài qua hai tháng như của Bảo (từ cuối tháng 03/2025 sang đầu tháng 04/2025), cần cung cấp thêm `--start-month-max` (số thứ tự thực tế lớn nhất của tháng 03) nhằm tránh sinh ra các ID không tồn tại:

```bash
python src/crawler.py --month 2503 --start 21914 --end-month 2504 --end 2522 --start-month-max 26500 --output ./data
```

### Các tùy chọn bổ sung

- `--s2-api-key <KEY>`: Sử dụng khóa API của Semantic Scholar để ổn định tốc độ và tránh bị giới hạn request.
- `--batch-size <N>`: Số lượng bài viết gom nhóm trong một lượt truy vấn metadata (mặc định: 100).
- `--no-resume`: Bỏ qua dữ liệu checkpoint để chạy lại từ đầu.
- `--log-file crawl.log`: Ghi nhận nhật ký chạy vào tệp văn bản.

## 5. Quy định phối hợp nhóm

1. Mỗi thành viên làm việc trên nhánh tính năng riêng: `feat/member1-downloader`, `feat/member3-discovery`, `feat/member4-extractor`.
2. Không đẩy thư mục dữ liệu `data/` và các tệp nén tạm thời lên GitHub.
3. Tạo Pull Request vào nhánh `main` để Phát kiểm tra mã nguồn trước khi tích hợp.
