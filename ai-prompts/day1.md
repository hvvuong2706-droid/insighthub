# Day 1 AI Prompts

> Host: Claude Code · Version: 2.1.278 · Model: claude-sonnet-5 (Sonnet 5) · Auth: (người dùng xác nhận: subscription/API — agent không tự biết)
> OS: Linux (WSL2) · Checkout: `day1-refactor` @ `0d5b838` (+ working tree chưa commit)
> Tổng số lượt agent trong ngày: nhiều chục lượt trò chuyện · Số lượt được ghi đầy đủ ở đây: 4 (≥3)

## Prompt 1 — Phân tích kiến trúc starter, không suy đoán (P01)

**Host**: Claude Code
**Version / Model / Auth mode**: 2.1.278 / claude-sonnet-5 / (người dùng xác nhận)
**Context / Evidence**: Chưa nạp context nào trước đó — đây là prompt mở đầu
phiên. Evidence: toàn bộ phần "Architecture map" + "API contract" + bảng
Must-have/Should-have tôi trả lời ngay sau prompt này trong log hội thoại.
**Time**: 2026-09-21 (đầu phiên)

**Prompt**:
```text
RÀNG BUỘC
Chỉ đọc và phân tích source. Chưa sửa file nào, chưa cài dependency.
KHÔNG dùng specs/day1-async-refactor/ làm nguồn — đó là ghi chú của người khác.
Tôi muốn mọi kết luận rút ra từ chính source của repo này.
Giữ DB schema, layout frontend, error contract và embedding invariants.
Phân biệt rõ: lỗi cố ý của starter vs phần Day 1 phải triển khai.

MỤC TIÊU
Phân tích InsightHub starter: trách nhiệm của web / api / postgres, luồng
upload → chunk → embed → store, luồng chat, và chính xác chỗ nào ingestion
đồng bộ làm chặn request.
Sau đó đề xuất nội dung cho 5 mục "TODO học viên" trong AGENTS.md.

TIÊU CHÍ CHẤP NHẬN
- Architecture map, mỗi nhận định dẫn tên file và số dòng cụ thể.
- Liệt kê API contract hiện tại: endpoint, status code, điều kiện lỗi.
- Nêu các invariant phải giữ: atomicity, idempotency, vector identity.
- Chỉ ra chức năng ĐÃ CÓ trong starter, để tôi không tính nhầm là feature mới.
- Đề xuất AGENTS.md ≤200 dòng, đủ 6 section; phần Constraints phải có
  forbidden patterns CỤ THỂ, không nói chung chung.
- Liệt kê những chỗ bạn không chắc và cần tôi xác nhận.

DỪNG sau khi trình bày. Chưa được ghi vào AGENTS.md.

THAM CHIẾU
Running-Project-Specification-Student.md mục 2 và 5;
api/app/routers/documents.py; api/app/services/ingestion.py;
api/app/core/index.py; infra/db/init.sql; api/tests/; web/components/;
docker-compose.yml; AGENTS.md (bản 38 dòng hiện tại).
```

**Kết quả**: Tôi đọc trực tiếp 15+ file nguồn (không dùng `specs/day1-async-refactor/`), trả về architecture map có trích dòng cụ thể, bảng API contract đầy đủ (400/413/422/409/503/502/503), 7 invariant, bảng "đã có sẵn vs phải làm Day 1", và bản nháp 6 section AGENTS.md kèm 5 điểm chưa chắc cần xác nhận — không tự ghi vào AGENTS.md như ràng buộc yêu cầu.

**Why it worked**:
- Cấm dùng `specs/day1-async-refactor/` ngay từ đầu buộc tôi tự đọc source thật thay vì lặp lại đáp án có sẵn — về sau phát hiện thư mục đó chứa gần như đáp án mẫu (13 ADR, 48 task), nếu không cấm từ đầu tôi đã vô tình "học tủ".
- "DỪNG sau khi trình bày" tạo gate rõ ràng, ngăn tôi nhảy thẳng sang sửa code khi mới hiểu sơ bộ codebase.
- Yêu cầu trích dòng cụ thể buộc tôi đọc kỹ thay vì mô tả chung chung — bắt được chính xác điểm chặn đồng bộ ở `documents.py:34`.

