Ran check full git diff against HEAD
Ran check status short
Ran check checkpoint progress

Dưới đây là **bản tóm tắt kỹ thuật chi tiết các điểm thay đổi so với `git HEAD` bên nhánh `main`**. Bạn có thể sao chép toàn bộ nội dung này gửi cho bạn của bạn (hoặc đưa thẳng cho Agent của bạn đó xử lý):

---

# BẢN TÓM TẮT THAY ĐỔI CODE CRAWLER (SO VỚI MAIN HEAD)

Có **4 file** được tối ưu và sửa lỗi trọng yếu để đảm bảo crawler chạy bền bỉ, không bị nghẽn mạng và không mất dữ liệu:

---

### 1. `src/utils.py` (Rate Limiter & Nhận diện lỗi mạng đứt quãng)

* **Vấn đề 1 (Rate Limit S2):** Giá trị `s2_rate_limiter` cũ là `1.0s`, bằng đúng hạn ngạch 1 RPS của Semantic Scholar. Khi gặp độ trễ mạng quốc tế (jitter), các request dễ rơi sát nhau khiến CloudFront phạt mã `429 Too Many Requests`.
  * **Khắc phục:** Tăng `min_interval` từ `1.0` lên `1.5` (tạo vùng đệm an toàn).
* **Vấn đề 2 (Bắt thiếu Exception mạng):** Khi tải các bài báo lớn (15MB – 35MB), kết nối TCP hay bị đứt giữa chừng ném ra các lỗi `ChunkedEncodingError`, `IncompleteRead`, hoặc `"Connection broken"`. Decorator `@retry_with_backoff` cũ không coi đây là lỗi retryable nên không thử lại mà để crash luôn.
  * **Khắc phục:** Bổ sung kiểm tra `ChunkedEncodingError` và chuỗi `"IncompleteRead"`, `"Connection broken"` vào điều kiện `is_retryable = True`.

**Diff:**
```python
# --- Rate Limiter ---
arxiv_rate_limiter = RateLimiter(min_interval=3.0)
- s2_rate_limiter = RateLimiter(min_interval=1.0)
+ s2_rate_limiter = RateLimiter(min_interval=1.5)

# --- retry_with_backoff ---
- elif isinstance(exc, (requests.Timeout, requests.ConnectionError)):
+ elif isinstance(exc, (requests.Timeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError)):
      is_retryable = True
+ elif "IncompleteRead" in str(exc) or "Connection broken" in str(exc):
+     is_retryable = True
- elif isinstance(exc, (TimeoutError, ConnectionError, OSError)):
+ elif isinstance(exc, (TimeoutError, ConnectionError, OSError)) or "IncompleteRead" in str(exc):
      is_retryable = True
```

---

### 2. `src/downloader.py` (Đưa Stream Download vào trong Retry Decorator)

* **Vấn đề cốt lõi:** Code cũ chỉ bọc bước gọi `requests.get()` ban đầu trong `@retry_with_backoff`. Vòng lặp ghi stream file `for chunk in response.iter_content()` lại nằm **bên ngoài** decorator! Hậu quả: Nếu đang stream được 10MB/20MB mà mạng bị đứt, file bị lỗi và ném exception `File write failed` mà hoàn toàn **không được thử lại**.
* **Khắc phục:** Đóng gói toàn bộ quá trình `requests.get` + ghi stream ra file tạm `.part` + atomic rename vào bên trong hàm `_fetch_and_stream()` được bọc `@retry_with_backoff`. Nếu đứt mạng giữa chừng, nó tự động xóa file `.part` và stream lại từ đầu.

**Diff:**
```python
- def _fetch_stream() -> Any:
+ def _fetch_and_stream() -> Optional[Path]:
      arxiv_rate_limiter.wait()
      resp = req_func(url, headers=headers, stream=True, timeout=timeout)
      if resp.status_code == 404:
          logger.info("[%s] No LaTeX source archive available on arXiv (HTTP 404, PDF-only).", versioned_id)
          return None
      resp.raise_for_status()
-     return resp

+     tmp_dest = dest.with_name(f"{dest.name}.part")
+     try:
+         with open(tmp_dest, "wb") as f:
+             for chunk in resp.iter_content(chunk_size=65536):
+                 if chunk:
+                     f.write(chunk)
+         tmp_dest.replace(dest)
+     except Exception as stream_err:
+         if tmp_dest.exists():
+             tmp_dest.unlink(missing_ok=True)
+         raise stream_err
+     finally:
+         resp.close()
+     return dest

  try:
-     response = _fetch_stream()
+     return _fetch_and_stream()
  except Exception as exc:
...
```

---

### 3. `src/references.py` (S2 Retry, Cooldown thông minh & Chống ghi đè rỗng)

