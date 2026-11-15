#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SatoshiFaucet FULL FLOW — CF bypass + login + faucet discovery
Proxy : VaultProxies US (datacenter)
Geo   : US / en-US  (WAJIB match proxy, kalau tidak = ban)
Flow  :
  A. CF bypass (retry per proxy, health check dulu)
  B. Set fingerprint (uf hex-32, utt, ls) sesuai geo
  C. Solve AdsLab via Tertuyul
  D. POST /auth/login (+ Referer/Origin)
  E. Verifikasi dashboard (deteksi ban/login form)
  F. Discovery /faucet-*
  G. Simpan session (bisa di-resume)
"""
import os
import re
import json
import time
import random
import string
import tempfile
import cloudscraper

from tertuyul_solver import solve_adslab

# ---------------- KONFIG ----------------
BASE         = "https://satoshifaucet.io"
EMAIL        = "chusmyoh@gmail.com"
ADS_SITEKEY  = "lA0LtcfCXUxnBWifcQrqRsmPi6sSV3HtrpyRodRg"

PROXY        = "http://a22dbca34692b100:78a308fad4121b8a@gate-us.vaultproxies.com:30"

ATT_PER_PROXY   = 8        # 1 proxy -> kasih banyak kesempatan
WAIT            = 10       # jeda antar attempt CF
REQ_TIMEOUT     = 30       # timeout request (detik)
CAPTCHA_TIMEOUT = 180
CAPTCHA_RETRY   = 3

# Geo proxy = US
TZ           = "America/New_York"
LOCALE       = "en-US,en"
LANG_HEADER  = "en-US,en;q=0.9"

# Path output portable (tidak lagi hardcode Termux)
OUT_DIR      = tempfile.gettempdir()
DASH_FILE    = os.path.join(OUT_DIR, "sf-dash.html")
FAUCET_FILE  = os.path.join(OUT_DIR, "sf-faucet-logged.html")
SESSION_FILE = "sf-session.json"


# ---------------- UTIL ----------------
def log(tag, msg):
    print(f"[{tag}] {msg}", flush=True)


def gen_proxies():
    return [PROXY]


def redact_proxy(p):
    # jangan bocorkan password ke log
    try:
        scheme, rest = p.split("://", 1)
        creds, host = rest.split("@", 1)
        user = creds.split(":", 1)[0]
        return f"{scheme}://{user}:***@{host}"
    except Exception:
        return "<proxy>"


def classify(r):
    low = (r.text or "")[:6000].lower()
    if "just a moment" in low:      return "CHALLENGE"
    if "attention required" in low: return "BLOCK"
    if r.status_code in (403, 429, 503): return "BLOCK"
    return "OK"


def extract_csrf(html):
    if not html:
        return None
    m = re.search(r'name="csrf_token_name"[^>]*value="([^"]+)"', html)
    if m: return m.group(1)
    m = re.search(r'value="([^"]+)"[^>]*name="csrf_token_name"', html)
    return m.group(1) if m else None


def alert_msg(html):
    # lebih toleran daripada regex lama
    m = re.search(r'alert-(\w+)[^>]*>(.*?)</div>', html, re.S)
    if not m:
        return None
    txt = re.sub(r"<[^>]+>", "", m.group(2)).strip()
    return (m.group(1).lower(), txt)  # (tipe, pesan)


def healthcheck(proxy):
    """Cek proxy cepat sebelum buang waktu di CF."""
    try:
        s = cloudscraper.create_scraper()
        s.proxies = {"http": proxy, "https": proxy}
        j = s.get("http://ip-api.com/json/?fields=query,country,proxy,hosting",
                  timeout=8).json()
        log("IP", f"{j.get('query')} {j.get('country')} "
                  f"proxy={j.get('proxy')} hosting={j.get('hosting')}")
        return True
    except Exception as e:
        log("IP", f"healthcheck err: {str(e)[:80]}")
        return False


# ---------------- CF BYPASS ----------------
def cf_bypass():
    for i, proxy in enumerate(gen_proxies(), 1):
        log("PX", f"=== Proxy {i} [{redact_proxy(proxy)}] ===")
        if not healthcheck(proxy):
            log("PX", "skip, proxy tidak sehat")
            continue

        s = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False})
        s.proxies = {"http": proxy, "https": proxy}
        s.headers["Accept-Language"] = LANG_HEADER

        for a in range(1, ATT_PER_PROXY + 1):
            try:
                r = s.get(f"{BASE}/", timeout=REQ_TIMEOUT)
            except Exception as e:
                log("CF", f"[{a}/{ATT_PER_PROXY}] err: {str(e)[:60]}")
                time.sleep(WAIT); continue
            cls  = classify(r)
            csrf = extract_csrf(r.text or "")
            log("CF", f"[{a}/{ATT_PER_PROXY}] HTTP {r.status_code} {cls} "
                     f"csrf={'Y' if csrf else 'N'}")
            if cls == "OK" and csrf:
                return s
            time.sleep(WAIT)
    return None


# ---------------- MAIN ----------------
def main():
    s = cf_bypass()
    if not s:
        log("FATAL", "CF tidak terlewati")
        return 1

    # Refresh + ambil csrf final setelah cookie cookie CF settle
    try:
        r = s.get(f"{BASE}/", timeout=REQ_TIMEOUT)
    except Exception as e:
        log("FATAL", f"refresh err: {e}")
        return 1
    csrf = extract_csrf(r.text or "")
    if not csrf:
        log("FATAL", "sesi CF hilang saat refresh")
        return 1

    # -------- FINGERPRINT (match US) --------
    fp = "".join(random.choices("0123456789abcdef", k=32))
    s.cookies.set("uf",  fp,     domain="satoshifaucet.io", path="/")
    s.cookies.set("utt", TZ,     domain="satoshifaucet.io", path="/")
    s.cookies.set("ls",  LOCALE, domain="satoshifaucet.io", path="/")
    s.headers["Accept-Language"] = LANG_HEADER
    log("FP", f"uf={fp} utt={TZ} ls={LOCALE}")

    # -------- SOLVE CAPTCHA (dengan retry) --------
    token = None
    for k in range(1, CAPTCHA_RETRY + 1):
        log("CAPTCHA", f"attempt {k}/{CAPTCHA_RETRY} solve AdsLab...")
        try:
            token = solve_adslab(ADS_SITEKEY, f"{BASE}/", timeout=CAPTCHA_TIMEOUT)
        except Exception as e:
            log("CAPTCHA", f"err: {str(e)[:80]}")
            token = None
        if token:
            log("CAPTCHA", f"ok token={token[:30]}...")
            break
        time.sleep(5)
    if not token:
        log("FATAL", "captcha solver gagal semua attempt")
        return 1

    # -------- POST LOGIN --------
    try:
        r2 = s.post(f"{BASE}/auth/login", data={
            "wallet":             EMAIL,
            "csrf_token_name":    csrf,
            "ls":                 LOCALE,
            "uf":                 fp,
            "utt":                TZ,
            "captcha":            "adslab",
            "alcaptcha-response": token,
        }, headers={
            "Referer": f"{BASE}/",
            "Origin":  BASE,
        }, allow_redirects=False, timeout=REQ_TIMEOUT)
    except Exception as e:
        log("LOGIN", f"post err: {e}")
        return 1

    loc = r2.headers.get("Location", "")
    log("LOGIN", f"POST -> {r2.status_code} loc={loc}")

    body = ""
    if loc:
        try:
            r3 = s.get(loc if loc.startswith("http") else BASE + loc,
                       timeout=REQ_TIMEOUT)
            body = r3.text
        except Exception as e:
            log("LOGIN", f"redirect err: {e}")
            return 1
    else:
        body = r2.text

    am = alert_msg(body)
    if am:
        log("LOGIN", f"alert[{am[0]}]: {am[1]}")
        if "banned" in am[1].lower():
            log("FATAL", "AKUN KENA BAN — hentikan")
            return 1
        if "captcha" in am[1].lower():
            log("FATAL", "captcha ditolak server")
            return 1

    if re.search(r'form[^>]*auth/login', body):
        log("FATAL", "login form masih tampil (login gagal)")
        return 1

    # -------- DASHBOARD --------
    try:
        r4 = s.get(f"{BASE}/dashboard", timeout=REQ_TIMEOUT)
    except Exception as e:
        log("DASH", f"err: {e}")
        return 1
    dash = r4.text
    log("DASH", f"HTTP {r4.status_code} len={len(dash)}")

    if re.search(r'\bbanned\b', dash, re.I):
        log("FATAL", "AKUN BANNED")
        return 1
    if "auth/login" in dash and re.search(r'<form', dash):
        log("FATAL", "dashboard menampilkan login — sesi gagal")
        return 1
    with open(DASH_FILE, "w", encoding="utf-8") as f:
        f.write(dash)
    log("DASH", f"saved -> {DASH_FILE}")

    # -------- FAUCET DISCOVERY --------
    for path in ["/faucet-ltc", "/faucet-usdt", "/faucet"]:
        try:
            rf = s.get(f"{BASE}{path}", timeout=REQ_TIMEOUT)
        except Exception as e:
            log("FAUCET", f"{path} err: {e}")
            continue
        log("FAUCET", f"{path} -> {rf.status_code} len={len(rf.text)}")
        if rf.status_code == 200 and "csrf_token_name" in rf.text:
            with open(FAUCET_FILE, "w", encoding="utf-8") as f:
                f.write(rf.text)
            log("FAUCET", f"OK -> {FAUCET_FILE} ({path})")
            break

    # -------- SAVE SESSION --------
    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "proxy":   s.proxies.get("http"),
                "cookies": {c.name: c.value for c in s.cookies},
                "fp":      fp,
                "email":   EMAIL,
                "tz":      TZ,
                "locale":  LOCALE,
            }, f, indent=1)
        log("SAVE", f"session -> {SESSION_FILE}")
    except Exception as e:
        log("SAVE", f"err: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