**What I changed**: (đây là prompt mở đầu, chưa có đề xuất nào của agent để bác bỏ — xem Prompt 2 cho phần "What I changed" thật)

**Evidence**: Toàn bộ phần trả lời "Architecture map / API contract / Invariant / Must-have checklist" trong lịch sử hội thoại phiên này.

## Prompt 2 — Review chéo bảng quyết định kỹ thuật (P02 — PLAN gate)

**Host**: Claude Code
**Version / Model / Auth mode**: 2.1.278 / claude-sonnet-5 / (người dùng xác nhận)
**Context / Evidence**: `specs/day1-async-refactor/plan.md` §2 (bảng D1-D17) đã viết trước đó qua `/sdd-plan`. Evidence: diff thật ở `plan.md` sau prompt này (D4 sửa, D7 sửa, D11 thêm mới, D14 thêm mới, D15 thêm mới, D16 thêm mới).
**Time**: 2026-09-22 (giữa phiên, sau khi `plan.md` bản đầu đã viết)

**Prompt**:
```text
Đã review chéo bảng D1-D13. Sáu việc:

1. D4 — lý do SAI. Gọi hàm đồng bộ từ coroutine làm NGHẼN event loop (worker
   không nhận job khác), chứ không gây lỗi "event loop already running" — lỗi
   đó là do gọi asyncio.run() bên trong loop đang chạy. Quyết định giữ nguyên,
   sửa lại phần giải thích cho đúng cơ chế.

2. Kiểm chứng lại khẳng định "web/ không cần đổi gì". Kịch bản: worker ghi
   failed sau lượt retry 1, frontend ngừng polling; lượt 2 thành công, DB
   thành ready nhưng màn hình kẹt ở failed vĩnh viễn. Chạy thật để xác nhận
   có xảy ra không. Nếu có, nêu phương án sửa tối thiểu ở frontend.

3. Logger của ARQ ở mức INFO có thể in tham số job — mà job chứa bytes tài
   liệu và filename theo D3. Allowlist của ta chỉ phủ log ta tự viết. Nêu cách
   khoá logger thư viện và viết test chứng minh không lọt.

4. D8 — khi tài liệu hỏng rất sớm (enqueue lỗi trước khi tính hash),
   content_sha256 và pipeline_id đã có trong DB chưa? Nếu chưa thì route
   /retry lấy gì để đối chiếu file gốc? Trả lời cụ thể theo thứ tự thao tác.

5. D10 — phân biệt rõ: giới hạn 10 MiB áp cho KÍCH THƯỚC FILE hay TOÀN BỘ
   REQUEST? File đúng 10 MiB phải được nhận (spec), nên nếu chặn theo request
   thì phần bao bì multipart sẽ làm nó trượt. Và xử lý sao khi client dùng
   chunked, không có Content-Length?

6. Câu hỏi còn treo từ lần trước, chưa quyết định nào đứng tên: enqueue xảy ra
   TRƯỚC hay SAU khi commit metadata vào DB? Khi enqueue lỗi thì XOÁ row hay
   đánh dấu failed? Tạo hẳn một quyết định D14 cho việc này, kèm phương án đã
   loại và đánh đổi.

Thêm một câu cần trả lời: kiểm tra xung đột embedding identity có làm được như
một preflight rẻ ở API TRƯỚC khi enqueue không? Nếu được thì giữ nguyên 409
đồng bộ và không phải viết lại test_index_identity_change.

Và mypy --strict vẫn chưa thấy trong bảng quyết định (Should-have SH2).

Cập nhật bảng rồi trình lại. CHƯA code.
```

