# Bộ nhãn trích dẫn của Phát

Phạm vi gồm 5 bài rà tay và 495 bài gắn nhãn tự động trong dải `2505.10666` đến `2505.15665`. Mỗi dòng nhãn ghép với BibTeX bằng ID bài nguồn và `citation_key`.

| Tệp | Nội dung |
| --- | --- |
| `manual_5_review.csv` | Bảng rà tay có nguồn đối chiếu cho 5 bài. Cột `human_verified` ghi nhận các dòng Phát đã duyệt. |
| `manual_5_labels_draft.csv` | Bản nháp 7 cột theo header nhãn tay của Bảo và Khánh. |
| `auto_495_labels.csv` | Bảng 9 cột theo header nhãn tự động của Bảo và Khánh. Bao phủ mọi mục BibTeX mà parser M2 trích được từ 495 bài đã chọn. |
| `bibtex_selected_500.csv` | Mục BibTeX tương ứng với hai bảng nhãn. Cột `is_cited` cho biết mục có xuất hiện trong lệnh trích dẫn LaTeX. |
| `selected_papers.csv` | Danh sách bài nguồn, loại nhãn và số mục BibTeX của từng bài. |
| `summary.json` | Số bài, số nhãn, trạng thái rà tay và cấu hình matcher. |

Script đọc 5 ID từ bộ rà tay đã chọn và loại các ID đó trước khi xáo mẫu với seed 42. Bài tự động cần có ứng viên arXiv đã crawl và ít nhất một mục BibTeX có tiêu đề được trích trong LaTeX. Script bỏ qua bài có tệp BibTeX vượt 5 MB hoặc có lỗi khi parse.

Matcher dùng cùng bản của Bảo tại commit `73f06ee` như bộ Khôi. `method=bib_arxiv_id` dùng ID đọc từ BibTeX hoặc LaTeX có trong danh sách ứng viên của bài nguồn. Nếu có nhiều ID như vậy, chọn ID có điểm hybrid cao nhất. `method=score` dùng ứng viên đứng đầu khi điểm đạt ít nhất 0,75. `best_score` ghi điểm cao nhất trong danh sách ứng viên.

Trong hai CSV nhãn gọn, `groundtruth_arxiv_id` để trống khi đã xác định không có ứng viên khớp. File rà tay chi tiết lưu `label_status`, trạng thái duyệt và `external_arxiv_id` để đối chiếu. Bản nháp 7 cột chỉ xuất các dòng có trạng thái `matched` hoặc `none` trong file rà tay. Chỉ dùng dòng đã được Phát duyệt khi chốt nhãn tay.

Từ thư mục gốc của repo, dùng môi trường Python của dự án để tạo lại các bảng từ dữ liệu trong `data/data`.

```powershell
.\venv\Scripts\python.exe -B data/phat_labels_seed42_2026_11_26/prepare.py
```

Ngưỡng 10% nhãn tự động của đề được tính trên toàn bộ tập bài còn lại của nhóm. Bộ này dùng đúng số lượng 495 bài tự động đã chốt cho Phát.
