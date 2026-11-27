# arXiv Data Science Project: Milestone 1 (Data Crawling)

> Bản tích hợp M2: xem [task.md](task.md) để nhận việc, tạo nhánh sửa và chạy kiểm thử nghiệm thu.

Dự án thu thập dữ liệu bài báo khoa học từ kho lưu trữ mở arXiv và trích xuất trích dẫn từ Semantic Scholar, thuộc môn học Nhập môn Khoa học Dữ liệu tại Trường Đại học Khoa học Tự nhiên, ĐHQG-HCM (HCMUS).

## 1. Giới thiệu tổng quan

Hệ thống cung cấp giải pháp thu thập tự động cho tập bài báo theo dải mã arXiv được phân công:
- Khám phá metadata: Truy vấn API arXiv để lấy tiêu đề, tác giả, ngày công bố và danh sách tất cả các phiên bản từ v1 đến vN.
- Tải mã nguồn LaTeX: Thu thập toàn bộ các phiên bản mã nguồn thô từ export mirror chính thức của arXiv.
- Trích xuất chọn lọc: Giải nén và chỉ giữ lại các tệp `.tex` và `.bib`, loại bỏ hình ảnh và tệp nhị phân để tiết kiệm hơn 90% dung lượng lưu trữ.
- Thu thập trích dẫn: Tích hợp với Semantic Scholar Graph API để lấy thông tin các bài báo được trích dẫn.
- Xử lý song song: Hỗ trợ cơ chế Producer-Consumer đa luồng, giúp tối ưu hóa thời gian chờ mạng trong khi vẫn tuân thủ nghiêm ngặt các quy định về tần suất truy vấn.

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

Chạy crawler thu thập dữ liệu bằng lệnh:

```bash
python src/crawler.py --month 2505 --start 10666 --end 15665 --output ./data --parallel
```

### Bảng tham số dòng lệnh

| Tham số | Giá trị mặc định | Mô tả |
| :--- | :--- | :--- |
| `--start` | Bắt buộc | Số thứ tự bắt đầu (ví dụ: `10666`) hoặc mã arXiv đầy đủ (`2506.05788`) |
| `--end` | Bắt buộc | Số thứ tự kết thúc (ví dụ: `15665`) hoặc mã arXiv đầy đủ (`2506.10787`) |
| `--month` | `None` | Mã tháng 4 chữ số (ví dụ: `2505`). Tự động trích xuất nếu `--start` là mã đầy đủ |
| `--end-month` | `None` | Mã tháng kết thúc khi chạy dải bài xuyên tháng (ví dụ: `2504`) |
| `--start-month-max` | `None` | Giới hạn số bài thực tế của tháng bắt đầu cho dải xuyên tháng |
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

## 8. Huấn luyện Citation Matching cho Milestone 3

Từ thư mục gốc, chạy các lệnh sau trong PowerShell. Bước tạo thêm nhãn dùng dữ liệu thô của Phát. Trước khi chuẩn hóa, đặt các gói bàn giao của nhóm vào `parquet_bao`, `parquet_Khanh` và `parquet_khoi`, cùng bản `manual_5_review.csv` đã duyệt của Phát trong thư mục nhãn của Phát. Danh sách tệp và các nhánh nhãn dự phòng nằm trong `MEMBER_SOURCES` của [src/prepare_dataset.py](src/prepare_dataset.py).

```powershell
.\venv\Scripts\python.exe -m pip install -r src/requirements-m3.txt
.\venv\Scripts\python.exe -B data/phat_labels_seed42_2026_11_26/prepare.py --extra-auto 18
.\venv\Scripts\python.exe -B -m src.prepare_dataset
.\venv\Scripts\python.exe -B -m src.train_matching --dataset-dir kaggle_dataset --output-dir outputs_m3/audited
```

`kaggle_dataset` chứa Parquet nhãn, danh sách ứng viên trích dẫn, danh sách bài theo từng tập, thống kê và gói code `m3_training_code.zip`. Mỗi tập `valid` và `test` có một bài nhãn tay và một bài nhãn tự động từ mỗi thành viên. Các bài còn lại thuộc tập `train`. MRR@5 dùng toàn bộ mục đã gắn nhãn trong tập tương ứng. Báo cáo cũng có `mrr@5_matched` tính riêng các mục có đáp án arXiv trong pool.

Lệnh chuẩn hóa mặc định yêu cầu ít nhất 20 nhãn đã được người rà xác nhận cho mỗi bài trong tập nhãn tay. Khi chạy thử với `--allow-agent-reviewed`, manifest và báo cáo ghi riêng số nhãn do công cụ rà để nhóm kiểm tra trước khi chốt kết quả.

Nhãn `matched` giữ ID arXiv trong danh sách tham chiếu của đúng bài nguồn. Nhãn `none` ghi nhận mục đã được xét mà chưa xác định được mục khớp trong danh sách đó. Cột `usable_label` cho biết mục nào được dùng trong huấn luyện và đánh giá. Cột `label_provenance` ghi nguồn nhãn.