**Kết quả**: Tôi sửa D4 (cơ chế đúng: nghẽn event loop, không phải crash), sửa D7 (so khớp NULL-safe cho content_sha256/pipeline_id), thêm D11 (khoá logger arq + test), thêm D14 (insert-then-enqueue, đánh dấu failed không xoá row), thêm D15 (preflight identity, đề xuất do chính học viên đưa ra), thêm D16 (mypy strict), và **chạy thật** (docker compose + SQL flip) để xác nhận khoảng hở polling ở `web/` là có thật trước khi trả lời câu 2.

**Why it worked**:
- Mỗi điểm đều **buộc kiểm chứng thật** ("Chạy thật để xác nhận có xảy ra không") thay vì cho phép trả lời lý thuyết — điều này trực tiếp dẫn tới việc tôi phải dựng `docker compose`, tự tay `UPDATE` SQL, và phát hiện khoảng hở polling là thật (không phải suy đoán).
- Câu hỏi về D4 chỉ đúng cơ chế lỗi kỹ thuật (không nói chung là "sai") giúp tôi sửa đúng gốc rễ thay vì chỉ đổi từ ngữ.
- Yêu cầu "CHƯA code" ở cuối giữ đúng PLAN gate, ngăn tôi nhảy sang implement khi bảng quyết định còn lỗi.

**What I changed sau review** (đây là chỗ agent — tôi — bị bác bỏ/sửa thật, không phải tôi tự sửa mình):
- Tôi đã **sai** khi ghi lý do D4 là "event loop already running" — học viên chỉ ra đúng cơ chế thật (nghẽn event loop), tôi sửa lại toàn bộ đoạn giải thích, không chỉ đổi câu chữ.
- Tôi đã **bỏ sót hoàn toàn** rủi ro logger của arq (D11) — không phải tôi tự phát hiện, học viên đặt câu hỏi trực tiếp buộc tôi điều tra và tìm ra lỗ hổng thật.
- Tôi đã khẳng định "`web/` không cần đổi gì" **mà chưa kiểm chứng** — học viên từ chối chấp nhận khẳng định suông, buộc tôi chạy thật và thừa nhận có khoảng hở polling thật (dù có lối thoát thủ công).

**Evidence**: `specs/day1-async-refactor/plan.md` — bảng D1-D17 (đặc biệt D4, D7, D11, D14, D15, D16), mục "2b. Đã chạy thật để xác nhận".

## Prompt 3 — Yêu cầu kịch bản kiểm chứng nhìn thấy được (P04 — review/test)

**Host**: Claude Code
**Version / Model / Auth mode**: 2.1.278 / claude-sonnet-5 / (người dùng xác nhận)
**Context / Evidence**: Sau khi Nhóm 1-6 đã code xong (`api/app/routers/documents.py`, `ingestion-worker/worker.py`, `Makefile` lint/typecheck). Evidence: `tests/milestones/day1/*.py`, `scripts/demo-day1.sh`.
**Time**: 2026-09-22 (sau khi Nhóm 6 hoàn tất)

**Prompt**:
```text
làm tiếp, tạo kịch bản live test đơn giản, có thể thấy bằng mắt, kết quả cho
ra đạt yêu cầu
```

**Kết quả**: Tôi viết 6 file `tests/milestones/day1/test_*.py` (đúng 6 tên hàm bắt buộc của `scripts/verify.py`) chạy HTTP thật trên stack sống, cộng thêm `scripts/demo-day1.sh` — kịch bản bash thuần in rõ từng bước ✓/✗ để xem bằng mắt không cần biết Python.

