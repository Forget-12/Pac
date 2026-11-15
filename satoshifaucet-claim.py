#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SatoshiFaucet CLAIM — 2 fase
  fase 1 (tanpa argumen): sesi baru -> CF bypass -> login -> cf_clearance utk
                          /faucet/* -> ambil challenge -> simpan c-cosmos.png
  fase 2 (--pts "x1,y1;x2,y2;x3,y3"): POST check dgn koordinat -> POST claim
State: sf-live.json (proxy+cookies+fp+email)
"""
import re
import json
import time
import random
import string
import sys
import base64
import cloudscraper
import requests

from tertuyul_solver import solve_adslab, API_KEY, BASE as TAPI

BASE = "https://satoshifaucet.io"
EMAIL = "chusmyoh@gmail.com"
ADS_SITEKEY = "lA0LtcfCXUxnBWifcQrqRsmPi6sSV3HtrpyRodRg"
COIN = "ltc"
PI_USER, PI_PASS = "N9MNrSuT", "PEVxW4oEp7"
STATE = "sf-live.json"
ATT, WAIT = 3, 10
TZ = "Europe/Paris"
LANGS = "fr-FR,fr,en-US,en"


def log(t, m): print(f"[{t}] {m}", flush=True)


def rnd(n=6):
    return "".join(random.choices(string.ascii_letters + string.digits, k=n))


def new_session():
    sid = rnd()
    proxy = f"http://{PI_USER}:{PI_PASS}_session-{sid}_lifetime-60_country-FR@proxy.proxying.io:8080"
    s = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False})
    s.proxies = {"http": proxy, "https": proxy}
    return s


def cf_ok(r):
    return r.status_code == 200 and "csrf_token_name" in (r.text or "")


def save_state(s, fp, extra=None):
    d = {"proxy": s.proxies["http"], "cookies": dict(s.cookies), "fp": fp,
         "email": EMAIL, "ua": s.headers.get("User-Agent", "")}
    if extra: d.update(extra)
    with open(STATE, "w") as f: json.dump(d, f, indent=1)


def load_state():
    return json.load(open(STATE))


def rebuild(state):
    s = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False})
    s.proxies = {"http": state["proxy"], "https": state["proxy"]}
    if state.get("ua"): s.headers["User-Agent"] = state["ua"]
    for k, v in state["cookies"].items():
        s.cookies.set(k, v, domain="satoshifaucet.io", path="/")
    return s


def solve_cf(pageurl, proxy):
    """Tertuyul method=cloudflare -> (cf_clearance, ua)."""
    r = requests.post("http://api.tertuyul.my.id/in.php", data={
        "key": API_KEY, "method": "cloudflare", "pageurl": pageurl, "proxy": proxy,
    }, timeout=30)
    tid = r.text.strip()
    if not tid.isdigit():
        raise RuntimeError(f"CF submit: {tid}")
    deadline = time.time() + 240
    while time.time() < deadline:
        rr = requests.get(f"{TAPI}/res.php", params={
            "key": API_KEY, "action": "get", "id": tid, "json": 1}, timeout=20).json()
        if rr.get("status") == 1:
            tok, ua = rr["request"].split("::", 1)
            return tok, ua
        if "ERROR" in rr.get("request", ""):
            raise RuntimeError(rr["request"])
        time.sleep(5)
    raise RuntimeError("CF solve timeout")


def phase1():
    for i in range(1, 9):
        s = new_session()
        log("CF", f"--- literasi {i} ---")
        got = False
        for a in range(1, ATT + 1):
            try:
                r = s.get(f"{BASE}/")
            except Exception as e:
                log("CF", f"[{a}/3] err {str(e)[:50]}"); time.sleep(WAIT); continue
            log("CF", f"[{a}/3] HTTP {r.status_code} {cf_ok(r) and 'OK'}")
            if cf_ok(r): got = True; break
            time.sleep(WAIT)
        if not got:
            continue
        fp = "".join(random.choices("0123456789abcdef", k=32))
        s.cookies.set("uf", fp, domain="satoshifaucet.io", path="/")
        s.cookies.set("utt", TZ, domain="satoshifaucet.io", path="/")
        s.cookies.set("ls", LANGS, domain="satoshifaucet.io", path="/")

        log("CAP", "solve AdsLab...")
        tok = solve_adslab(ADS_SITEKEY, f"{BASE}/", timeout=180)
        csrf = re.search(r'name="csrf_token_name"[^>]*value="([^"]+)"', r.text).group(1)
        r2 = s.post(f"{BASE}/auth/login", data={
            "wallet": EMAIL, "csrf_token_name": csrf, "ls": LANGS, "uf": fp,
            "utt": TZ, "captcha": "adslab", "alcaptcha-response": tok,
        }, allow_redirects=False)
        loc = r2.headers.get("Location")
        body = r3.text if loc and (r3 := s.get(loc if loc.startswith("http") else BASE + loc)) else r2.text
        m = re.search(r'alert\s+text-center\s+alert-(\w+)">(?:<[^>]+>)*\s*([^<]+)', body)
        if m: log("LOGIN", f"pesan: {m.group(2).strip()}")
        if re.search(r'form[^>]*auth/login', body):
            log("LOGIN", "gagal -> literasi baru"); continue
        log("LOGIN", "OK ✅")

        log("CF2", "solve CF utk /faucet/* via Tertuyul...")
        cftok, cfua = solve_cf(f"{BASE}/faucet/currency/{COIN}", s.proxies["http"])
        s.headers["User-Agent"] = cfua
        s.cookies.set("cf_clearance", cftok, domain="satoshifaucet.io", path="/")
        log("CF2", f"cf_clearance OK (UA {cfua[:40]}...)")

        rf = s.get(f"{BASE}/faucet/currency/{COIN}")
        if rf.status_code != 200 or "csrf_token_name" not in rf.text:
            log("FAUCET", f"HTTP {rf.status_code} -> cf_clearance gagal, literasi baru")
            continue
        csrf = re.search(r'name="csrf_token_name"[^>]*value="([^"]+)"', rf.text).group(1)
        ftoken = re.search(r'name="token"\s+value="([^"]+)"', rf.text).group(1)
        nonce = re.search(r'name="claim_nonce"\s+value="([^"]+)"', rf.text).group(1)
        log("FAUCET", f"OK | csrf {csrf[:10]} | nonce {nonce[:12]}")

        s.headers["X-Requested-With"] = "XMLHttpRequest"
        rc = s.get(f"{BASE}/cosmos/challenge/{COIN}_{'faucet_'+COIN if False else ''}{'faucet_'+COIN}"
                   if False else f"{BASE}/cosmos/challenge/faucet_{COIN}?_={int(time.time()*1000)}")
        ch = rc.json()
        open("c-cosmos.png", "wb").write(base64.b64decode(ch["img"].split(",", 1)[1]))
        save_state(s, fp, {"csrf": csrf, "ftoken": ftoken, "nonce": nonce,
                           "ctoken": ch["token"]})
        log("CHALLENGE", f"token {ch['token'][:14]}... | gambar disimpan c-cosmos.png")
        log("NEXT", 'baca gambar lalu: python satoshifaucet-claim.py --pts "x1,y1;x2,y2;x3,y3"')
        return
    log("FATAL", "habis literasi")


def phase2(pts):
    st = load_state()
    s = rebuild(st)
    csrf, ctoken = st["csrf"], st["ctoken"]
    s.headers["X-Requested-With"] = "XMLHttpRequest"
    r = s.post(f"{BASE}/cosmos/check/faucet_{COIN}", data={
        "csrf_token_name": csrf, "token": ctoken, "hp": "", "pts": pts})
    log("CHECK", f"HTTP {r.status_code}: {r.text[:150]}")
    try: j = r.json()
    except: return
    if j.get("ok") and j.get("pass"):
        log("CHECK", "PASS OK ✅")
        csrf2 = j.get("csrf") or csrf
        rcl = s.post(f"{BASE}/faucet/verify/{COIN}", data={
            "csrf_token_name": csrf2, "token": st["ftoken"],
            "claim_nonce": st["nonce"], "uf": st["fp"], "utt": TZ, "ls": LANGS,
            "captcha": "sf_cosmos", "sfz_pass": j["pass"], "sfz_hp": "",
            "wallet": st["email"]}, allow_redirects=False)
        loc = rcl.headers.get("Location")
        log("CLAIM", f"POST -> {rcl.status_code} loc={loc}")
        if loc:
            rfin = s.get(loc if loc.startswith("http") else BASE + loc)
            m = re.search(r'alert\s+text-center\s+alert-(\w+)">(?:<[^>]+>)*\s*([^<]+)', rfin.text)
            log("CLAIM", f"pesan: {m.group(2).strip() if m else '(tidak ada alert)'}")
            open("/data/data/com.termux/files/usr/tmp/opencode/sf-claim-result.html", "w").write(rfin.text)
        else:
            open("/data/data/com.termux/files/usr/tmp/opencode/sf-claim-result.html", "w").write(rcl.text)
    else:
        log("CHECK", "salah — challenge perlu diambil lagi (jalankan fase 1)")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--pts":
        phase2(sys.argv[2])
    else:
        phase1()
