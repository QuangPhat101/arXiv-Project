# Kế hoạch thực hiện: Milestone 1 - Thu thập dữ liệu

Hạn chót: Tối 6/11/2026

## 1. Mục tiêu

Thu thập dữ liệu bài báo từ arXiv theo các dải ID được giao. Với mỗi bài:
- Lấy toàn bộ các phiên bản.
- Tải mã nguồn LaTeX, giải nén và chỉ giữ lại các tệp `.tex` và `.bib` (loại bỏ hình ảnh).
- Thu thập metadata của bài viết.
- Thu thập danh sách trích dẫn từ Semantic Scholar.

Sản phẩm bàn giao gồm hai bảng dữ liệu `papers` và `references`, trang báo cáo Jupyter Book trên GitHub Pages, và toàn bộ mã nguồn trên GitHub.

## 2. Cấu trúc mã nguồn

```text
<group-repo>/
├── src/
│   ├── crawler.py          # Điều phối quy trình thu thập dữ liệu
│   ├── discovery.py        # Trích xuất metadata bài viết và danh sách phiên bản
│   ├── downloader.py       # Tải tệp mã nguồn từ export.arxiv.org
│   ├── extractor.py        # Giải nén archive, lọc lấy .tex và .bib
│   ├── references.py       # Thu thập trích dẫn từ Semantic Scholar
│   ├── utils.py            # Quản lý rate limit, cơ chế thử lại và ghi log
│   └── requirements.txt
└── README.md
```

Quy định kỹ thuật cho từng tệp trong `src/`:

- `discovery.py`: Dùng thư viện `arxiv` (bản 4.x trở lên, cú pháp `client.results(search)`). Gọi batch `arxiv.Search(id_list=[...])` qua `arxiv.Client().results(search)` theo từng cụm 50 đến 100 ID để tiết kiệm thời gian mạng. Đọc `.entry_id` chứa hậu tố phiên bản mới nhất (ví dụ `2505.10666v3`) để suy ra danh sách phiên bản từ v1 đến v3. Trích xuất metadata chuẩn gồm: `arxiv_id`, `title`, `authors`, `submission_date`, `revised_dates`, `venue`. Lưu kết quả vào `metadata.json`.
- `downloader.py`: Tải mã nguồn từng phiên bản qua `https://export.arxiv.org/src/{versioned_id}`. Dùng `User-Agent` định danh nhóm. Không gửi request trực tiếp đến `arxiv.org` để tránh lỗi HTTP 403. Giãn cách tối thiểu 3 giây giữa các request.
- `extractor.py`: Giải nén tệp tải về và chỉ giữ lại `.tex`, `.bib`. Xử lý tệp `tar.gz` bằng `tarfile` (lọc tệp trước khi giải nén, kiểm tra tránh lỗi Zip Slip), tệp `gzip` đơn, và bài viết dạng PDF thuần (tạo thư mục rỗng và đánh dấu hoàn thành qua file `.complete` chứa `PDF_ONLY`). Không chỉnh sửa nội dung văn bản bên trong tệp `.tex`. Giữ nguyên các thẻ `\includegraphics` và môi trường `figure`.
- `references.py`: Gọi `GET https://api.semanticscholar.org/graph/v1/paper/arXiv:{base_id}` với tham số fields dạng phẳng chứa `references.title,references.authors,references.year,references.publicationDate,references.venue,references.externalIds`. Lấy `ref_arxiv_id` từ `externalIds.ArXiv`, `ref_s2_id` từ `paperId`. Lưu toàn bộ danh sách trích xuất thô vào `references.json`. Giữ nguyên định dạng ID cũ của arXiv (ví dụ `hep-th/9901001`). Xử lý mã 429 bằng thuật toán exponential backoff.
- `utils.py`: Cung cấp bộ rate limiter dùng chung bằng đồng hồ đơn điệu `time.monotonic()` (3 giây cho arXiv, 1 giây cho Semantic Scholar). Chỉ tính thời gian chờ cần thiết thay vì sleep cố định. Cung cấp decorator thử lại với exponential backoff và cấu hình ghi log.
- `crawler.py`: Tiếp nhận tham số dòng lệnh `--month`, `--start`, `--end`, `--output`. Quản lý cơ chế kiểm tra checkpoint hai lớp (cấp bài báo và cấp phiên bản) để chạy tiếp khi bị ngắt quãng. Đo lường kích thước archive trước khi xóa và kích thước `.tex`, `.bib` sau trích xuất để phục vụ báo cáo hiệu năng. Bắt lỗi cục bộ theo từng bài viết để tránh dừng toàn bộ quy trình.