Mô hình phân loại từng cặp gồm một mục BibTeX và một tham chiếu thuộc cùng bài nguồn. Các đặc trưng `exact_title`, `token_cosine`, `raw_seq_ratio` và `char_ngram_tfidf` so tiêu đề theo khớp chính xác, tần suất từ, thứ tự ký tự và cụm ký tự. `author_jaccard` đo phần họ tác giả giao nhau. `year_diff` và `year_score` biểu diễn chênh lệch năm. `roman_mismatch` giúp phân biệt các phần của tài liệu có tiêu đề gần giống nhau.

Với bài tạo trên 50.000 cặp ứng viên, trainer lấy mẫu trích dẫn theo seed 42 và giữ toàn bộ ứng viên cho từng trích dẫn đã chọn. Giới hạn này chỉ áp dụng trên tập train.

`outputs_m3/audited` chứa trọng số Logistic Regression, model XGBoost, điểm kiểm thử và dự đoán top 5 trên tập test. Có thể chạy cùng pipeline trên Kaggle bằng [notebook huấn luyện](notebooks/train_citation_matching_kaggle.ipynb).

Để chạy trên Kaggle, tạo một Dataset từ năm file trong `kaggle_dataset`. Import notebook huấn luyện, chọn **Add Input** để gắn Dataset rồi chạy **Save & Run All**. Kết quả nằm trong `/kaggle/working/outputs_m3`. Nếu bật GPU cho XGBoost, đặt `USE_GPU = True` trong ô huấn luyện.

### Xuất năm bảng M1 và M2

Chạy từ thư mục gốc. Mỗi đường dẫn trong `--data-dir` chứa các thư mục bài báo có `metadata.json`, `references.json` và các thư mục phiên bản.

```powershell
.\venv\Scripts\python.exe -B -m src.export_hf_tables --data-dir data/data --output-dir outputs_m3/hf_phat_m1_m2
```

Có thể truyền nhiều thư mục dữ liệu sau `--data-dir`. Kết quả gồm năm bảng Parquet chia phần trong `data/` và `audit.json` ghi số dòng, trạng thái xử lý phiên bản và lỗi đọc dữ liệu. [Notebook Colab](notebooks/run_m2_m3_colab_kaggle.ipynb) cũng dùng trình xuất này.

### Đồng bộ nhãn với bản xuất nhóm

Chỉ định thư mục xuất M1/M2 và bộ nhãn cùng tập chia đã duyệt. Trình chuẩn hóa giữ tập chia theo ID bài, đối chiếu nhãn tay với khóa mới và tạo lại nhãn tự động cho mọi mục BibTeX thuộc các bài đã chọn để gắn nhãn tự động. Thuật toán ưu tiên một ID arXiv tường minh trong danh sách ứng viên của bài. Khi thiếu ID tường minh, nó tìm một ứng viên duy nhất có tiêu đề chuẩn hóa khớp và có họ tác giả chung. Xem `label_reconciliation.json` để rà các khóa cần xử lý.

```powershell
.\venv\Scripts\python.exe -B -m src.prepare_dataset --hf-tables-dir outputs_m3/hf_release_work/m1_m2 --reviewed-dataset outputs_m3/hf_reviewed_run/dataset --members-dir outputs_m3/hf_release_work/members --output-dir outputs_m3/hf_release_work/dataset --sync-dir outputs_m3/hf_release_work/sync
```

### Xuất bảng dự đoán Parquet

Sau khi đồng bộ nhãn, huấn luyện Logistic Regression trên bộ vừa tạo rồi xuất dự đoán bằng cùng tập chia và bảng BibTeX của nhóm. Có thể truyền một hoặc nhiều file hoặc thư mục Parquet vào `--bibtex`.

```powershell
.\venv\Scripts\python.exe -B -m src.train_matching --dataset-dir outputs_m3/hf_release_work/dataset --output-dir outputs_m3/hf_release_work/models --workers 8 --logreg-only
.\venv\Scripts\python.exe -B -m src.export_predictions --dataset-dir outputs_m3/hf_release_work/dataset --bibtex outputs_m3/hf_release_work/m1_m2/data/bibtex --model outputs_m3/hf_release_work/models/logreg_model.json --output outputs_m3/hf_release_work/predictions/part-00000.parquet --workers 8
```

Để xuất bản nộp, dùng model fit trên bản chia tương ứng với `--dataset-dir` và dùng các bảng M2 đầy đủ cho các bài đã chọn. Cột `groundtruth_arxiv_id` lấy từ nhãn có đáp án trong pool của chính bài nguồn. Đưa các file Parquet vào `data/predictions/` trên Hugging Face và thêm cấu hình bảng này vào Dataset Card. [Đề Milestone 3](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/matching/)

- Bộ dữ liệu công khai trên Hugging Face: [QuangPhat101/arxiv-citation-matching](https://huggingface.co/datasets/QuangPhat101/arxiv-citation-matching)
