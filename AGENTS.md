# InsightHub - Project context DO2603

Nguồn context duy nhất. `CLAUDE.md` chỉ import file này, không nhân bản.
Giữ ≤200 dòng: thêm mục mới thì rút gọn mục cũ. Phương pháp làm việc:
`.claude/INSTRUCTOR.md`. Luật bất biến: `specs/constitution.md`.

## Architecture

- Đích Day 1: 5 service Compose — `web` (Next.js, không đổi), `api`
  (FastAPI), `postgres` (pgvector), `redis` (7, AOF), `ingestion-worker`
  (Python + ARQ). `ollama` là profile tuỳ chọn, không tính vào 5.
- Upload: `web → POST /documents → api validate (ext/size/nội dung) →
  preflight embedding-identity (đồng bộ, trả 409 ngay nếu conflict) → INSERT
  status='pending' → enqueue → 202`. Không embed trong request.
- Worker: dequeue → `asyncio.to_thread(process_document)` (hàm **dùng
  chung** từ `api/app/services/ingestion.py`, không viết lại) → chunk/embed/
  store atomic → `ready`/`failed` → log JSON `event="ingestion_completed"`.
- Retry: `POST /documents/{id}/retry` nhận lại file gốc, chỉ cho tài liệu
  `failed`, đi qua cùng đường enqueue, giữ nguyên ID.
- Chat: `web → POST /chat → api embed câu hỏi → pgvector retrieval trên
  tài liệu 'ready' → generation → answer+sources`. Độc lập với queue/worker;
  vẫn phục vụ khi worker dừng.
- Worker có HTTP nội bộ (không publish host) cho `/healthz` `/readyz`
  `/metrics`, cùng event loop với ARQ.
- `api/app/core/metrics.py` có sẵn Prometheus metrics, phục vụ Day 4.

## Conventions

- Python 3.12. `ruff format`, `ruff check`, `mypy --strict` trên cả API và
  worker (`make lint typecheck`).
- `snake_case` hàm/field, `PascalCase` class. Trạng thái tài liệu chỉ
  `pending|ready|failed`.
- Conventional Commits, 1 mục tiêu kỹ thuật/commit, test đi cùng code.
- Branch `day{N}-<topic>`; PR title `[Day N] <mô tả>`.
- `ServiceError` chỉ lộ code/message đã sanitize.
- API và worker dùng chung `app.core.config`: cùng `DATABASE_URL`,
  `REDIS_URL`, model, embedding dimension/revision.
- Dependency khoá hash; image runtime pin digest.

## Commands

- `cp .env.example .env && docker compose up --build -d --wait`; dừng giữ
  volume: `docker compose down`.
- Baseline: `make test-backend` (cần `docker compose up -d --wait postgres`
  trước vì target dùng `--no-deps`), `make test-verifiers`.
- Chất lượng: `make lint typecheck` (mypy strict + ruff).
- Milestone Day 1: `pytest tests/milestones/day1/` với
  `INSIGHTHUB_API_URL`/`INSIGHTHUB_REPO_ROOT` đã export.
- Demo xem bằng mắt (bash thuần): `bash scripts/demo-day1.sh` sau `make up`.
- Verifier: `python3 scripts/verify.py fingerprint` → điền
  `evidence/day1.json` → `bash scripts/verify-day-1.sh --worker-service
  ingestion-worker ...`.
- pytest trên host: `PYTHONPATH=api pytest api/tests/ -xvs`, cần
  `RUN_DB_TESTS=1` + Postgres lab riêng.

## Constraints

- Chỉ làm phạm vi Day đang mở. Không thêm sớm MCP/IaC/dashboard/bot của
  ngày sau.
- Không sửa `infra/db/init.sql`, không đổi schema hay thêm trạng thái
  `queued`/`processing`.
- Không sửa `web/**` cho Day 1 (quyết định đã ghi trong `plan.md` D17) —
  khoảng hở UI (tài liệu `failed` được retry qua API không tự cập nhật trừ
  khi bấm "Làm mới trạng thái") được chấp nhận và ghi nhận, không âm thầm bỏ
  qua và không tự ý mở rộng phạm vi để "tiện sửa luôn".
- Cấm dùng `BackgroundTasks` thay Redis; cấm copy pipeline ingestion sang
  worker — worker phải gọi lại đúng `process_document`.
