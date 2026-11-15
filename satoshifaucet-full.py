#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SatoshiFaucet FULL FLOW — CF bypass + login + faucet discovery
Pelajaran dari ban sebelumnya:
  - uf (fingerprint) WAJIB hex-32 acak valid, BUKAN nol
  - timezone/lang WAJIB konsisten dgn geo IP proxy
  - 1 sesi = 1 email, tidak bolak-balik IP pada akun yg sama
Flow:
  A. CF bypass: 3x cloudscraper/literasi, tunggu 10s, sesi cookie sama
  B. Login (email + captcha AdsLab via Tertuyul)
  C. Verifikasi dashboard (deteksi ban)
  D. Discovery halaman faucet (untuk tahap claim)
"""
import os
import re
import sys
import json
import time
import random
import string
import requests
import cloudscraper

from tertuyul_solver import solve_adslab

BASE = "https://satoshifaucet.io"
EMAIL = "chusmyoh@gmail.com"
ADS_SITEKEY = "lA0LtcfCXUxnBWifcQrqRsmPi6sSV3HtrpyRodRg"
ATT_PER_PROXY = 3
WAIT = 10
PI_USER, PI_PASS = "N9MNrSuT", "PEVxW4oEp7"

# Mode tanpa proxy: pakai IP asli device (mobile/residential).
# trust_env=False wajib -> requests TIDAK memakai HTTP_PROXY/HTTPS_PROXY dari env.
NO_PROXY = "--no-proxy" in sys.argv or os.environ.get("SF_NO_PROXY") == "1"

if NO_PROXY:
    # buang proxy dari environment supaya requests/cloudscraper/solver
    # benar-benar konek langsung (bukan lewat gate-eu.vaultproxies dsb).
    for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
               "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(_k, None)
    os.environ["NO_PROXY"] = "*"

# Geo -> (timezone, languages). Fingerprint WAJIB konsisten dgn IP.
GEO_PROFILE = {
    "ID": ("Asia/Jakarta", "id-ID,id,en-US,en"),
    "FR": ("Europe/Paris", "fr-FR,fr,en-US,en"),
    "US": ("America/New_York", "en-US,en"),
}


def log(t, m): print(f"[{t}] {m}", flush=True)


def rnd_sid(n=6):
    return "".join(random.choices(string.ascii_letters + string.digits, k=n))


def gen_proxies():
    px = []
    for _ in range(5):
        sid = rnd_sid()
        px.append(f"http://{PI_USER}:{PI_PASS}_session-{sid}_lifetime-60_country-FR@proxy.proxying.io:8080")
    for _ in range(3):
        sid = rnd_sid()
        px.append(f"http://{PI_USER}:{PI_PASS}_session-{sid}_lifetime-60_country-ID@proxy.proxying.io:8080")
    return px


def geo_profile():
    """Deteksi negara/IP langsung (direct, trust_env=False)."""
    s = requests.Session()
    s.trust_env = False
    try:
        j = s.get("http://ip-api.com/json/?fields=status,query,country,countryCode,city,isp,org,mobile,proxy,hosting", timeout=20).json()
        if j.get("status") != "success":
            raise ValueError(j.get("message", "status != success"))
        log("IP", (f"{j.get('query')} {j.get('country')} {j.get('city')} isp={j.get('isp') or j.get('org')} "
                   f"mobile={j.get('mobile')} proxy={j.get('proxy')} hosting={j.get('hosting')}"))
        return j
    except Exception as e:
        log("IP", f"gagal deteksi geo: {str(e)[:120]}")
        return {}


def classify(r):
    low = (r.text or "")[:4000].lower()
    if "just a moment" in low: return "CHALLENGE"
    if "attention required" in low: return "BLOCK"
    return "OK"


def _new_scraper(proxy=None):
    s = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False})
    s.trust_env = False            # abaikan HTTP_PROXY/HTTPS_PROXY env
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    return s


def _try_homepage(s, tag):
    try:
        r = s.get(f"{BASE}/", timeout=45)   # sesi cookie sama, refresh
    except Exception as e:
        log("CF", f"[{tag}] err: {str(e)[:60]}")
        return None
    cls = classify(r)
    ok = cls == "OK" and "csrf_token_name" in (r.text or "")
    log("CF", f"[{tag}] HTTP {r.status_code} {cls} csrf={'Y' if ok else 'N'}")
    return r if ok else None


def cf_bypass():
    """Return scraper yg sudah lolos CF (homepage 200+csrf) atau None."""
    for i, proxy in enumerate(gen_proxies(), 1):
        log("PX", f"=== Proxy {i} [{proxy.split('_session-')[1][:6]}] ===")
        s = _new_scraper(proxy)
        for a in range(1, ATT_PER_PROXY + 1):
            r = _try_homepage(s, f"{a}/3")
            if r:
                # info IP
                try:
                    j = s.get("http://ip-api.com/json/?fields=query,country,proxy,hosting").json()
                    log("IP", f"{j.get('query')} {j.get('country')} proxy={j.get('proxy')} hosting={j.get('hosting')}")
                except Exception:
                    pass
                return s
            time.sleep(WAIT)
    return None


def cf_direct():
    """Tanpa proxy: 1 sesi, IP asli. trust_env=False -> env proxy diabaikan."""
    log("PX", "=== NO-PROXY (IP asli) ===")
    geo = geo_profile()
    s = _new_scraper()
    for a in range(1, ATT_PER_PROXY + 1):
        r = _try_homepage(s, f"{a}/{ATT_PER_PROXY}")
        if r:
            return s, geo
        time.sleep(WAIT)
    return None, geo


def main():
    geo = {}
    if NO_PROXY:
        s, geo = cf_direct()
    else:
        s = cf_bypass()
    if not s:
        log("FATAL", "CF tidak terlewati" + (" (no-proxy)" if NO_PROXY else " di semua proxy"))
        return

    # ---------- FINGERPRINT ASLI ----------
    r = s.get(f"{BASE}/", timeout=45)
    if "csrf_token_name" not in r.text:
        log("FATAL", "sesi CF hilang saat refresh")
        return
    fp = "".join(random.choices("0123456789abcdef", k=32))   # visitorId asli
    # geo: IP asli (no-proxy) atau geo proxy FR
    cc = (geo.get("countryCode") or "FR").upper()
    tz, langs = GEO_PROFILE.get(cc, ("Europe/Paris", "fr-FR,fr,en-US,en"))
    s.cookies.set("uf", fp, domain="satoshifaucet.io", path="/")
    s.cookies.set("utt", tz, domain="satoshifaucet.io", path="/")
    s.cookies.set("ls", langs, domain="satoshifaucet.io", path="/")
    s.headers["Accept-Language"] = ",".join(
        p if i == 0 else f"{p};q={max(0.9 - i * 0.1, 0.1):.1f}"
        for i, p in enumerate(langs.split(",")))
    log("FP", f"uf={fp} utt={tz} ls={langs} cc={cc}")

    csrf = re.search(r'name="csrf_token_name"[^>]*value="([^"]+)"', r.text).group(1)

    # ---------- LOGIN ----------
    log("CAPTCHA", "Solve AdsLab via Tertuyul...")
    token = solve_adslab(ADS_SITEKEY, f"{BASE}/", timeout=180)
    log("CAPTCHA", f"token {token[:30]}...")

    r2 = s.post(f"{BASE}/auth/login", data={
        "wallet": EMAIL, "csrf_token_name": csrf,
        "ls": langs, "uf": fp, "utt": tz,
        "captcha": "adslab", "alcaptcha-response": token,
    }, allow_redirects=False)
    loc = r2.headers.get("Location", "")
    log("LOGIN", f"POST -> {r2.status_code} loc={loc}")

    msg = None
    if loc:
        r3 = s.get(loc if loc.startswith("http") else BASE + loc)
        m = re.search(r'alert\s+text-center\s+alert-(\w+)">(?:<[^>]+>)*\s*([^<]+)', r3.text)
        msg = m.group(2).strip() if m else None
        body = r3.text
    else:
        body = r2.text

    log("LOGIN", f"pesan server: {msg or '(tidak ada)'}")

    if msg and "banned" in msg.lower():
        log("FATAL", "AKUN KENA BAN — hentikan")
        return
    if re.search(r'form[^>]*auth/login', body):
        log("FATAL", "belum login (form masih tampil)")
        return

    # ---------- VERIFIKASI DASHBOARD ----------
    r4 = s.get(f"{BASE}/dashboard")
    dash = r4.text
    log("DASH", f"HTTP {r4.status_code} len={len(dash)}")
    if "banned" in dash.lower():
        log("FATAL", "AKUN BANNED")
        return
    if "form" in dash and "auth/login" in dash:
        log("FATAL", "dashboard menampilkan login — sesi gagal")
        return
    open("/data/data/com.termux/files/usr/tmp/opencode/sf-dash.html", "w").write(dash)

    # ---------- DISCOVERY FAUCET ----------
    # Path asli dari dashboard: /faucet/currency/<koin> (bukan /faucet-ltc)
    for path in ["/faucet/currency/ltc", "/faucet/currency/usdt", "/faucet"]:
        rf = s.get(f"{BASE}{path}")
        log("FAUCET", f"{path} -> HTTP {rf.status_code} len={len(rf.text)}"
                     f"{' [CF CHALLENGE — butuh browser/cf_clearance]' if rf.status_code == 403 else ''}")
        if rf.status_code == 200 and "csrf_token_name" in rf.text:
            open("/data/data/com.termux/files/usr/tmp/opencode/sf-faucet-logged.html", "w").write(rf.text)
            log("FAUCET", f"OK -> disimpan sf-faucet-logged.html ({path})")
            break

    # simpan cookies utk lanjutan
    px = s.proxies.get("http") if s.proxies else None
    with open("sf-session.json", "w") as f:
        json.dump({"proxy": px, "no_proxy": NO_PROXY, "cookies": dict(s.cookies),
                   "fp": fp, "email": EMAIL}, f, indent=1)
    log("SAVE", "cookies+proxy -> sf-session.json")


if __name__ == "__main__":
    main()
