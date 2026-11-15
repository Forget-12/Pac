#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SatoshiFaucet login — ROTASI PROXY SESSION + CF BYPASS (cffi/cloudscraper)
Strategi per sesi:
  1. curl_cffi homepage -> 200+csrf? lanjut. gagal -> cloudscraper.
  2. cloudscraper 403 juga? -> rotasi session baru (10s jeda).
  3. Probe POST dgn captcha sampah:
     - pesan "VPN & Proxy"  -> IP tertolak SEBELUM captcha -> rotasi (hemat token)
     - pesan captcha/CSRF   -> lolos check IP -> solve AdsLab asli -> login
  4. Berhasil -> simpan cookies ke file.
"""
import re
import json
import time
import random
import string
import cloudscraper
from curl_cffi.requests import Session

from tertuyul_solver import solve_adslab

BASE = "https://satoshifaucet.io"
EMAIL = "gi2h37@gmail.com"
ADS_SITEKEY = "lA0LtcfCXUxnBWifcQrqRsmPi6sSV3HtrpyRodRg"
PROXY_BASE = ("http://19cd190a3d8fe4a4-session-{sid}-ttl-600"
              ":f8806fc3799eca55@gate-us.vaultproxies.com:777")
FP_TZ = "America/Chicago"
FP_LANGS = "en-US,en"
MAX_SESSIONS = 12
WAIT = 10


def log(t, m): print(f"[{t}] {m}", flush=True)


def new_sid():
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=10))


def alert_msg(html):
    m = re.search(r'alert\s+text-center\s+alert-(\w+)">(?:<[^>]+>)*\s*([^<]+)', html or "")
    return m.group(2).strip() if m else None


def try_homepage(proxy):
    """Return (client, html) jika dapat homepage 200+csrf, else (None, None)."""
    s = Session(impersonate="chrome120", timeout=40, proxy=proxy)
    s.headers["Accept-Language"] = "en-US,en;q=0.9"
    try:
        r = s.get(f"{BASE}/")
        if r.status_code == 200 and "csrf_token_name" in r.text:
            return s, r.text
    except Exception as e:
        log("CF", f"cffi err: {str(e)[:50]}")

    sc = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False})
    sc.proxies = {"http": proxy, "https": proxy}
    try:
        r2 = sc.get(f"{BASE}/")
        if r2.status_code == 200 and "csrf_token_name" in r2.text:
            return sc, r2.text
        log("CF", f"cloudscraper -> HTTP {r2.status_code}")
    except Exception as e:
        log("CF", f"cloudscraper err: {str(e)[:50]}")
    return None, None


def post_login(client, csrf, token):
    return client.post(f"{BASE}/auth/login", data={
        "wallet": EMAIL, "csrf_token_name": csrf,
        "ls": FP_LANGS, "uf": "0" * 32, "utt": FP_TZ,
        "captcha": "adslab", "alcaptcha-response": token,
    }, allow_redirects=False)


def main():
    for attempt in range(1, MAX_SESSIONS + 1):
        sid = new_sid()
        proxy = PROXY_BASE.format(sid=sid)
        log("ROT", f"=== Sesi {attempt}/{MAX_SESSIONS} ({sid}) ===")

        client, html = try_homepage(proxy)
        if not client:
            log("ROT", "CF tetap 403 -> rotasi")
            time.sleep(WAIT)
            continue
        log("ROT", f"Homepage OK via {type(client).__name__}")

        csrf = re.search(r'name="csrf_token_name"[^>]*value="([^"]+)"', html).group(1)

        # --- probe IP-check dengan captcha sampah ---
        r = post_login(client, csrf, "probe-invalid")
        loc = r.headers.get("Location")
        msg = None
        if loc:
            r2 = client.get(loc if loc.startswith("http") else BASE + loc)
            msg = alert_msg(r2.text)
        log("PROBE", f"pesan server: {msg}")

        if msg and "VPN" in msg:
            log("ROT", "IP dianggap VPN/proxy -> rotasi (tanpa boros token)")
            time.sleep(WAIT)
            continue

        # --- lolos check IP: solve captcha asli & login ---
        log("CAPTCHA", "Solve AdsLab via Tertuyul...")
        token = solve_adslab(ADS_SITEKEY, f"{BASE}/", timeout=180)
        log("CAPTCHA", f"Token OK: {token[:30]}...")

        r = post_login(client, csrf, token)
        loc = r.headers.get("Location")
        log("LOGIN", f"POST -> HTTP {r.status_code} loc={loc}")
        if loc:
            r2 = client.get(loc if loc.startswith("http") else BASE + loc)
            msg = alert_msg(r2.text)
            log("LOGIN", f"pesan: {msg}")
            logged_in = not re.search(r'form[^>]*auth/login', r2.text)
            if logged_in:
                cookies = {c.name: c.value for c in getattr(client, "cookies", []).jar} \
                    if hasattr(client.cookies, "jar") else dict(client.cookies)
                with open("sf-cookies.json", "w") as f:
                    json.dump({"sid": sid, "proxy": proxy, "cookies": cookies}, f, indent=1)
                log("SUCCESS", "🎉 LOGIN BERHASIL! cookies disimpan ke sf-cookies.json")
                return
        else:
            if r.status_code == 200:
                log("SUCCESS", "🎉 LOGIN (langsung 200)!")
                return
        log("ROT", "gagal -> rotasi")
        time.sleep(WAIT)

    log("DONE", "Habis rotasi, belum sukses.")


if __name__ == "__main__":
    main()
