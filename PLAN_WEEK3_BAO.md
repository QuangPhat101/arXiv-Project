# Kế hoạch thực hiện: Hợp nhất dữ liệu 20.000 bài & Bàn giao Báo cáo (Tuần 3)

> **Người thực hiện:** Bảo (Thành viên 3 - Data Engineering & Statistics)  
> **Thời gian:** 02/11/2026 – 04/11/2026  
> **Mục tiêu:** Tổng hợp trọn vẹn 20.000 bài báo từ 4 thành viên thành 2 bảng dữ liệu chuẩn (`papers` và `references`), tính toán toàn bộ chỉ số thống kê, cập nhật dữ liệu summary cho `statistics.ipynb` và bàn giao cho Khánh.

---

## 1. Nguồn dữ liệu hiện có (4/4 thành viên đã đủ)

| Thành viên | Dải phân công | Tệp / Thư mục hiện có trên máy | Số lượng bài |
| :--- | :--- | :--- | :---: |
| **Bảo** | 2025-03: 21914 ➔ 2025-04: 2522 | `Project/arXiv-Project/data` | **5.000** |
| **Khánh** | 2025-03: 01914 ➔ 2025-03: 06913 | `data_khanh/data` (đã giải nén) | **5.000** |
| **Phát** | 2025-05: 10666 ➔ 2025-05: 15665 | `data_Phat.rar` (693 MB) | **5.000** |
| **Khôi** | 2025-06: 05788 ➔ 2025-06: 10787 | `Khoi lam 5788 toi 10787.zip` (703 MB) | **5.000** |
| **Tổng cộng** | **4 dải toàn nhóm** | **Đầy đủ 100% kho dữ liệu** | **20.000 bài** |

---

## 2. Quy trình 5 bước thực hiện chi tiết

```
[Bước 1] Giải nén dữ liệu của Phát & Khôi
       │
       ▼
[Bước 2] Chạy aggregate.py tổng hợp 20.000 bài (ra papers & references)
       │
       ▼
[Bước 3] Trích xuất 3 file summary (Bảo, Phát, Khôi) vào arXiv-Report/milestone1/data/
       │
       ▼
[Bước 4] Chạy kiểm thử tự động statistics.ipynb (xác nhận 20.000 bài)
       │
       ▼
[Bước 5] Commit Git, tạo PR & Bàn giao số liệu hoàn chỉnh cho Khánh
```

---

### Bước 1: Giải nén dữ liệu Phát và Khôi vào thư mục riêng biệt
* **Mục đích:** Cách ly dữ liệu từng người, tránh xung đột file `checkpoint.txt` và dễ dàng kiểm soát.
* **Thao tác:**
  1. Giải nén `data_Phat.rar` vào `D:\3.1\NMKHDL\data_phat`.
  2. Giải nén `Khoi lam 5788 toi 10787.zip` vào `D:\3.1\NMKHDL\data_khoi`.
* **Kiểm tra sau giải nén:**
  - Kiểm tra mỗi thư mục có đúng 5.000 bài và file `checkpoint.txt` báo đủ 5.000 bài.

---

### Bước 2: Chạy kịch bản tổng hợp `src/aggregate.py` cho toàn bộ 20.000 bài
* **Mục đích:** Sinh 2 bảng dữ liệu nòng cốt của Milestone 1 theo đặc tả môn học.
* **Lệnh thực thi:**
  ```bash
  cd Project/arXiv-Project
  python src/aggregate.py \
    --data-dirs ./data ../../data_khanh/data ../../data_phat/data ../../data_khoi/data \
    --output-dir ./data/aggregated \
    --format both
  ```
* **Kết quả đầu ra tại `data/aggregated/`:**
  1. `papers.parquet` & `papers.csv`: Đúng 20.000 dòng, 6 cột (`arxiv_id`, `title`, `authors`, `submission_date`, `revised_dates`, `venue`).
  2. `references.parquet` & `references.csv`: Khoảng 380.000 – 400.000 dòng trích dẫn có `ref_arxiv_id`.
  3. `crawl_statistics.json`: File JSON lưu số liệu tổng hợp toàn nhóm (tổng versions, phân bố versions, số ref trung bình...).

---

### Bước 3: Tạo các file summary CSV cho `arXiv-Report`
* **Mục đích:** Báo cáo Jupyter Book không lưu trữ 20.000 thư mục bài thô trên Git, mà đọc các file summary gọn nhẹ (`milestone1/data/*_summary.csv`).
* **Hiện trạng:**
  - Khánh đã tạo sẵn file của mình: `arxiv_2503_summary.csv`.
* **Cần tạo thêm 3 file summary:**
  1. `arxiv_2503_2504_summary.csv` (dải của Bảo)
  2. `arxiv_2505_summary.csv` (dải của Phát)
  3. `arxiv_2506_summary.csv` (dải của Khôi)
* **Định dạng chuẩn từng dòng (9 cột theo cấu trúc Khánh đã thiết kế):**
  `arxiv_id,version,n_versions,n_authors,n_refs,n_refs_arxiv,status,raw_bytes,extracted_bytes`
* **Vị trí lưu:** `Project/arXiv-Report/milestone1/data/`.

---

### Bước 4: Kiểm thử tự động `statistics.ipynb`
* **Mục đích:** Đảm bảo notebook nhận đủ 20.000 bài và toàn bộ đồ thị của Khánh tự động render mượt mà.
* **Thao tác:**
  - Chạy `statistics.ipynb` bằng Python script hoặc Jupyter kernel.
  - Xác nhận dòng log hiển thị:  
    `20,000 papers | ~32,000 versions | ranges: arxiv_2503, arxiv_2503_2504, arxiv_2505, arxiv_2506`
  - Đảm bảo 100% cell chạy thành công không sinh Exception.

---

### Bước 5: Cam kết mã nguồn & Bàn giao kết quả
1. **Bên `arXiv-Project`:**
   - Commit `src/aggregate.py` trên nhánh `feat/data-aggregation` và tạo Pull Request vào `main`.
2. **Bên `arXiv-Report`:**
   - Commit 3 file summary mới trên nhánh `feat/data-summary-20k` và tạo Pull Request vào `main`.
3. **Bàn giao cho Khánh (Thành viên 4):**
   - Nhắn tin thông báo cho Khánh: toàn bộ 20.000 bài đã được gộp thành công, 2 bảng dữ liệu và 4 file summary đã đồng bộ. Khánh chỉ cần mở notebook xem đồ thị tự render và rà soát lại bài nhận xét Tiếng Anh.

---

## 3. Bảng phân định ranh giới công việc (Tránh làm thay người khác)

| Nội dung | Bảo (Bạn) | Thành viên khác |
| :--- | :---: | :---: |
| Giải nén và kiểm tra 20k bài | **Làm** | |
| Gộp bảng `papers` và `references` | **Làm** | |
| Tính toán chỉ số thống kê & sinh CSV summary | **Làm** | |
| Viết mã nguồn vẽ biểu đồ (`plt.bar`, `plt.hist`...) | Không làm | **Khánh làm** |
| Viết bài văn giải thích Tiếng Anh trong `statistics.ipynb` | Không làm | **Khánh làm** |
| Đo lường hiệu năng Colab CPU trong `performance.ipynb` | Không làm | **Khôi làm** |
| Soạn thảo `implementation.md` | Không làm | **Phát làm** |

