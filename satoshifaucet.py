#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SatoshiFaucet.io Auto Claim — Step 1: LOGIN via AdsLab (Tertuyul solver)
Flow:
  1. GET /                    -> csrf_token_name, ls, uf, utt, cookies
  2. Tertuyul solve adslab    -> token
  3. POST /auth/login         -> wallet + csrf + honeypot + alcaptcha-response
  4. Inspeksi hasil login     -> redirect / set-password / dashboard
"""

import re
import sys
import time
import random
from curl_cffi.requests import Session
import cloudscraper

from tertuyul_solver import solve_adslab

BASE = "https://satoshifaucet.io"
EMAIL = "gi2h37@gmail.com"
PASSWORD = "Aprilia1"
ADS_SITEKEY = "lA0LtcfCXUxnBWifcQrqRsmPi6sSV3HtrpyRodRg"

# Proxy (residential/sticky vaultproxies)
# CATATAN TERVERIFIKASI (11 Nov): SEMUA exit IP vaultproxies (US gate) diblok
# Cloudflare oleh satoshifaucet.io (403 Attention Required) — 12 sesi dirotasi,
# semuanya 403. Proxy yang sama lolos ke pandafaucet. Jadi proxy ini TIDAK
# bisa dipakai utk satoshifaucet; pilihan: hotspot mobile data / provider lain.
PROXY = "http://19cd190a3d8fe4a4:f8806fc3799eca55@gate-us.vaultproxies.com:777"

# Fingerprint simulasi (FingerprintJS v4 open-source: visitorId dihitung lokal,
# server hanya bisa cek format hex-32 + konsistensi cookie <-> form field)
# PENTING: timezone/lang harus COCOK dgn geo IP keluar, bukan IP lokal!
FP_VISITOR_ID = "".join(random.choices("0123456789abcdef", k=32))
FP_TIMEZONE = "America/Chicago"   # geo IP proxy (Dallas, US)
FP_LANGS = "en-US,en"


def log(tag, msg):
    print(f"[{tag}] {msg}", flush=True)


def extract(text, pattern, default=None):
    m = re.search(pattern, text)
    return m.group(1) if m else default


def _cookie_pairs(session) -> dict:
    """Ambil semua cookie dari curl_cffi session sebagai dict."""
    return {c.name: c.value for c in session.cookies.jar}


def _sync_cookies_to_scraper(scraper, cffi_session):
    """Copy cookies curl_cffi -> cloudscraper (biar sesi 'sama')."""
    for name, value in _cookie_pairs(cffi_session).items():
        scraper.cookies.set(name, value, domain="satoshifaucet.io", path="/")


def _sync_cookies_to_cffi(cffi_session, scraper):
    """Copy cookies cloudscraper -> curl_cffi."""
    for name, value in scraper.cookies.items():
        cffi_session.cookies.set(name, value, domain="satoshifaucet.io", path="/")


def get_homepage_with_cf_retry(s, max_attempts=8, wait=10):
    """
    Lewati Cloudflare: coba curl_cffi lalu cloudscraper dgn SESI SAMA,
    tunggu `wait` detik, refresh ulang sampai dapat 200 + csrf.
    Return (html_text, source) atau (None, None).
    """
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False},
    )
    for attempt in range(1, max_attempts + 1):
        # ---- percobaan curl_cffi (TLS fingerprint chrome120) ----
        try:
            r = s.get(f"{BASE}/")
            if r.status_code == 200 and "csrf_token_name" in r.text:
                log("CF", f"curl_cffi OK di percobaan {attempt}")
                return r.text, "curl_cffi", None
            log("CF", f"[{attempt}] curl_cffi -> HTTP {r.status_code}")
            _sync_cookies_to_scraper(scraper, s)
        except Exception as e:
            log("CF", f"[{attempt}] curl_cffi error: {str(e)[:60]}")

        # ---- percobaan cloudscraper (challenge solver) ----
        try:
            r2 = scraper.get(f"{BASE}/")
            if r2.status_code == 200 and "csrf_token_name" in r2.text:
                log("CF", f"cloudscraper OK di percobaan {attempt}")
                _sync_cookies_to_cffi(s, scraper)
                return r2.text, "cloudscraper", scraper
            log("CF", f"[{attempt}] cloudscraper -> HTTP {r2.status_code}")
            _sync_cookies_to_cffi(s, scraper)
        except Exception as e:
            log("CF", f"[{attempt}] cloudscraper error: {str(e)[:60]}")

        if attempt < max_attempts:
            log("CF", f"[{attempt}] gagal, tunggu {wait}s lalu refresh (sesi sama)...")
            time.sleep(wait)

    return None, None, None


def main():
    s = Session(impersonate="chrome120", timeout=60, proxy=PROXY)
    s.headers["Accept-Language"] = "en-US,en;q=0.9"
    log("NET", f"Session dibuat via proxy -> {PROXY.split('@')[1]}")

    log("STEP1", "GET homepage via CF-retry (cffi + cloudscraper, tunggu 10s)...")
    html, source, scraper = get_homepage_with_cf_retry(s, max_attempts=8, wait=10)
    if not html:
        log("FATAL", "Homepage tidak bisa dilewati (CF hard block persist)")
        return
    log("STEP1", f"Homepage OK via {source}")
    client = scraper if source == "cloudscraper" else s

    # Fingerprint cookies — menyimulasi yang dilakukan inline JS:
    #   uf  = FingerprintJS visitorId | utt = timezone | ls = navigator.languages
    s.cookies.set("uf", FP_VISITOR_ID, domain="satoshifaucet.io", path="/")
    s.cookies.set("utt", FP_TIMEZONE, domain="satoshifaucet.io", path="/")
    s.cookies.set("ls", FP_LANGS, domain="satoshifaucet.io", path="/")
    if scraper is not None:
        scraper.cookies.set("uf", FP_VISITOR_ID, domain="satoshifaucet.io", path="/")
        scraper.cookies.set("utt", FP_TIMEZONE, domain="satoshifaucet.io", path="/")
        scraper.cookies.set("ls", FP_LANGS, domain="satoshifaucet.io", path="/")
    log("STEP1", f"fp cookies set: uf={FP_VISITOR_ID} utt={FP_TIMEZONE} ls={FP_LANGS}")

    csrf = extract(html, r'name="csrf_token_name"\s*id="token"\s*value="([^"]+)"') \
        or extract(html, r'name="csrf_token_name"[^>]*value="([^"]+)"')
    sitekey = extract(html, r'data-sitekey="([0-9A-Za-z]{20,64})"')
    log("STEP1", f"csrf={csrf} sitekey={sitekey}")

    if not csrf:
        log("FATAL", "csrf_token_name tidak ditemukan")
        return

    log("STEP2", "Solve AdsLab via Tertuyul...")
    token = solve_adslab(sitekey or ADS_SITEKEY, f"{BASE}/", timeout=180)
    log("STEP2", f"Token OK len={len(token)}: {token[:40]}...")

    log("STEP3", f"POST /auth/login via {source} (wallet={EMAIL})...")
    r2 = client.post(f"{BASE}/auth/login", data={
        "wallet": EMAIL,
        "csrf_token_name": csrf,
        "ls": FP_LANGS,
        "uf": FP_VISITOR_ID,
        "utt": FP_TIMEZONE,
        "captcha": "adslab",
        "alcaptcha-response": token,
    }, allow_redirects=False)
    log("STEP3", f"HTTP {r2.status_code} | Location: {r2.headers.get('Location','-')}")
    log("STEP3", f"Set-Cookie: {r2.headers.get('Set-Cookie','-')[:100]}")
    log("STEP3", f"Body head: {r2.text[:400]}")

    # Follow redirect manual biar bisa lihat tiap hop
    loc = r2.headers.get("Location")
    if loc:
        if loc.startswith("/"):
            loc = BASE + loc
        log("STEP4", f"Follow -> {loc}")
        r3 = client.get(loc, allow_redirects=False)
        log("STEP4", f"HTTP {r3.status_code}")

        body = r3.text
        m = re.search(r'alert\s+text-center\s+alert-(\w+)">(?:<[^>]+>)*\s*([^<]+)', body)
        if m:
            log("STEP4", f"Server message [{m.group(1)}]: {m.group(2).strip()}")
        if re.search(r'form[^>]*auth/login', body):
            log("STEP4", "STATUS: BELUM LOGIN (form login masih tampil)")
        else:
            log("STEP4", "STATUS: kemungkinan LOGIN BERHASIL")
            with open("/data/data/com.termux/files/usr/tmp/opencode/sf-session.html", "w") as f:
                f.write(body)
    else:
        log("STEP4", f"Body head: {r2.text[:400]}")


if __name__ == "__main__":
    main()
