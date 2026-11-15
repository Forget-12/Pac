#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SF-CF — sticky geo-ID session + curl_cffi (Chrome impersonation) + cloudscraper
Strategi: sesi sticky geo-ID (proxying.io _session-{sid}_lifetime-60_country-ID)
=> curl_cffi impersonate chrome124 (TLS/HTTP2 fingerprint Chrome asli)
=> retry homepage dengan COOKIE YANG SAMA (sesi sama / IP tetap), jeda 10 detik
Tujuan: lolos migrasi Cloudflare Managed Challenge di satoshifaucet.io
Iterasi: coba curl_cffi dulu, fallback cloudscraper, ulangi maks N attempt.
Status: proxying.io akun CONNECT 403 (perlu top-up), vaultproxies CF hard-block.
"""
import os
import sys
import time
import random
import string
import json

BASE = "https://satoshifaucet.io"
CE = os.environ.get("IMPERSONATE", "chrome124")
GEO = os.environ.get("GEO", "ID")
SID = os.environ.get("SID", "".join(random.choices(string.ascii_letters + string.digits, k=10)))
PI_USER, PI_PASS = "N9MNrSuT", "PEVxW4oEp7"
VAULT = ("http://19cd190a3d8fe4a4:f8806fc3799eca55@gate-us.vaultproxies.com:777")
MAX_TRY = int(os.environ.get("MAX_TRY", "10"))
WAIT = int(os.environ.get("WAIT_S", "10"))

PROXY = os.environ.get(
    "PROXY",
    f"http://{PI_USER}:{PI_PASS}_session-{SID}_lifetime-60_country-{GEO}@proxy.proxying.io:8080",
)


def log(t, m):
    print(f"[{time.strftime('%H:%M:%S')}] [{t}] {m}", flush=True)


def try_curl_cffi(jar):
    from curl_cffi import requests as cref
    s = cref.Session(impersonate=CE)
    s.proxies = {"http": PROXY, "https": PROXY}
    r1 = s.get(f"{BASE}/", cookies=jar, timeout=40)
    jar.update({k: v for k, v in r1.cookies.items()})
    return r1, jar, s


def try_cloudscraper(jar):
    import cloudscraper
    s = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False})
    s.proxies = {"http": PROXY, "https": PROXY}
    for k, v in jar.items():
        s.cookies.set(k, v, domain="satoshifaucet.io", path="/")
    r1 = s.get(f"{BASE}/", timeout=40)
    for c in s.cookies:
        jar[c.name] = c.value
    return r1, jar, s


def attempt(jar, tag):
    try:
        if tag == "cffi":
            r, jar, s = try_curl_cffi(jar)
        else:
            r, jar, s = try_cloudscraper(jar)
    except Exception as e:
        log(tag.upper(), f"EXC: {str(e)[:90]}")
        return jar, None
    low = r.text[:4000].lower()
    kind = "OK" if (r.status_code == 200 and "csrf_token_name" in r.text) else (
        "CF-JS" if ("just a moment" in low or r.status_code == 403) else f"HTTP{r.status_code}")
    log(tag.upper(), f"homepage {r.status_code} [{kind}] len={len(r.content)}")
    return jar, (r, r.status_code == 200 and "csrf_token_name" in r.text)


def main():
    log("BOOT", f"sticky geo-{GEO} sid={SID} proxy={PROXY.split('@')[-1]}")
    jar = {}
    for i in range(1, MAX_TRY + 1):
        log("TRY", f"attempt {i}/{MAX_TRY} (sesi sama, tunggu {WAIT}s)")
        for tag in ("cffi", "cloudscraper"):
            jar, res = attempt(jar, tag)
            if res and res[1]:
                log("HASIL", "✅ bypass sukses — faucet terbuka (csrf ditemukan)")
                print(json.dumps({"ok": True, "sid": SID, "cookies": jar}, indent=1))
                return 0
        if i < MAX_TRY:
            time.sleep(WAIT)
    log("HASIL", "❌ tidak lolos — perlu IP/proxy residensial lain")
    return 1


if __name__ == "__main__":
    sys.exit(main())
