#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# set-ubuntu.sh — Multi-Instance Solver Bootstrap (Termux→Proot)
#
# Pemakaian:
#   cd ~/panda          && ./set-ubuntu.sh setup 1
#   cd ~/python-scripts && ./set-ubuntu.sh setup 2
#
#   cd ~/panda          && ./set-ubuntu.sh run 1
#   cd ~/python-scripts && ./set-ubuntu.sh run 2
#
#   ./set-ubuntu.sh stop 1      ← stop instance 1 saja
#   ./set-ubuntu.sh stop 2      ← stop instance 2 saja
#   ./set-ubuntu.sh stop        ← stop semua
#   ./set-ubuntu.sh status      ← cek semua instance
#
# ⚠️ PROJECT_DIR = current working directory ($PWD)
#    Jadi WAJIB `cd` ke folder instance sebelum run/setup.
# ============================================================

DISTRO="ubuntu"
RESOLUTION="800x600x24"

G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; B='\033[0;34m'; N='\033[0m'
MODE="${1:-run}"
INSTANCE_ID="${2:-1}"

PROJECT_DIR="$PWD"
DISPLAY_NUM=":${INSTANCE_ID}"
LOCK_FILE="/tmp/pandax9_${INSTANCE_ID}.lock"
INSTANCE_TMPDIR="/tmp/pandax9_inst_${INSTANCE_ID}"

echo -e "${G}============================================${N}"
echo -e "${G}  Instance ${INSTANCE_ID} — DISPLAY=${DISPLAY_NUM}       ${N}"
echo -e "${G}  Project : $PROJECT_DIR${N}"
echo -e "${G}============================================${N}"

# ---------- validate ----------
if ! command -v proot-distro >/dev/null 2>&1; then
    echo -e "${R}[ERROR]${N} proot-distro belum terinstal."; exit 1
fi
if ! [[ "$INSTANCE_ID" =~ ^[1-9][0-9]*$ ]]; then
    echo -e "${R}[ERROR]${N} INSTANCE_ID harus angka >= 1 (contoh: ./set-ubuntu.sh run 1)"; exit 1
fi

# ============================================================
# HELPERS — di-embed literal ($$ tidak di-expand di sini,
#           akan di-expand oleh bash -c di dalam proot)
# ============================================================
HELPERS_SH=$(cat <<'HELPERS'
_chromium_pids_by_tag() {
    local tag="$1" pid comm
    for pid in $(pgrep -f "$tag" 2>/dev/null); do
        [ "$pid" = "$$" ] && continue
        comm=$(cat /proc/$pid/comm 2>/dev/null)
        case "$comm" in
            chromium|chrome|Chrome*) echo "$pid" ;;
        esac
    done
}
_xvfb_pids_by_display() {
    local disp="$1" pid comm
    # match DISPLAY persis: ":2" juga cocok dgn ":266" tanpa anchor → pakai ( |$)
    for pid in $(pgrep -f "Xvfb $disp( |\$)" 2>/dev/null); do
        [ "$pid" = "$$" ] && continue
        comm=$(cat /proc/$pid/comm 2>/dev/null)
        [ "$comm" = "Xvfb" ] && echo "$pid"
    done
}
_node_pids_by_project() {
    local proj="$1" pid comm
    for pid in $(pgrep -f "$proj/_solver_worker.js" 2>/dev/null); do
        [ "$pid" = "$$" ] && continue
        comm=$(cat /proc/$pid/comm 2>/dev/null)
        [ "$comm" = "node" ] && echo "$pid"
    done
}
_python_pids_pandax() {
    local pid comm
    for pid in $(pgrep -f "pandax9.py" 2>/dev/null); do
        [ "$pid" = "$$" ] && continue
        comm=$(cat /proc/$pid/comm 2>/dev/null)
        case "$comm" in python3|python) echo "$pid" ;; esac
    done
}
_kill_chromium_by_tag() {
    local pid
    for pid in $(_chromium_pids_by_tag "$1"); do
        kill -9 "$pid" 2>/dev/null
    done
}
_kill_xvfb_by_display() {
    local pid
    for pid in $(_xvfb_pids_by_display "$1"); do
        kill -9 "$pid" 2>/dev/null
    done
}
_kill_node_by_project() {
    local pid
    for pid in $(_node_pids_by_project "$1"); do
        kill -9 "$pid" 2>/dev/null
    done
}
_kill_python_pandax() {
    local pid
    for pid in $(_python_pids_pandax); do
        kill -9 "$pid" 2>/dev/null
    done
}
_kill_from_lock() {
    local lock="$1"
    [ -f "$lock" ] || return
    local p
    p=$(cat "$lock" 2>/dev/null)
    if [ -n "$p" ] && kill -0 "$p" 2>/dev/null; then
        comm=$(cat /proc/$p/comm 2>/dev/null)
        case "$comm" in
            bash|sh) kill -9 "$p" 2>/dev/null ;;
        esac
    fi
}
HELPERS
)

