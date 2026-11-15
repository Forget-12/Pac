#!/usr/bin/env python3
"""
koala_monitor.py — Monitor read-only untuk koalafaucet.com

Sesuai dokumen ~/koala.txt (bagian 17: metode reproduksi analisa READ-ONLY).
Script ini HANYA melakukan GET ke endpoint publik:
  - dogefaucet_api?coin=<COIN>&action=status
  - dogefaucet_api?coin=<COIN>&action=recent

Tidak ada POST, tidak ada klaim, tidak ada bypass proteksi.

Pemakaian:
  python3 koala_monitor.py                 # sekali, coin SOL
  python3 koala_monitor.py --coin LTC      # sekali, coin LTC
  python3 koala_monitor.py --json          # output JSON mentah
  python3 koala_monitor.py --watch 60      # polling tiap 60 detik (jangan terlalu sering)
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error

BASE = "https://koalafaucet.com"
UA = "Mozilla/5.0"  # sama seperti perintah curl di bagian 17 dokumen
COINS = ("SOL", "DOGE", "LTC", "BNB", "BCH")


def api_get(coin: str, action: str, timeout: float = 15.0):
    """GET endpoint publik, kembalikan dict JSON atau {'ok': False, 'error': ...}."""
    url = f"{BASE}/dogefaucet_api?coin={coin}&action={action}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}"}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        return {"ok": False, "error": str(e)}


def fmt_status(s: dict) -> str:
    """Ringkas field status sesuai bagian 3 & 12 dokumen."""
    if not s.get("ok"):
        return f"  gagal mengambil status: {s.get('error', '?')}"

    # Keputusan kondisi faucet (inferensi bagian 12 dokumen)
    if s.get("blocked"):
        state = "BLOCKED (IP/device diblokir server)"
    elif not s.get("enabled") or not s.get("configured"):
        state = "CLOSED (faucet tidak aktif)"
    elif s.get("refilling"):
        state = "REFILLING (saldo faucet sedang diisi)"
    elif s.get("secondsLeft", 0) > 0:
        state = f"COOLDOWN ({s['secondsLeft']} detik lagi)"
    else:
        state = "SIAP"

    lines = [
        f"  coin          : {s.get('coin', '?')}",
        f"  kondisi       : {state}",
        f"  reward        : {s.get('amountCoin', '?')} per klaim",
        f"  interval      : {s.get('intervalMinutes', '?')} menit",
        f"  wait          : {s.get('waitSeconds', '?')} detik",
        f"  cooldown sisa : {s.get('secondsLeft', 0)} detik",
        f"  limit harian  : {s.get('claimsUsed', '?')}/{s.get('claimsMax', '?')} klaim (sisa {s.get('claimsLeft', '?')})",
        f"  powBits       : {s.get('powBits', '?')}",
        f"  turnstile     : {s.get('turnstile', '?')}",
        f"  antiAdblock   : {s.get('antiAdblock', '?')}",
        f"  requireAdLoad : {s.get('requireAdLoad', '?')}",
        f"  IP            : {s.get('ip', '?')}",
    ]
    return "\n".join(lines)


def fmt_recent(r: dict, limit: int = 10) -> str:
    """Daftar klaim terakhir (email tersamarkan), sesuai contoh 4.2 dokumen."""
    if not r.get("ok"):
        return f"  gagal mengambil recent: {r.get('error', '?')}"
    items = r.get("items", [])[:limit]
    if not items:
        return "  (kosong)"
    out = []
    for it in items:
        # 'at' = unix milidetik (contoh: 1793945877000)
        ts = time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(it.get("at", 0) / 1000))
        out.append(
            f"  {it.get('name', '?'):24s} {it.get('amount', 0):<12g} {it.get('currency', '?'):4s} {ts}"
        )
    return "\n".join(out)


def once(coin: str, as_json: bool) -> None:
    print(f"=== {coin} — {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
    s = api_get(coin, "status")
    r = api_get(coin, "recent")
    if as_json:
        print(json.dumps({"status": s, "recent": r}, indent=2, ensure_ascii=False))
        return
    print("-- STATUS")
    print(fmt_status(s))
    print("-- RECENT")
    print(fmt_recent(r))


def main() -> int:
    ap = argparse.ArgumentParser(description="Monitor read-only koalafaucet (tanpa klaim).")
    ap.add_argument("--coin", default="SOL", choices=COINS, help="koin faucet (default SOL)")
    ap.add_argument("--json", action="store_true", help="cetak JSON mentah")
    ap.add_argument("--watch", type=int, metavar="DETIK", help="polling berulang tiap N detik")
    args = ap.parse_args()

    if args.watch:
        if args.watch < 30:
            print("Interval minimal 30 detik agar tidak membebani server.", file=sys.stderr)
            return 2
        try:
            while True:
                once(args.coin, args.json)
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print("\nberhenti.")
            return 0
    else:
        once(args.coin, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
