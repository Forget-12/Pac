#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SatoshiFaucet — FINAL (single-file runner, one step, live log)
==============================================================
Email  : gi2h370@gmail.com
Koin   : ltc (default)  •  Jalur: direct -> fallback proxy+PAC (French SID acak)

Satu-satunya langkah:
    python satoshifaucet-final.py

Yang dilakukan otomatis:
  1. Cek tool wajib: python, proot-distro + Ubuntu (node & xvfb-run via proot).
  2. Bersihkan lock profil Chromium sisa crash.
  3. Jalankan bot worker (satoshifaucet-noproxy.py) NONSTOP.
     - crash => auto-restart (jeda 15s), log mulai/lagi ke sf-run.log
     - Ctrl-C => matikan bot + chromium dengan rapi
  4. Semua log live-time ke terminal + sf-noproxy.log / sf-noproxy.stdout

Worker menjalankan browser claim di dalam proot Ubuntu via xvfb-run
(PAC: challenge DIRECT, sisanya proxy Prancis).

Dipakai juga sebagai fallback yang sama dengan run-satoshifaucet.sh.
"""
import os
import re
import shutil
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)

BOT = os.path.join(HERE, "satoshifaucet-noproxy.py")
DISPNO = "99"
LOG_RUN = os.path.join(HERE, "sf-run.log")


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_RUN, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def check_tool(name):
    ok = shutil.which(name)
    log(f"{'ok' if ok else 'MISSING'}  {name} -> {ok or 'tidak ada'}")
    return bool(ok)


def proot_has_node_and_xvfb():
    try:
        r = subprocess.run(
            ["proot-distro", "login", "ubuntu", "--",
             "bash", "-c", "command -v node >/dev/null && command -v xvfb-run >/dev/null"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        return r.returncode == 0
    except Exception:
        return False


def clean_locks():
    import glob
    for pat in ("/tmp/chrome-claim-*", "/tmp/puppeteer_dev_*"):
        for p in glob.glob(pat):
            shutil.rmtree(p, ignore_errors=True)
    prof = "/tmp/chrome-claim-profile"
    for f in ("SingletonLock", "SingletonCookie", "SingletonSocket", "DevToolsActivePort"):
        try:
            os.remove(os.path.join(prof, f))
        except OSError:
            pass
    log("lock profil Chromium sisa crash dibersihkan")


def cleanup_all():
    log("Ctrl-C — matikan bot & chromium...")
    for cmd in ("pkill -f 'satoshifaucet-noproxy.py'",
                "pkill -f 'browser_claim.js'",
                "pkill -f 'cf_solve.js'"):
        subprocess.run(cmd, shell=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log("selesai.")
    sys.exit(0)


def run_bot():
    log("bot worker START")
    p = subprocess.Popen([sys.executable, "-u", BOT],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, bufsize=1)
    for line in p.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
    p.wait()
    log(f"bot worker EXIT rc={p.returncode}")
    return p.returncode


def main():
    log("============================================================")
    log("[FINAL] SatoshiFaucet — single-file runner (nonstop)")
    log(f"[FINAL] dir : {HERE}")
    log("============================================================")

    ok = True
    ok &= check_tool("python")
    ok &= check_tool("proot-distro")
    if not proot_has_node_and_xvfb():
        log("proot Ubuntu belum siap (butuh node + xvfb-run)")
        ok = False
    if not os.path.exists(BOT):
        log(f"worker bot tidak ada: {BOT}")
        ok = False
    if not ok:
        log("tool wajib hilang — hentikan")
        return 1

    signal.signal(signal.SIGINT, lambda *a: cleanup_all())
    signal.signal(signal.SIGTERM, lambda *a: cleanup_all())
    clean_locks()

    attempt = 0
    while True:
        attempt += 1
        log(f"========== loop #{attempt} START ==========")
        rc = run_bot()
        log(f"========== loop #{attempt} EXIT rc={rc} — restart 15s ==========")
        time.sleep(15)


if __name__ == "__main__":
    sys.exit(main())
