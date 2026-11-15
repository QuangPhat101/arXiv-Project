# Tình hình và bàn giao tích hợp Milestone 2 — 15/11/2026

## Mục tiêu hiện tại

Nhánh làm việc chung: **`integration/milestone-2`**. Tích hợp và nghiệm thu parser nội dung/BibTeX; tiếp tục benchmark M1 đang chạy. Không triển khai thêm M3 trong đợt này.

Khôi tự push bằng SSH. Nhánh chưa lên remote tại thời điểm chuẩn bị tài liệu. Không merge vào `main` trước khi sửa và nghiệm thu M2.

## Trạng thái đã kiểm tra

| Phần | Trạng thái |
|---|---|
| Code Khánh | `feat/latex-parser` tại `250156d`, đã tích hợp |
| Code Bảo | `feat/bibtex-parser-bao` tại `12192d7`, đã tích hợp |
| Bản tích hợp | `e38716c`; sau đó `5a97e92` bổ sung audit và kiểm thử M1/M2 |
| Code M3 agent từng thêm | Đã bỏ khỏi lịch sử nhánh hiện tại; giữ nguyên phần bàn giao gốc Bảo |
| Tests thông thường | 46 tests pass trên môi trường đã cài dependency |
| Nghiệm thu M2 | 7 ca kiểm tra còn fail; đây là việc cần sửa, không phải lỗi mới do merge |
| Raw Khôi | Local có 5.000 bài, 8.253 version; chưa nghiệm thu đầy đủ nội dung từng version |
| Raw 15.000 bài còn lại | Khôi xác nhận trên Drive; chờ link/quyền truy cập hoặc bảng xuất |
| Report | Repo riêng, main vẫn có các thay đổi local cũ ở performance.ipynb và ablation_benchmark.ipynb; chưa đụng vào |
| Link repo nộp 14/11 | Chờ Khôi xác nhận trạng thái Moodle |

Mốc kế hoạch còn lại: dataset HF cá nhân 20/11 23:59; Book/poster/chốt code 27/11. Chưa xác nhận thay đổi deadline từ Moodle.

## Bảo và Khánh cần sửa

| Người phụ trách | Việc | Tiêu chí nghiệm thu |
|---|---|---|
| Khánh | Loại bibliography khỏi cây | Nội dung thebibliography/reference section không vào elements; acknowledgments/appendix vẫn giữ |
| Khánh | Itemize | Có node item, câu trong mỗi item có parent đúng |
| Khánh | Cleanup và math normalization | Formatting không đổi ý nghĩa bị bỏ; công thức block tương đương được chuẩn hóa; dedup sau chuẩn hóa |
| Bảo | Union BibTeX giữa version | v1 có year, v2 thêm doi: một entry cuối giữ cả hai; không chỉ lấy bản ghi đầu |
| Bảo phối hợp Khánh | Citation key mapping | Các cite đổi sang canonical key trước khi tính ID/dedup nội dung; bibtex và nội dung thống nhất |
| Bảo | Ghi nhận lỗi | process_single_paper trả errors, mỗi record có arxiv_id, version, stage, message; không nuốt lỗi bằng except/pass |
| Bảo | Ghi nhận coverage | Có record cho từng version, phân biệt parsed, empty/PDF-only và parse error; không bỏ version rỗng |

`errors` và `coverage` là dữ liệu nội bộ phục vụ kiểm tra, không tự thêm cột vào schema Parquet của đề. Giữ giao diện parse_version trả elements/hierarchy; nếu cần thay đổi, cập nhật runner và test cùng lúc.

Lệnh nghiệm thu:

```bash
python -m unittest discover -s tests -p m2_acceptance.py -v
```

Hiện cả 7 ca đều fail và tái hiện được. Không skip/expectedFailure hoặc nới assertion chỉ để pass. Nếu chọn biểu diễn cây tương đương nhưng khác tên kind, thống nhất giao diện và cập nhật test theo yêu cầu thực tế, kèm giải thích.