## 3. Phân chia dải ID

| Thành viên | Tháng | ID bắt đầu | ID kết thúc | Ghi chú |
|:---|:---|:---|:---|:---|
| Khôi (Thành viên 1) | 2025-06 | 5788 | 10787 | Dải đơn tháng |
| Phát (Thành viên 2) | 2025-05 | 10666 | 15665 | Dải đơn tháng |
| Bảo (Thành viên 3) | 2025-03 sang 2025-04 | 21914 | 2522 | Dải xuyên tháng, cần `--start-month-max` |
| Khánh (Thành viên 4) | 2025-03 | 1914 | 6913 | Dải đơn tháng |

Cấu trúc thư mục kết quả của mỗi bài:

```text
data/2505.10666/
├── metadata.json
├── references.json
├── v1/
│   ├── main.tex
│   └── refs.bib
├── v2/
│   └── main.tex
└── ...
```

## 4. Đặc tả bảng dữ liệu đầu ra

Bảng `papers`:

| Cột | Kiểu dữ liệu | Mô tả |
|:---|:---|:---|
| `arxiv_id` | Chuỗi ký tự, không null | ID gốc của bài viết |
| `title` | Chuỗi ký tự | Tiêu đề bài viết |
| `authors` | Danh sách chuỗi ký tự | Tên các tác giả |
| `submission_date` | Chuỗi chuẩn ISO | Ngày nộp bản thảo đầu tiên |
| `revised_dates` | Danh sách chuỗi ký tự | Danh sách các mốc thời gian cập nhật |
| `venue` | Chuỗi ký tự, có thể null | Tạp chí xuất bản (`journal_ref`) nếu có |

Bảng `references` (chỉ lưu các dòng có `ref_arxiv_id`):

| Cột | Kiểu dữ liệu | Mô tả |
|:---|:---|:---|
| `arxiv_id` | Chuỗi ký tự, không null | ID bài viết trích dẫn |
| `ref_arxiv_id` | Chuỗi ký tự, không null | ID bài viết được trích dẫn trên arXiv |
| `ref_title` | Chuỗi ký tự | Tiêu đề bài viết được trích dẫn |
| `ref_authors` | Danh sách chuỗi ký tự | Tác giả bài viết được trích dẫn |
| `ref_submission_date` | Chuỗi ký tự | Ngày công bố |
| `ref_s2_id` | Chuỗi ký tự | Mã định danh Semantic Scholar |

## 5. Báo cáo Jupyter Book

Triển khai trên GitHub Pages từ một kho lưu trữ riêng biệt:

```text
<report-repo>/
├── myst.yml                  # Cấu hình Jupyter Book v2
├── milestone1/
│   ├── intro.md              # Giới thiệu đồ án
│   ├── implementation.md     # Tài liệu kiến trúc và xử lý ngoại lệ
│   ├── statistics.ipynb      # Thống kê tập dữ liệu bằng code tự sinh
│   └── performance.ipynb     # Đánh giá hiệu năng bằng code tự sinh
└── README.md
```

Nội dung báo cáo:
- Tài liệu kỹ thuật: Mô tả chi tiết quy trình cào, thư viện sử dụng, luồng xử lý và cách giải quyết các trường hợp biên.
- Thống kê dữ liệu: Tỷ lệ cào thành công, kích thước trung bình trước và sau khi lọc bỏ hình ảnh, số lượng trích dẫn trung bình, tỷ lệ bài có metadata trích dẫn.
- Đo lường hiệu năng trên môi trường Google Colab CPU: Thời gian xử lý từng bài và toàn bộ dải ID, lượng RAM tiêu thụ đỉnh và trung bình qua `psutil`, dung lượng đĩa sử dụng. Toàn bộ bảng biểu và đồ thị phải được xuất tự động từ code, không dùng ảnh chụp màn hình.

## 6. Phân công chi tiết

### Phát
1. Xây dựng khung mã nguồn toàn bộ repository `src/`: Thiết lập đầy đủ các hàm, kiểu dữ liệu trả về, docstring và hướng dẫn triển khai cho từng thành viên.
2. Hoàn thiện `crawler.py`: Xây dựng CLI tiếp nhận dải ID, cơ chế lưu vết checkpoint hai lớp, xử lý ngắt quãng và ghi log tổng kết.
3. Khởi tạo kho lưu trữ báo cáo Jupyter Book với cấu hình `myst.yml`.
4. Thu thập dữ liệu dải cá nhân (tháng 05/2025: 10666 đến 15665).
5. Viết nội dung `implementation.md` trong báo cáo.
6. Đánh giá mã nguồn và duyệt Pull Request từ các thành viên.

