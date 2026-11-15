#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
#  SatoshiFaucet — ONE-SHOT NONSTOP RUNNER (proot Ubuntu + Xvfb)
#  Email  : gi2h370@gmail.com
#  Koin   : ltc (default)  •  Jalur : direct -> fallback proxy+PAC
#
#  Satu langkah:
#    1. Cek tool wajib (python / proot-distro / Xvfb)
#    2. Mulai Xvfb :99 persistent (atau pakai yang sudah jalan)
#    3. Bersihkan lock profil Chromium sisa crash
#    4. Resolusi proxy SID Prancis acak jika CF bandel (auto di bot)
#    5. Jalankan bot NONSTOP — auto-restart bila crash
#    6. Semua aksi live-time ke terminal + sf-noproxy.log / sf-noproxy.stdout
#
#  Jalankan:   ./run-satoshifaucet.sh
#  Stop:       Ctrl-C (kill bot + chromium dengan rapi)
# ============================================================
set -u
cd "$(dirname "$0")"
DISPNO=99
HERE="$(pwd)"
LOG_OUT=sf-noproxy.stdout
LOG_RUN=sf-run.log

echo "============================================================"
echo "[RUN] $(date '+%F %T') SatoshiFaucet nonstop — one-shot"
echo "[RUN] direktori : $HERE"
echo "============================================================"

# ---------- 1. cek tool wajib ----------
miss=0
for t in python proot-distro Xvfb; do
  if command -v "$t" >/dev/null 2>&1; then
    echo "[RUN] ok  $t -> $(command -v "$t")"
  else
    echo "[RUN] MISSING: $t"; miss=1
  fi
done
[ "$miss" = "1" ] && { echo "[RUN] tool wajib hilang — hentikan."; exit 1; }

# proot Ubuntu + Chromium (untuk CF solve & browser claim)
if ! proot-distro login ubuntu -- bash -c 'command -v xvfb-run >/dev/null && command -v node >/dev/null' >/dev/null 2>&1; then
  echo "[RUN] proot Ubuntu belum siap (butuh node + xvfb-run). jalankan setup-ubuntu dulu."
  echo "[RUN] cek: proot-distro login ubuntu -- bash -c 'node -v; xvfb-run -a true'"
  exit 1
fi

# ---------- 2. mulai Xvfb :99 ----------
if pgrep -x Xvfb >/dev/null 2>&1; then
  echo "[RUN] Xvfb sudah jalan (DISPLAY=:$DISPNO)"
else
  rm -f /tmp/.X${DISPNO}-lock
  echo "[RUN] mulai Xvfb :$DISPNO ..."
  nohup Xvfb :$DISPNO -screen 0 1366x768x24 > "xvfb-${DISPNO}.log" 2>&1 &
  sleep 2
  pgrep -x Xvfb >/dev/null && echo "[RUN] Xvfb :$DISPNO aktif" || { echo "[RUN] GAGAL mulai Xvfb"; exit 1; }
fi
export DISPLAY=:$DISPNO

# ---------- 3. bersihkan lock Chromium lama ----------
shopt -s nullglob
for pat in /tmp/chrome-claim-* /tmp/puppeteer_dev_* /root/.cache/.org.chromium.Chromium; do
  rm -rf "$pat" 2>/dev/null
done
shopt -u nullglob
# lock di profil persisten (hapus file lock saja, bukan seluruh profil)
find /tmp/chrome-claim-profile -maxdepth 1 \( -name 'Singleton*' -o -name 'DevToolsActivePort' \) -delete 2>/dev/null
echo "[RUN] profil Chromium sisa crash dibersihkan"

# ---------- 4. trap Ctrl-C ----------
cleanup() {
  echo ""
  echo "[RUN] $(date '+%F %T') dihentikan — matikan bot & chromium..."
  for p in $(pgrep -f 'python -u satoshifaucet-noproxy.py' 2>/dev/null); do
    [ "$(cat /proc/$p/comm 2>/dev/null)" = "python" ] && kill "$p" 2>/dev/null
  done
  for p in $(pgrep -f 'node browser_claim.js|node cf_solve.js' 2>/dev/null); do
    kill "$p" 2>/dev/null
  done
  echo "[RUN] selesai."
  exit 0
}
trap cleanup INT TERM

# ---------- 5. loop nonstop ----------
echo "[RUN] bot mulai — Ctrl-C untuk berhenti"
echo "[RUN] log: $HERE/sf-noproxy.log | stdout: $LOG_OUT"
while true; do
  echo "===== $(date '+%F %T') START =====" | tee -a "$LOG_RUN"
  python -u satoshifaucet-noproxy.py 2>&1 | tee -a "$LOG_OUT"
  rc=${PIPESTATUS[0]}
  echo "===== $(date '+%F %T') EXIT rc=$rc — restart dalam 15s =====" | tee -a "$LOG_RUN"
  sleep 15
done
