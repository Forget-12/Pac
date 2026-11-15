#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SatoshiFaucet CF "Just a moment" bypass
Aturan (permintaan user):
  - WAJIB 3x percobaan cloudscraper per literasi
  - Tunggu 10 detik, refresh dengan SESI COOKIE YANG SAMA
  - Target IP: USA / PRANCIS / ASIA
  - Proxy: vaultproxies sticky-session (US) + proxying.io residential (FR, ID)
Berhasil -> simpan cookies + proxy ke sf-cookies.json
"""
import re
import json
import time
import random
import string
import cloudscraper

BASE = "https://satoshifaucet.io"
ADS_SITEKEY = "lA0LtcfCXUxnBWifcQrqRsmPi6sSV3HtrpyRodRg"
ATT_PER_PROXY = 3      # WAJIB 3x per literasi
WAIT = 10


def log(t, m): print(f"[{t}] {m}", flush=True)


def gen_proxy_list():
    """Vaultproxies US (sticky) + proxying.io FR sesi yg diberikan + gen baru."""
    px = []
    # vaultproxies US — sesi tetap user + beberapa sticky baru
    vp_user = "19cd190a3d8fe4a4"
    vp_pass = "f8806fc3799eca55"
    for sid in ["39135395"] + ["".join(random.choices(string.digits, k=8)) for _ in range(3)]:
        px.append(("US-vault", f"http://{vp_user}-session-{sid}-ttl-600:{vp_pass}@gate-us.vaultproxies.com:777"))
    # proxying.io FR — 5 sesi dari user + beberapa gen baru
    pi_user = "N9MNrSuT"
    pi_pass = "PEVxW4oEp7"
    for sid in ["HVYiWi", "PhmVYz", "Zz4bPu", "vWgrN5", "2YSywz"]:
        px.append(("FR-resi", f"http://{pi_user}:{pi_pass}_session-{sid}_lifetime-60_country-FR@proxy.proxying.io:8080"))
    for _ in range(3):
        sid = "".join(random.choices(string.ascii_letters + string.digits, k=6))
        px.append(("FR-resi", f"http://{pi_user}:{pi_pass}_session-{sid}_lifetime-60_country-FR@proxy.proxying.io:8080"))
    # proxying.io Asia (ID)
    for _ in range(3):
        sid = "".join(random.choices(string.ascii_letters + string.digits, k=6))
        px.append(("AS-resi", f"http://{pi_user}:{pi_pass}_session-{sid}_lifetime-60_country-ID@proxy.proxying.io:8080"))
    return px


def classify_cf(r):
    """Bedakan 'Just a moment' (challenge, bisa dicoba lagi) vs hard block."""
    low = (r.text or "")[:4000].lower()
    if "just a moment" in low:
        return "CHALLENGE"
    if "attention required" in low or r.status_code == 403:
        return "BLOCK"
    return "OK"


def ip_info(scraper):
    try:
        j = scraper.get("http://ip-api.com/json/?fields=query,country,proxy,hosting,mobile,timezone").json()
        return f"{j.get('query')} {j.get('country')} proxy={j.get('proxy')} hosting={j.get('hosting')}"
    except Exception:
        return "?"


def main():
    proxies = gen_proxy_list()
    log("INIT", f"{len(proxies)} proxy di antrian")

    for idx, (label, proxy) in enumerate(proxies, 1):
        log("PX", f"=== Literasi {idx}/{len(proxies)} [{label}] ===")
        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False})
        scraper.proxies = {"http": proxy, "https": proxy}

        for attempt in range(1, ATT_PER_PROXY + 1):
            try:
                r = scraper.get(f"{BASE}/")   # refresh SESI SAMA (cookies bertahan)
            except Exception as e:
                log("CF", f"[{attempt}/3] error: {str(e)[:70]}")
                time.sleep(WAIT)
                continue

            cls = classify_cf(r)
            has_csrf = "csrf_token_name" in (r.text or "")
            log("CF", f"[{attempt}/3] HTTP {r.status_code} -> {cls} csrf={'Y' if has_csrf else 'N'}")

            if cls == "OK" and has_csrf:
                log("IP", ip_info(scraper))
                cookies = dict(scraper.cookies)
                with open("sf-cookies.json", "w") as f:
                    json.dump({"proxy": proxy, "label": label,
                               "cookies": cookies, "html_csrf": True}, f, indent=1)
                log("SUCCESS", f"🎉 CF LEWAT! [{label}] cookies+proxy tersimpan")
                return
            time.sleep(WAIT)   # WAJIB tunggu 10 detik, refresh sesi sama

        log("PX", f"[{label}] 3x gagal -> literasi berikutnya")

    log("DONE", "Semua proxy habis, belum lolos CF.")


if __name__ == "__main__":
    main()