- Cấm gọi `process_document` (hàm blocking) trực tiếp trong coroutine của
  ARQ — bắt buộc qua `asyncio.to_thread`, nếu không worker nghẽn cả job khác.
- Cấm worker retry lỗi permanent (`InvalidDocument`, `DocumentConflict`,
  `DocumentNotFound`, `IndexIdentityConflict`) — chỉ retry
  `ProviderError`/`SchemaMismatch`, tối đa 3 lần, backoff 1s/2s/4s.
- Route retry cấm so khớp cứng `content_sha256`/`pipeline_id` — 2 cột này
  có thể NULL nếu tài liệu hỏng trước khi worker từng chạy; phải NULL-safe
  (`IS NULL OR = %s`), nếu không sẽ chặn nhầm chính case cần retry nhất.
- Enqueue lỗi: cấm xoá document row — phải `UPDATE ... SET status='failed'
  WHERE id=%s AND status='pending'` (không ghi đè `ready`), giữ tài liệu
  hiện diện trong `GET /documents`.
- Cấm để log worker lộ nội dung tài liệu/filename/raw exception. Allowlist:
  `event, timestamp, document_id, job_id, attempt, status, error_code,
  duration`. Phải khoá logger `arq`/`arq.worker` về `CRITICAL` (theo đúng
  pattern `api/app/main.py:22-23` cho httpx/httpcore/pypdf/psycopg.pool) —
  allowlist tự viết không chặn được log mặc định của thư viện.
- Cấm blanket `# type: ignore`, cấm hạ `mypy --strict`, cấm sửa
  `scripts/verify.py`, cấm xoá/skip/xfail assertion bắt buộc.
- Migrate test 201→202: cấm xoá assertion dữ liệu/chunk/retrieval/
  idempotency cũ — chỉ đổi status code và cách chờ kết quả.
- Cấm silent fallback real → fixture. Real mode fail closed.
- Cấm log/commit `.env`, API key, nội dung tài liệu, provider response body.
- Cấm `git reset` phá huỷ, `docker system prune`, xoá volume project khác,
  tự merge PR.

## Domain

- `pending` → worker xử lý → `ready` (`chunk_count>0`) hoặc `failed`
  (`error_code` sanitize, chunks đã dọn).
- Lỗi: `400` sai extension · `413` >10MiB (chặn trước multipart parser, áp
  dụng cả `/documents` và `/documents/{id}/retry`, không chặn nhầm file
  đúng 10MiB, không tin riêng `Content-Length` khi chunked) · `422` nội
  dung không hợp lệ · `503` enqueue lỗi · `409` retry sai trạng thái/
  payload hoặc embedding-identity conflict (preflight đồng bộ) · `404`
  thiếu ID.
- Retry giữ nguyên document ID, đi qua enqueue như upload — kế thừa
  idempotency có sẵn của `process_document`, không viết logic riêng.
- Redelivery/2 retry đồng thời không nhân đôi chunks — atomic store +
  UPDATE có điều kiện đã có sẵn xử lý.
- Mốc đo trên workload fixture cố định: 202 <1s, `ready` <30s — 1 warm-up
  không tính + ≥5 lần đo, ghi từng lần.
- DB commit và Redis enqueue không atomic — không tuyên bố exactly-once;
  xử lý theo runbook recovery ở `plan.md` D14.

## References

- `Running-Project-Specification-Student.md` §5 · `specs/constitution.md`
  · `.claude/INSTRUCTOR.md`.
- `specs/day1-async-refactor/{spec.md,plan.md,tasks.md}` — nguồn quyết
  định kỹ thuật Day 1 (D1-D17), có ADR + trade-off cho mỗi lựa chọn.
- `docs/PROMPT_LOG_PLAYBOOK.md` · `docs/EVIDENCE_PLAYBOOK.md` ·
  `docs/RUBRIC_L3_L4_MATRIX.md` · `scripts/VERIFICATION_CONTRACT.md`.
- Source chính: `api/app/routers/documents.py` ·
  `api/app/services/{ingestion,queue}.py` ·
  `api/app/core/{config,errors,index,upload_limit}.py` ·
  `ingestion-worker/worker.py` · `docker-compose.yml` · `infra/db/init.sql`.
- Bài nộp: `ai-prompts/day1.md` · `evidence/day1.json` ·
  `docs/evidence/day1/`.
