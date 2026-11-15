#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
proxy_finder.py — Cari & validasi proxy publik, tulis yang hidup ke proxies_found.txt

Pemakaian:
  python3 proxy_finder.py                  # default: validasi vs api.ipify.org
  python3 proxy_finder.py --max 60         # simpan maksimal 60 proxy terbaik
  python3 proxy_finder.py --per-source 400 # batas kandidat per sumber
  python3 proxy_finder.py --target https://pandafaucet.com/   # validasi vs faucet langsung
  python3 proxy_finder.py --concurrency 60 --timeout 8

Hasil: proxies_found.txt  (scheme://ip:port per baris, terurut dari yang paling cepat)
Catatan: proxy publik cepat mati/rotasi — jalankan ulang finder sebelum dipakai.
"""

import argparse
import asyncio
import random
import re
import sys
import time
import urllib.request

from curl_cffi.requests import AsyncSession

SOURCES = [
    # Hanya sumber dengan rate hidup bagus (tervalidasi 13 Nov 2026 vs pandafaucet.com):
    ("socks5h", "monosans-gh-socks5",      "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt"),   # 16.4%
    ("http",    "monosans-gh-http",        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt"),      # 12.5%
    ("http",    "proxifly-gh-http",        "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt"),  # 9.1%
    ("http",    "proxifly-jsdelivr-http",  "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/http/data.txt"),        # 6.5%
    ("socks5h", "proxifly-gh-socks5",      "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks5/data.txt"),  # 6.5%
]

LINE_RE = re.compile(r"^(?:(https?|socks5h?)://)?(\d{1,3}(?:\.\d{1,3}){3}):(\d{2,5})/?$")
OUT_FILE = "proxies_found.txt"


def parse_line(line):
    m = LINE_RE.match(line.strip())
    if not m:
        return None
    scheme, ip, port = m.groups()
    port = int(port)
    if not (0 < port < 65536):
        return None
    # oktet IP valid?
    if any(int(o) > 255 for o in ip.split(".")):
        return None
    return scheme, ip, port


def fetch_candidates(per_source):
    candidates = []
    for proto, tag, url in SOURCES:
        try:
            with urllib.request.urlopen(url, timeout=25) as resp:
                text = resp.read().decode("utf-8", "ignore")
        except Exception as e:
            print(f"[SRC-FAIL] {proto:7s} {tag}: {e}")
            continue
        cand = []
        seen = set()
        for line in text.splitlines():
            p = parse_line(line)
            if not p:
                continue
            _, ip, port = p
            entry = f"{proto}://{ip}:{port}"
            if entry in seen:
                continue
            seen.add(entry)
            cand.append(entry)
        random.shuffle(cand)
        cand = cand[:per_source]
        print(f"[SRC]      {proto:7s} {tag}: {len(cand)} kandidat")
        candidates.extend((tag, c) for c in cand)
    # dedupe lintas sumber (pertahankan sumber pertama)
    seen = set()
    uniq = []
    for src, p in candidates:
        if p in seen:
            continue
        seen.add(p)
        uniq.append((src, p))
    random.shuffle(uniq)
    return uniq


async def get_direct_ip():
    try:
        async with AsyncSession(impersonate="chrome110", timeout=10.0,
                                verify=False) as sess:
            r = await sess.get("https://api.ipify.org?format=json")
            return r.json().get("ip")
    except Exception:
        return None


async def check_proxy(source, proxy, target, timeout, sem, results, direct_ip):
    async with sem:
        t0 = time.time()
        sess = AsyncSession(impersonate="chrome110",
                            proxies={"http": proxy, "https": proxy},
                            timeout=timeout, verify=False)
        try:
            r = await sess.get(target)
            if r.status_code not in (200, 301, 302):
                return
            # kalau target ipify → pastikan traffic benar-benar lewat proxy
            if "ipify" in target and direct_ip:
                try:
                    ip = r.json().get("ip")
                except Exception:
                    return
                if not ip or ip == direct_ip:
                    return
            results.append((time.time() - t0, proxy, source))
        except Exception:
            pass
        finally:
            await sess.close()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="https://api.ipify.org?format=json",
                    help="URL untuk validasi (default: ipify)")
    ap.add_argument("--max", type=int, default=60, help="simpan maksimal N proxy (default 60)")
    ap.add_argument("--per-source", type=int, default=400,
                    help="maks kandidat per sumber (default 400)")
    ap.add_argument("--concurrency", type=int, default=80,
                    help="jumlah validasi paralel (default 80)")
    ap.add_argument("--timeout", type=float, default=8.0,
                    help="timeout per proxy detik (default 8)")
    args = ap.parse_args()

    print("=" * 60)
    print(" PROXY FINDER — sumber: monosans / proxifly (rate bagus saja)")
    print("=" * 60)
    print(f"Target validasi : {args.target}")
    t0 = time.time()
    candidates = fetch_candidates(args.per_source)
    print(f"Total kandidat  : {len(candidates)} (dedupe)")

    direct_ip = await get_direct_ip()
    print(f"IP direct       : {direct_ip or 'tidak diketahui'}")

    results = []
    sem = asyncio.Semaphore(args.concurrency)
    tasks = [asyncio.create_task(check_proxy(src, p, args.target, args.timeout,
                                             sem, results, direct_ip))
             for src, p in candidates]
    done = 0
    total = len(tasks)
    for fut in asyncio.as_completed(tasks):
        await fut
        done += 1
        if done % 200 == 0:
            print(f"  ... progress {done}/{total}, hidup sejauh ini: {len(results)}")

    results.sort(key=lambda x: x[0])  # tercepat duluan
    # rate hidup per sumber (berguna utk pangkas sumber jelek)
    total_per_src = {}
    for src, _ in candidates:
        total_per_src[src] = total_per_src.get(src, 0) + 1
    alive_per_src = {}
    for _, _, src in results:
        alive_per_src[src] = alive_per_src.get(src, 0) + 1
    print("-" * 60)
    print(" RATE HIDUP PER SUMBER")
    for src, tot in sorted(total_per_src.items(),
                           key=lambda kv: alive_per_src.get(kv[0], 0) / kv[1],
                           reverse=True):
        ok = alive_per_src.get(src, 0)
        print(f"   {ok:4d}/{tot:<4d}  {ok / tot * 100:5.1f}%  {src}")
    best = results[: args.max]
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write("# proxy_finder — proxy publik yang lolos validasi\n")
        f.write(f"# target={args.target}  waktu={time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        for rtt, proxy, _src in best:
            f.write(f"{proxy}\n")

    elapsed = time.time() - t0
    print("=" * 60)
    print(f" HASIL: {len(best)} proxy hidup (dari {total} kandidat) → {OUT_FILE}")
    print(f" Waktu total: {elapsed:.0f}s")
    if best:
        print(" Top 5 tercepat:")
        for rtt, proxy, _src in best[:5]:
            print(f"   {rtt:5.1f}s  {proxy}")
    else:
        print(" Tidak ada proxy hidup — coba naikkan --timeout / --per-source.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\n[-] Dihentikan.")
        sys.exit(130)