# ============================================================
# MODE: SETUP (jalankan sekali per instance)
# ============================================================
if [ "$MODE" = "setup" ]; then
    if [ ! -f "$PROJECT_DIR/pandax9.py" ]; then
        echo -e "${Y}[WARN]${N} pandax9.py belum ada di $PROJECT_DIR — copy dulu sebelum setup"
    fi
    mkdir -p "$PROJECT_DIR"
    echo -e "${B}[SETUP]${N} Install dependency di $DISTRO (instance ${INSTANCE_ID})..."
    INSIDE_SCRIPT="${HELPERS_SH}
set +e
apt update -y
apt install -y python3 python3-pip xvfb curl chromium \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2
pip3 install --break-system-packages curl_cffi colorama
cd '$PROJECT_DIR' || exit 1
npm init -y 2>/dev/null || true
npm install puppeteer-real-browser
echo '[SETUP] Selesai untuk $PROJECT_DIR'
"
    proot-distro login "$DISTRO" -- bash -c "$INSIDE_SCRIPT"
    exit 0
fi

# ============================================================
# MODE: STOP
# ============================================================
if [ "$MODE" = "stop" ]; then
    if [ -z "${2:-}" ]; then
        # ---- STOP SEMUA ----
        echo -e "${Y}[STOP-ALL]${N} Menghentikan semua instance..."
        INSIDE_SCRIPT="${HELPERS_SH}
set +e
for N in 1 2 3 4 5 6 7 8 9; do
    _kill_chromium_by_tag \"user-data-dir=/tmp/pandax9_inst_\$N\"
    _kill_xvfb_by_display \":\$N\"
    _kill_from_lock \"/tmp/pandax9_\$N.lock\"
    rm -f \"/tmp/pandax9_\$N.lock\"
done
_kill_node_by_project \"/data/data/com.termux/files/home\"
_kill_python_pandax
# sapu bersih sisa puppeteer
rm -rf /tmp/pandax9_inst_* /tmp/runtime-root-* 2>/dev/null
echo '[STOP-ALL] Selesai.'
"
        proot-distro login "$DISTRO" -- bash -c "$INSIDE_SCRIPT" || true
        termux-wake-unlock 2>/dev/null || true
        exit 0
    fi

    # ---- STOP INSTANCE N ----
    echo -e "${Y}[STOP]${N} Menghentikan instance ${INSTANCE_ID} saja..."
    INSIDE_SCRIPT="${HELPERS_SH}
set +e
_kill_chromium_by_tag 'user-data-dir=${INSTANCE_TMPDIR}'
_kill_node_by_project '${PROJECT_DIR}'
_kill_xvfb_by_display '${DISPLAY_NUM}'
_kill_from_lock '${LOCK_FILE}'
rm -f '${LOCK_FILE}'
rm -rf '${INSTANCE_TMPDIR}' 2>/dev/null
echo '[STOP] Instance ${INSTANCE_ID} dihentikan.'
"
    proot-distro login "$DISTRO" -- bash -c "$INSIDE_SCRIPT" || true
    termux-wake-unlock 2>/dev/null || true
    exit 0
