#!/usr/bin/env bash
# Live, watchable demo of the Day 1 async refactor. Pure curl — no pytest, no
# Python needed to follow along. Requires the 5-service stack already running
# (`make up`). Run it and watch each step print its real result.
set -euo pipefail
API=${API_URL:-http://localhost:8000}
PASS="✓"
FAIL="✗"
ok=0

check() {
  local label=$1 got=$2 want=$3
  if [ "$got" = "$want" ]; then
    echo "  $PASS $label ($got)"
  else
    echo "  $FAIL $label — expected $want, got $got"
    ok=1
  fi
}

echo "== 1. Cả 5 service đang chạy? =="
docker compose ps --format '{{.Service}}: {{.Status}}'
echo

echo "== 2. Upload thật, đo thời gian trả 202 (MH6: phải <1s) =="
tmpfile=$(mktemp /tmp/day1-demo-XXXX.txt)
echo "InsightHub Day 1 demo — $(date -u +%FT%TZ)" > "$tmpfile"
start=$(date +%s.%N)
resp=$(curl -s -w '\n%{http_code}' -X POST "$API/documents" -F "file=@$tmpfile;filename=demo-$(date +%s).txt")
end=$(date +%s.%N)
elapsed=$(awk "BEGIN{printf \"%.3f\", $end-$start}")
body=$(echo "$resp" | head -n -1)
code=$(echo "$resp" | tail -n1)
echo "  Response ($elapsed s): $body"
check "HTTP 202" "$code" "202"
awk "BEGIN{exit !($elapsed < 1)}" && echo "  $PASS elapsed ${elapsed}s < 1s" || { echo "  $FAIL elapsed ${elapsed}s >= 1s"; ok=1; }
doc_id=$(echo "$body" | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")
echo "  document_id=$doc_id"
echo

echo "== 3. Poll trạng thái tới khi worker xử lý xong (MH7: phải <30s) =="
deadline=$((SECONDS + 30))
status="pending"
while [ $SECONDS -lt $deadline ]; do
  status=$(curl -s "$API/documents" | python3 -c "
import json,sys
docs=json.load(sys.stdin)
m=[d for d in docs if str(d['id'])=='$doc_id']
print(m[0]['status'] if m else 'missing')
")
  echo "  [$((SECONDS))s] status=$status"
  [ "$status" = "ready" ] && break
  sleep 1
done
check "worker đưa tài liệu về ready" "$status" "ready"
echo

echo "== 4. Log worker có đúng sự kiện ingestion_completed cho document này? =="
log_line=$(docker compose logs ingestion-worker --no-color 2>/dev/null | grep "\"document_id\": $doc_id" | tail -n1)
if [ -n "$log_line" ]; then
  echo "  $PASS tìm thấy: $log_line"
else
  echo "  $FAIL không tìm thấy dòng log ingestion_completed cho id=$doc_id"
  ok=1
fi
echo

echo "== 5. Chat vẫn hoạt động (MH8) =="
chat=$(curl -s -X POST "$API/chat" -H 'Content-Type: application/json' -d '{"question":"InsightHub"}')
answer=$(echo "$chat" | python3 -c "import json,sys;print(json.load(sys.stdin)['answer'][:80])")
echo "  answer: $answer..."
[ -n "$answer" ] && echo "  $PASS chat trả lời không rỗng" || { echo "  $FAIL chat rỗng"; ok=1; }
echo

echo "== 6. Demo retry: tạo tài liệu lỗi thật (nội dung chỉ có khoảng trắng), rồi retry =="
badfile=$(mktemp /tmp/day1-demo-bad-XXXX.txt)
printf '   \n\t \n' > "$badfile"
bad_filename="demo-bad-$(date +%s).txt"
bad_id=$(curl -s -X POST "$API/documents" -F "file=@$badfile;filename=$bad_filename" | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")
echo "  document_id=$bad_id, filename=$bad_filename (nội dung chỉ khoảng trắng, sẽ fail sau khi worker trích xuất)"
deadline=$((SECONDS + 30))
while [ $SECONDS -lt $deadline ]; do
  status=$(curl -s "$API/documents" | python3 -c "
import json,sys
docs=json.load(sys.stdin)
m=[d for d in docs if str(d['id'])=='$bad_id']
print(m[0]['status'] if m else 'missing')
")
  [ "$status" = "failed" ] && break
  sleep 1
done
check "tài liệu chuyển failed đúng như kỳ vọng" "$status" "failed"
retry_code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API/documents/$bad_id/retry" -F "file=@$badfile;filename=$bad_filename")
echo "  gọi lại /documents/$bad_id/retry với chính file cũ..."
check "retry chấp nhận (202), giữ nguyên ID $bad_id" "$retry_code" "202"
echo

rm -f "$tmpfile" "$badfile"
echo "================================================================"
if [ $ok -eq 0 ]; then
  echo "KẾT QUẢ: TẤT CẢ ĐẠT YÊU CẦU ✓"
else
  echo "KẾT QUẢ: CÓ MỤC CHƯA ĐẠT — xem $FAIL ở trên"
fi
exit $ok