### Khôi
1. Hoàn thiện `utils.py`: Xây dựng bộ điều phối rate limit bằng `time.monotonic()`, decorator retry với exponential backoff và hàm thiết lập logger.
2. Hoàn thiện `downloader.py`: Xây dựng hàm tải mã nguồn qua `export.arxiv.org`, hỗ trợ stream dữ liệu vào tệp tạm và tái sử dụng session.
3. Thu thập dữ liệu dải cá nhân (tháng 06/2025: 5788 đến 10787).
4. Thực hiện đo lường hiệu năng trên Google Colab CPU với mẫu 100 đến 200 bài.
5. Viết nội dung `performance.ipynb` và phân tích các nút thắt cổ chai về thời gian mạng.

### Bảo
1. Hoàn thiện `discovery.py`: Tích hợp thư viện `arxiv`, hỗ trợ truy vấn gom lô qua `discover_papers_batch` để trích xuất metadata và danh sách phiên bản.
2. Hoàn thiện `references.py`: Gọi Semantic Scholar Graph API, bóc tách các trường dữ liệu trích dẫn và xử lý trường hợp bài chưa được đánh chỉ mục (HTTP 404).
3. Thu thập dữ liệu dải cá nhân (tháng 03/2025: 21914 sang tháng 04/2025: 2522).
4. Viết kịch bản tổng hợp dữ liệu từ 4 thành viên thành hai bảng `papers` và `references`. Kiểm tra tính toàn vẹn và làm sạch dữ liệu trùng lặp.
5. Tính toán các chỉ số thống kê và viết nội dung `statistics.ipynb`.

### Khánh
1. Hoàn thiện `extractor.py`: Xây dựng hàm giải nén có chọn lọc, chỉ lưu tệp `.tex` và `.bib`, xử lý trường hợp bài PDF thuần và phòng chống tấn công Zip Slip.
2. Thu thập dữ liệu dải cá nhân (tháng 03/2025: 1914 đến 6913).
3. Thiết lập GitHub Actions tự động build và xuất bản Jupyter Book lên GitHub Pages.
4. Viết mã nguồn vẽ biểu đồ phân tích trong các notebook báo cáo.
5. Soạn thảo phần giải thích biểu đồ và ghi nhận các trường hợp biên khi thu thập dữ liệu.

## 7. Kế hoạch thời gian

### Tuần 1 (20/10 đến 26/10): Thiết lập khung và hoàn thiện mã nguồn
- Phát: Dựng khung skeleton hai repository và hoàn thiện `crawler.py`.
- Khôi: Hoàn thiện `utils.py` và `downloader.py`, tạo Pull Request.
- Bảo: Hoàn thiện `discovery.py` và `references.py`, tạo Pull Request.
- Khánh: Hoàn thiện `extractor.py`, tạo Pull Request.
- Phát: Đánh giá mã nguồn và tích hợp vào nhánh chính.

### Tuần 2 (27/10 đến 02/11): Thu thập dữ liệu diện rộng
- Tất cả thành viên: Chạy bộ công cụ trên dải ID được giao.
- Khánh: Kiểm tra quy trình build và deploy GitHub Pages.

### Tuần 3 (03/11 đến 05/11): Hợp nhất dữ liệu và hoàn thiện báo cáo
- Bảo: Gộp dữ liệu thành hai bảng, tính toán số liệu và cập nhật `statistics.ipynb`.
- Khôi: Chạy đo lường trên Google Colab và cập nhật `performance.ipynb`.
- Khánh: Kiểm tra các biểu đồ tự sinh trong notebook báo cáo.
- Phát: Hoàn thiện `implementation.md` và rà soát toàn bộ báo cáo.

### Hạn nộp (Tối 06/11)
- Nộp đường dẫn repository mã nguồn và trang GitHub Pages lên Moodle.

## 8. Quy chuẩn làm việc

- Quản lý mã nguồn: Mỗi thành viên làm việc trên nhánh riêng, tạo Pull Request vào nhánh chính để rà soát trước khi gộp.
- Giới hạn tốc độ: Bắt buộc giãn cách 3 giây cho arXiv và 1 giây cho Semantic Scholar.
- Bảo mật dữ liệu: Không đẩy dữ liệu cào được lên kho lưu trữ mã nguồn.
- Tính toàn vẹn nội dung: Giữ nguyên mã nguồn LaTeX gốc, không xóa bỏ thẻ hình ảnh trong tệp `.tex`.