fi

# ============================================================
# MODE: STATUS
# ============================================================
if [ "$MODE" = "status" ]; then
    INSIDE_SCRIPT="${HELPERS_SH}
set +e
for N in 1 2 3 4; do
    echo \"--- Instance \$N (DISPLAY=:\$N) ---\"
    if [ -n \"\$(_xvfb_pids_by_display \":\$N\")\" ]; then
        echo \"  Xvfb    : RUN (PID \$(_xvfb_pids_by_display \":\$N\" | tr '\n' ' '))\"
    else
        echo \"  Xvfb    : mati\"
    fi
    if [ -n \"\$(_chromium_pids_by_tag \"user-data-dir=/tmp/pandax9_inst_\$N\")\" ]; then
        echo \"  Chromium: RUN (PID \$(_chromium_pids_by_tag \"user-data-dir=/tmp/pandax9_inst_\$N\" | tr '\n' ' '))\"
    else
        echo \"  Chromium: mati\"
    fi
    if [ -f /tmp/pandax9_\$N.lock ]; then
        P=\$(cat /tmp/pandax9_\$N.lock 2>/dev/null)
        if [ -n \"\$P\" ] && kill -0 \"\$P\" 2>/dev/null; then
            echo \"  Bot     : RUN (bash PID \$P)\"
        else
            echo \"  Bot     : lock stale (hapus: ./set-ubuntu.sh stop \$N)\"
        fi
    else
        echo \"  Bot     : mati\"
    fi
    echo
done
"
    proot-distro login "$DISTRO" -- bash -c "$INSIDE_SCRIPT"
    exit 0
fi

# ============================================================
# MODE: RUN (default)
# ============================================================

# --- PID lock (cegah 2 instance ID sama) ---
if [ -f "$LOCK_FILE" ]; then
    OLD_PID=$(cat "$LOCK_FILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo -e "${R}[ERROR]${N} Instance ${INSTANCE_ID} sudah jalan (PID $OLD_PID)."
        echo -e "${Y}        Hentikan dulu: ./set-ubuntu.sh stop ${INSTANCE_ID}${N}"
        exit 1
    fi
    rm -f "$LOCK_FILE"
fi

# --- pre-flight check file ---
if [ ! -f "$PROJECT_DIR/pandax9.py" ]; then
    echo -e "${R}[ERROR]${N} pandax9.py tidak ada di $PROJECT_DIR"
    echo -e "${Y}        Jalankan: cd ~/folder-instance && ./set-ubuntu.sh run ${INSTANCE_ID}${N}"
    exit 1
fi

termux-wake-lock 2>/dev/null || true

echo -e "${B}[1/3]${N} Start Xvfb di ${DISPLAY_NUM} (kalau belum ada)..."
echo -e "${B}[2/3]${N} Bersihkan Chromium sisa instance ${INSTANCE_ID}..."
echo -e "${B}[3/3]${N} Jalankan pandax9.py di $PROJECT_DIR..."
echo -e "${Y}       Tekan Ctrl+C untuk stop.${N}"
echo "--------------------------------------------"

INSIDE_SCRIPT="${HELPERS_SH}
set +e
export DISPLAY='${DISPLAY_NUM}'
export XDG_RUNTIME_DIR='/tmp/runtime-root-${INSTANCE_ID}'
export TMPDIR='${INSTANCE_TMPDIR}'
mkdir -p \"\$XDG_RUNTIME_DIR\" \"\$TMPDIR\"
chmod 700 \"\$XDG_RUNTIME_DIR\" \"\$TMPDIR\"

# --- Xvfb ---
XVFB_PIDS=\$(_xvfb_pids_by_display '${DISPLAY_NUM}')
if [ -z \"\$XVFB_PIDS\" ]; then
    echo '[XVFB] Nyalakan Xvfb ${DISPLAY_NUM} (${RESOLUTION})...'
    rm -f '/tmp/.X${INSTANCE_ID}-lock' 2>/dev/null
    rm -f '/tmp/.X11-unix/X${INSTANCE_ID}' 2>/dev/null
    Xvfb '${DISPLAY_NUM}' -screen 0 '${RESOLUTION}' &
    sleep 1.5
else
    echo '[XVFB] Xvfb ${DISPLAY_NUM} sudah jalan (reuse PID' \$XVFB_PIDS')'
fi

# --- Bersihkan Chromium zombie instance ini ---
ZOMBIES=\$(_chromium_pids_by_tag 'user-data-dir=${INSTANCE_TMPDIR}')
if [ -n \"\$ZOMBIES\" ]; then
    echo '[BROWSER] Kill Chromium zombie instance ${INSTANCE_ID}:' \$ZOMBIES
    _kill_chromium_by_tag 'user-data-dir=${INSTANCE_TMPDIR}'
    sleep 0.5
fi
rm -rf '${INSTANCE_TMPDIR}'/puppeteer_dev_* 2>/dev/null

# --- Masuk project dir ---
cd '${PROJECT_DIR}' || {
    echo '[ERROR] Gagal cd ke ${PROJECT_DIR}'
    _kill_xvfb_by_display '${DISPLAY_NUM}'
    exit 1
}

# --- Sanity check node_modules ---
if [ ! -d node_modules/puppeteer-real-browser ]; then
    echo '[ERROR] node_modules belum ada. Jalankan: ./set-ubuntu.sh setup ${INSTANCE_ID}'
    _kill_xvfb_by_display '${DISPLAY_NUM}'
    exit 1
fi
if [ ! -x /usr/bin/chromium ]; then
    echo '[ERROR] /usr/bin/chromium tidak ada. Jalankan: ./set-ubuntu.sh setup ${INSTANCE_ID}'
    _kill_xvfb_by_display '${DISPLAY_NUM}'
    exit 1
fi

# --- tulis PID bash ke lock ---
echo \$\$ > '${LOCK_FILE}'

# --- trap Ctrl+C ---
trap '
    echo
    echo \"[APP] Stop instance ${INSTANCE_ID}...\"
    _kill_chromium_by_tag \"user-data-dir=${INSTANCE_TMPDIR}\"
    _kill_node_by_project \"${PROJECT_DIR}\"
    _kill_xvfb_by_display \"${DISPLAY_NUM}\"
    rm -f \"${LOCK_FILE}\"
    rm -rf \"${INSTANCE_TMPDIR}\" 2>/dev/null
    exit 0
' INT TERM

echo '[APP] Working dir: '\$(pwd)
echo '[APP] TMPDIR     : '\$TMPDIR
echo '[APP] DISPLAY    : '\$DISPLAY
echo '[APP] Menjalankan pandax9.py...'
echo '--------------------------------------------'

python3 -u pandax9.py
PY_EXIT=\$?

# --- cleanup setelah python exit (normal/error) ---
echo '[APP] Python exit ('\$PY_EXIT') → cleanup instance ${INSTANCE_ID}...'
_kill_chromium_by_tag 'user-data-dir=${INSTANCE_TMPDIR}'
_kill_node_by_project '${PROJECT_DIR}'
_kill_xvfb_by_display '${DISPLAY_NUM}'
rm -f '${LOCK_FILE}'
rm -rf '${INSTANCE_TMPDIR}' 2>/dev/null

exit \$PY_EXIT
"

proot-distro login "$DISTRO" -- bash -c "$INSIDE_SCRIPT"

termux-wake-unlock 2>/dev/null || true