## Cách nhận việc sau khi Khôi push

Để tránh ghi đè công việc nhau, mỗi người tạo nhánh sửa từ bản tích hợp mới và mở PR về **integration/milestone-2**, không về main.

Khánh:

```bash
git fetch origin
git switch -c fix/m2-latex-standardization origin/integration/milestone-2
```

Bảo:

```bash
git fetch origin
git switch -c fix/m2-bibtex-normalization origin/integration/milestone-2
```

Các lệnh trên dành cho working tree sạch; nếu có việc chưa commit thì lưu riêng trước, không reset. Hai bạn báo thời điểm trả bản sửa cho Khôi. Phần citation rewriting cần thống nhất giữa parser và runner trước khi mỗi người sửa.

Môi trường và kiểm tra:

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r src/requirements.txt
python -m unittest discover -s tests -v
python -m unittest discover -s tests -p m2_acceptance.py -v
```

Kiểm tra manifest benchmark thật cần repo arXiv-Report nằm cạnh repo code; nếu thiếu, đúng một test manifest sẽ skip. Các kiểm thử queue còn lại vẫn chạy offline.

## Điều kiện chốt M2

- [ ] Khánh hoàn thành các mục parser và báo commit/PR.
- [ ] Bảo hoàn thành các mục BibTeX/runner và báo commit/PR.
- [ ] Cả bộ tests thông thường và 7 ca nghiệm thu đều pass.
- [ ] Chạy mẫu thật có multi-file, nhiều version, bibitem, .bib và PDF-only; đối chiếu source với output.
- [ ] Kiểm tra đủ version, không có parent/citation key bị đứt liên kết, có log lỗi/coverage.
- [ ] Sau nghiệm thu mới chạy toàn corpus và bổ sung thống kê/benchmark parser cho Book M2.

Tests chỉ kiểm tra một số yêu cầu đã phát hiện thiếu, không thay thế kiểm tra mẫu thật.

## Benchmark M1 đang chạy

Snapshot progress lúc **15/11 05:46:18 America/New_York (10:46:18 UTC)**:

- Đã đo 13.475/20.000 ID (67,375%); đã chốt 13.334.
- SUCCESS 12.121; PDF_ONLY 1.213; FAILED 40; INCOMPLETE 101.
- Còn 6.525 ID chưa đo và 141 FAILED/INCOMPLETE cần theo dõi.
- Trung bình profiler 8,3202 giây/lượt bài, chỉ trên các lô đã chốt; không bao gồm đầy đủ overhead lưu Drive/Git hoặc lượt dở.
- Audit trước ở snapshot 07a6238: 549/549 observed logs có s2_key_present=true. Điều này không chứng minh key hợp lệ hay key riêng cho từng VM.
- 429 S2 cao; chưa thay cấu hình hoặc triển khai tối ưu mới.

[Progress đang cập nhật](https://github.com/QuangPhat101/arXiv-Report/blob/benchmark-20k-parallel-2x2/milestone1/data/benchmark_20k/progress.json) · [Audit notebook](docs/benchmark_20k_audit.md).

Dùng notebook `notebooks/benchmark_20k_colab.ipynb` tiếp tục campaign hiện tại. Không reset queue hoặc đổi cấu hình giữa chiến dịch. Benchmark tự nhận lô toàn nhóm; dải được đo trên một VM không nhất thiết là dải cá nhân.

## Khôi cần làm trực tiếp

1. Push nhánh tích hợp bằng lệnh dưới, rồi gửi link branch và task.md cho Bảo/Khánh.
2. Xác nhận ai đang chạy benchmark, các VM có dùng chung S2 key không (không gửi giá trị key), vị trí Drive và giờ báo lại.
3. Xác nhận link repo đã nộp; review bản sửa M2 khi hai bạn bàn giao.

```bash
git push -u origin integration/milestone-2
```

Agent chưa push, chưa gửi tin nhắn cho thành viên và chưa merge main. Chưa xác nhận hai bạn đã nhận checklist.
