#!/data/data/com.termux/files/usr/bin/bash
# monitor-pandax9.sh — pantau pandax9.py tiap 2 menit
# Pemakaian: ./monitor-pandax9.sh [interval_detik] [iterasi]
LOG=/data/data/com.termux/files/usr/tmp/opencode/set-ubuntu-run2.log
MON=/data/data/com.termux/files/usr/tmp/opencode/pandax9-monitor.log
INTERVAL="${1:-120}"
ITER="${2:-60}"
PREV_OK=0; PREV_FAIL=0; PREV_TOK=0
echo "=== monitor mulai $(date '+%Y-%m-%d %H:%M:%S') (interval=${INTERVAL}s, iter=${ITER}) ===" >> "$MON"

# helper: hitung baris yang cocok, paksa integer murni (grep -c selalu mencetak angka; jangan pakai || echo 0)
cnt() {
  local n
  n=$(grep -c "$1" "$LOG" 2>/dev/null)
  n=$(printf '%s' "$n" | tr -cd '0-9')
  printf '%s\n' "${n:-0}"
}

for i in $(seq 1 "$ITER"); do
  sleep "$INTERVAL"
  ts=$(date '+%H:%M:%S')
  if ! pgrep -f "pandax9.py" >/dev/null 2>&1; then
    echo "[$ts] iter=$i [MATI] proses pandax9.py tidak ada — monitor berhenti" >> "$MON"
    break
  fi
  ok=$(cnt 'SUCCESS')
  fail=$(cnt 'Habis 5 attempt')
  tok=$(cnt 'Token OK')
  refill=$(cnt 'refilling')
  # log bot bisa ter-truncate saat restart → counter mengecil; reset baseline agar delta tidak negatif
  [ "$ok" -lt "$PREV_OK" ] && PREV_OK=0
  [ "$fail" -lt "$PREV_FAIL" ] && PREV_FAIL=0
  [ "$tok" -lt "$PREV_TOK" ] && PREV_TOK=0
  d_ok=$((ok-PREV_OK)); d_fail=$((fail-PREV_FAIL)); d_tok=$((tok-PREV_TOK))
  echo "[$ts] iter=$i ok=${ok}(+${d_ok}) skip5=${fail}(+${d_fail}) tokens=${tok}(+${d_tok}) refill=${refill}" >> "$MON"
  if [ "$d_ok" -gt 0 ]; then
    grep 'SUCCESS' "$LOG" | tail -n "$d_ok" >> "$MON"
  fi
  if [ "$d_fail" -gt 0 ]; then
    grep 'Habis 5 attempt' "$LOG" | tail -n "$d_fail" >> "$MON"
  fi
  PREV_OK=$ok; PREV_FAIL=$fail; PREV_TOK=$tok
done
echo "=== monitor selesai $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$MON"