**Why it worked**:
- Yêu cầu "có thể thấy bằng mắt" buộc tôi thiết kế output có ý nghĩa (in status/timing/id ra màn hình) thay vì chỉ trả về pass/fail khô khan — chính cách làm này giúp tôi (và học viên) **tự bắt được 3 bug thật** khi thực sự nhìn vào output: `/metrics` không phải JSON, fixture-mode không phải semantic search, và filename lệch giữa upload/retry trong chính demo script.
- "kết quả cho ra đạt yêu cầu" đặt tiêu chuẩn rõ ràng (phải chạy tới lúc PASS thật, không dừng ở "có vẻ đúng") — khiến tôi không dừng lại sau lần chạy đầu tiên bị FAIL mà phải sửa tới khi xanh thật.

**What I changed**:
- Tự phát hiện và sửa: `test_refactor_regression` ban đầu gọi `get_json("/metrics")` — sai vì `/metrics` là Prometheus text, không phải JSON. Đổi sang `request()` thô.
- Tự phát hiện và sửa: giả định fixture-mode retrieval sẽ tìm đúng tài liệu vừa upload theo từ khoá — sai vì fixture embedding là hash xác định, không phải semantic search (đúng như `embeddings.py` tự ghi). Đổi sang kiểm tra yếu hơn, khớp đúng cách `scripts/verify.py`'s `smoke()` đã làm.
- Tự phát hiện và sửa: `scripts/demo-day1.sh` dùng khác filename giữa lần upload gốc và lần gọi `/retry` — 409 đúng theo thiết kế D7 (đòi khớp filename tuyệt đối), không phải bug app. Sửa lại script dùng chung 1 biến filename.

**Evidence**: `tests/milestones/day1/` (6/6 pass — output thật trong log phiên), `scripts/demo-day1.sh` (chạy 2 lần, lần 2 ra `KẾT QUẢ: TẤT CẢ ĐẠT YÊU CẦU ✓`).

## Prompt 4 — Xác nhận verify chính thức + giao diện web (P04/P05)

**Host**: Claude Code
**Version / Model / Auth mode**: 2.1.278 / claude-sonnet-5 / (người dùng xác nhận)
**Context / Evidence**: Sau khi có `evidence/day1.json`, `evidence/day1-review.md`. Evidence: output thật của `scripts/verify.py day1` và `scripts/verify-day-1.sh`.
**Time**: 2026-09-22 (cuối phiên)

**Prompt**:
```text
làm tiếp 2 nhóm cuối. Nếu tôi dùng giao diện web và test thì có ra được không
và tôi muốn xem bằng mắt verify của giảng viên xem được bao điểm
```

**Kết quả**: Tôi chạy thật các route của chính `web` (Next.js) — `/api/documents`, `/api/proxy?target=upload`, `/api/proxy?target=chat`, `/api/health` — xác nhận đường đi thật của trình duyệt hoạt động đúng qua backend async mới. Sau đó chạy `scripts/verify-day-1.sh` thật 2 lần (lần đầu `INCOMPLETE` vì thiếu `pytest`, lần 2 `PASS` sau khi trỏ đúng venv).

**Why it worked**:
- Câu hỏi "web có ra được không" buộc tôi kiểm tầng tôi **chưa từng test** trong suốt phiên (luôn dùng `curl` thẳng tới API, chưa bao giờ qua route thật của `web`) — phát hiện đây là khoảng trống kiểm chứng thật, không phải giả định suông.
- "xem bằng mắt verify của giảng viên" buộc tôi chạy đúng lệnh trainer sẽ chạy (`verify-day-1.sh`) thay vì chỉ tự tin báo "chắc là pass" — và thật sự bắt được 1 lỗi môi trường thật (thiếu pytest) mà nếu chỉ đọc code sẽ không thấy.

**What I changed**: Không có đề xuất nào của agent bị bác bỏ ở prompt này (thiên về xác minh hơn là quyết định kỹ thuật mới) — ghi nhận trung thực thay vì bịa ra một lần bác bỏ không có thật.

**Evidence**: Output thật của `bash scripts/verify-day-1.sh ...` → `PASS day1 (scope=partial-runtime-contract, runtime_verified=true)`, exit 0 (log phiên).
