# Khôi — nhãn seed 42

`manual_5_approved.csv`: giữ 211 quyết định Khôi đã duyệt từ bộ cũ; chỉ đổi `human_verified=true` và nguồn. `auto_495_labels.csv`: 495 bài chọn ngẫu nhiên seed 42, mọi BibTeX entry có tiêu đề được `\cite` trong bất kỳ version nào; `bibtex_auto_495_cited.csv`: bảng BibTeX lọc khớp từng khóa với nhãn auto. `bibtex_selected_500.csv`: bảng BibTeX khớp khóa với toàn bộ nhãn 5 + 495 bài, có cờ `is_cited`. `selected_papers.csv`: danh sách 5 + 495; `summary.json`: thống kê và cấu hình.

Matcher dùng snapshot nguyên bản từ `origin/feat/m3-hybrid-citation-matching-bao` commit `73f06ee`; năm reference lấy từ `ref_submission_date[:4]`. ID arXiv ghi rõ trong `.bib` hoặc URL và thuộc reference pool được ưu tiên; còn lại chọn ứng viên điểm hybrid cao nhất nếu >=0,75, ngược lại `none`. Mỗi entry chỉ xét references của bài chứa nó. File `.bib` >5.000.000 byte và bài không có reference arXiv bị loại.

Lưu ý: phần manual được giữ theo quyết định Khôi, kể cả các entry không thấy `\cite` trong lần quét source mới. Các dòng manual `unresolved` cũng được giữ nguyên; đó chưa phải ground truth có ID/none cho mô hình. Không có model, MRR hay predictions trong bộ này. Chạy lại bằng `python prepare.py` từ repo root.