* **Vấn đề 1 (Treo 30 giây):** Khi gặp 429, code cũ hardcode ngủ `30.0s` (dành cho chế độ unauthenticated). Với người dùng đã có API Key, chỉ cần chờ **3.5s** là có thể gọi lại được.
* **Vấn đề 2 (MẤT DỮ LIỆU NGHIÊM TRỌNG):** Khi cạn số lần retry do 429 hoặc lag mạng, khối `except Exception:` cũ đã `return None`. Khi hàm trả về `None`, tầng trên tự động hiểu là bài báo không có trích dẫn và ghi `[]` vào `references.json` rồi đánh dấu hoàn tất! Điều này làm mất vĩnh viễn trích dẫn thật của các bài báo bị nghẽn mạng tạm thời.
* **Khắc phục:** 
  * Tăng `max_retries` từ 3 lên 5; delay ban đầu tăng từ 1.5s lên 2.0s.
  * Nếu có `api_key`, cooldown khi gặp 429 chỉ là `3.5s`.
  * Khi cạn lượt retry, ném `raise` exception để `crawler.py` nhận diện là bài thất bại, **không lưu file rỗng `[]`** và không ghi checkpoint, để dành cào bù sau.

**Diff:**
```python
- max_retries = 3
- delay = 1.5
+ max_retries = 5
+ delay = 2.0

  if response.status_code == 429:
      retry_after = response.headers.get("Retry-After")
-     cooldown = float(retry_after) if retry_after and retry_after.isdigit() else 30.0
+     default_cooldown = 3.5 if api_key else 30.0
+     cooldown = float(retry_after) if retry_after and retry_after.isdigit() else default_cooldown
      _s2_cooldown_until = time.monotonic() + cooldown
      if attempt < max_retries:
          ...
          continue
      raise RuntimeError(f"Semantic Scholar 429 Rate Limited after {max_retries} attempts.")

  except Exception as exc:
      if attempt == max_retries:
-         logger.warning("[%s] S2 request failed after %d retries (%s). Defaulting to empty references list.", arxiv_id, max_retries, exc)
-         return None
+         logger.error("[%s] S2 request failed after %d retries (%s).", arxiv_id, max_retries, exc)
+         raise
```

---

### 4. `src/crawler.py` (Bỏ qua Phase 1 & Ép cấu hình Runtime an toàn)

* **Vấn đề 1 (Tránh 429 ở Phase 1):** Phase 1 cũ luôn gọi arXiv Discovery API cho toàn bộ các bài pending. Nhưng nếu các bài đó đã có sẵn `metadata.json` trên đĩa từ các đợt chạy trước, việc gọi API lại chỉ làm lãng phí thời gian và dễ bị arXiv chặn IP (429).
  * **Khắc phục:** Lọc danh sách `missing_meta`. Nếu 100% bài đã có `metadata.json` hợp lệ, bỏ qua Phase 1 ngay trong 0.001 giây và nhảy thẳng sang Phase 2.
* **Vấn đề 2:** Ép cứng `s2_rate_limiter.min_interval = 1.5` ngay lúc import trong `crawler.py` để đề phòng trường hợp module khác cấu hình sai.

**Diff:**
```python
  from src.references import get_references
- from src.utils import setup_logger
+ from src.utils import setup_logger, s2_rate_limiter
+ 
+ # Enforce safe 1.5s interval for Semantic Scholar (under 1 RPS quota)
+ s2_rate_limiter.min_interval = 1.5

  # Trong run_pipeline():
  # Phase 1: High-Performance Batch Discovery
+ missing_meta = [
+     aid for aid in pending_ids
+     if not (output_dir / aid / "metadata.json").is_file()
+     or not _read_json(output_dir / aid / "metadata.json")
+ ]
  metadata_cache: dict[str, Any] = {}
+ if missing_meta:
+     logger.info("Phase 1: Running Batch Discovery for %d papers lacking metadata...", len(missing_meta))
      try:
-         for i in range(0, len(pending_ids), batch_size):
-             chunk = pending_ids[i:i + batch_size]
+         for i in range(0, len(missing_meta), batch_size):
+             chunk = missing_meta[i:i + batch_size]
              chunk_meta = discover_papers_batch(chunk, output_dir=output_dir)
              if chunk_meta:
                  metadata_cache.update(chunk_meta)
      except NotImplementedError:
          logger.info("Batch discovery not implemented yet by Member3; will fallback to single discovery.")
+ else:
+     logger.info("Phase 1: Skipping remote discovery (100%% of metadata exists locally for %d papers).", len(pending_ids))
```

---

### Kiểm thử xác thực
Sau khi áp dụng đầy đủ 4 file trên, toàn bộ 20 unit tests chạy qua lệnh:
```bash
python3 -m unittest discover -s tests -v
```
đạt kết quả **20/20 PASS** (thời gian chạy ~0.15s).