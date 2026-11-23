# Audit benchmark 20k — 15/11/2026

## Tiến độ remote đã xác minh

Snapshot nhánh `benchmark-20k-parallel-2x2`, commit `01c8323081634e08e16eb0fb5f8cecf37541f0ed`, mẫu cuối 15/11 05:02:17 America/New_York (10:02:17 UTC):

- Đã đo **13.175/20.000 ID (65,875%)**; đã chốt **13.035**.
- Kết quả gần nhất: 11.846 SUCCESS, 1.189 PDF_ONLY, 39 FAILED, 101 INCOMPLETE.
- 6.825 ID chưa đo; 140 ID đã đo nhưng còn FAILED/INCOMPLETE. Có 11 lượt quan sát chưa commit; không suy ra 11 runtime đang chạy.
- Hai dải tháng 03 và 03–04 đã đo đủ 5.000 ID/dải; dải tháng 05 đã đo 3.175; dải Khôi tháng 06 chưa có ID được đo trong snapshot.
- Tổng profiler của các lượt hợp lệ: 109.674,63 giây. Đây là thời gian cộng dồn các lượt, **không phải elapsed wall time của cả chiến dịch đa VM**.

[Progress tại commit kiểm tra](https://github.com/QuangPhat101/arXiv-Report/blob/01c8323081634e08e16eb0fb5f8cecf37541f0ed/milestone1/data/benchmark_20k/progress.json) · [Progress đang cập nhật](https://github.com/QuangPhat101/arXiv-Report/blob/benchmark-20k-parallel-2x2/milestone1/data/benchmark_20k/progress.md).

Hành động: tiếp tục campaign hiện có, không reset queue/đổi thông số campaign giữa chừng. Khôi xác nhận ai đang giữ các runtime và bảo đảm nhóm tiếp tục các lô chưa hoàn tất. `settled`/`finished` không đồng nghĩa 100% SUCCESS: một ID vẫn có thể chốt sau khi hết retry.

## Bản notebook đã audit

- Nguồn: `~/Downloads/benchmark_20k_colab(1).ipynb`.
- Bản sao giữ nguyên bytes tại `notebooks/benchmark_20k_colab.ipynb`.
- SHA-256 file: `842355e9b1ae9df68ed21f4f264998039479bcbad2757100d2758d1c48fb40b8`.
- Scraper pin: `c87f35aca9495f7e3aa4261340d5f10778b692ea`; report manifest pin: `50945d301d1939862f4cad5a33a16d4731374e57`.
- Runner hash: `09a79b38c705f2847c84269ff164a3689474c915df117d7512193c6cac814f9c`, khớp [campaign hiện có](https://github.com/QuangPhat101/arXiv-Report/blob/01c8323081634e08e16eb0fb5f8cecf37541f0ed/milestone1/data/benchmark_20k/campaign.json).
- Đã kiểm tra 4 CSV có đúng 20.000 ID khác nhau, 800 lô × 25 ID; giữ cấu hình 2 download worker, 2 S2 worker, tối đa 4 VM.
- Remote cũng có notebook ở `benchmark-20k-notebook/milestone1/benchmark_20k_colab.ipynb`, nhưng blob khác bản Downloads. Dùng cùng bản Downloads đã audit để bàn giao; không giả định hai notebook giống nhau.

## Kiểm thử offline

```bash
python -m unittest discover -s tests -p test_benchmark_notebook.py -v
```

7 tests pass:

1. Compile toàn bộ cell và child runner, không chạy Colab/setup/network.
2. Chỉ cấp tối đa 4 lease; hết hạn thì cấp lại, worker cũ không được ghi đè.
3. Checkpoint/release/resume; thiếu biên nhận archive không được commit; commit lặp không đếm hai lần.
4. Hai runtime không giữ discovery slot cùng lúc, có khoảng nghỉ sau khi trả slot.
5. SUCCESS thiếu metadata/source bị hạ thành INCOMPLETE.
6. Đọc manifest thật từ repo report: 20.000 ID, 800 lô.
7. Hai GitJournal dùng bare repo local: non-fast-forward được đọc lại và tính lại; giữ được cập nhật của cả hai worker.

## Giới hạn và cách đọc kết quả

- Agent chưa đăng nhập Colab hoặc tạo thêm lượt benchmark. Snapshot remote chứng minh có lượt đo/ghi log; chưa tải archive Drive để xác minh lại checksum và đủ source của từng lô.
- Offline tests không kiểm chứng tốc độ mạng, quyền token/Drive hoặc điều kiện S2 của từng thành viên. Snapshot có 13.134 HTTP S2 429; phải giữ retry/delay trong số liệu, không bỏ đi để đẹp thời gian.
- Discovery được phối hợp toàn nhóm; source/S2 dùng limiter ở từng VM. Không mô tả shared timestamp limiter như bằng chứng chỉ có một kết nối source đang mở. Không dùng chung một S2 key cho nhiều VM rồi giả định mỗi VM có quota riêng.
- Peak RSS đang báo từ profiler child; telemetry/log của lượt dở còn nằm ở attempts. Khi viết report, phân biệt thời gian scraper, overhead lưu Drive/Git, tổng machine-seconds và khoảng thời gian lịch.
- Chưa sửa campaign hay cấu hình notebook trong session này; file nguồn Downloads được giữ nguyên.
