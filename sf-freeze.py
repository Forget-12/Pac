#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ambil 1 challenge sf_cosmos, simpan frozen.png + token + state, lalu exit."""
import re
import json
import time
import cloudscraper
import requests
import base64

from tertuyul_solver import API_KEY, BASE as TAPI

BASE = "https://satoshifaucet.io"
COIN = "ltc"
STATE = "sf-live.json"


def solve_cf(pageurl, proxy):
    r = requests.post("http://api.tertuyul.my.id/in.php", data={
        "key": API_KEY, "method": "cloudflare", "pageurl": pageurl, "proxy": proxy,
    }, timeout=30)
    tid = r.text.strip()
    if not tid.isdigit():
        raise RuntimeError(f"CF submit: {tid}")
    dl = time.time() + 240
    while time.time() < dl:
        rr = requests.get(f"{TAPI}/res.php", params={
            "key": API_KEY, "action": "get", "id": tid, "json": 1}, timeout=20).json()
        if rr.get("status") == 1:
            tok, ua = rr["request"].split("::", 1)
            return tok, ua
        if "ERROR" in rr.get("request", ""):
            raise RuntimeError(rr["request"])
        time.sleep(5)
    raise RuntimeError("CF timeout")


def main():
    import sys
    prefix = sys.argv[1] if len(sys.argv) > 1 else "frozen"
    st = json.load(open(STATE))
    s = cloudscraper.create_scraper()
    s.proxies = {"http": st["proxy"], "https": st["proxy"]}
    if st.get("ua"):
        s.headers["User-Agent"] = st["ua"]
    for k, v in st["cookies"].items():
        s.cookies.set(k, v, domain="satoshifaucet.io", path="/")
    r = s.get(f"{BASE}/faucet/currency/{COIN}", timeout=40)
    low = r.text[:3000].lower()
    if "just a moment" in low or r.status_code == 403:
        print("CF challenge -> solve ulang...")
        cftok, cfua = solve_cf(f"{BASE}/faucet/currency/{COIN}", st["proxy"])
        s.headers["User-Agent"] = cfua
        s.cookies.set("cf_clearance", cftok, domain="satoshifaucet.io", path="/")
        r = s.get(f"{BASE}/faucet/currency/{COIN}", timeout=40)
    print("faucet HTTP", r.status_code)
    if r.status_code != 200:
        return
    s.headers["X-Requested-With"] = "XMLHttpRequest"
    rc = s.get(f"{BASE}/cosmos/challenge/faucet_{COIN}?_={int(time.time()*1000)}", timeout=40)
    ch = rc.json()
    open(f"{prefix}.png", "wb").write(base64.b64decode(ch["img"].split(",", 1)[1]))
    st["cookies"] = dict(s.cookies)
    st["ua"] = s.headers.get("User-Agent", "")
    st["csrf"] = re.search(r'name="csrf_token_name"[^>]*value="([^"]+)"', r.text).group(1)
    st["ftoken"] = re.search(r'name="token"\s+value="([^"]+)"', r.text).group(1)
    st["nonce"] = re.search(r'name="claim_nonce"\s+value="([^"]+)"', r.text).group(1)
    st["ctoken"] = ch["token"]
    json.dump(st, open(STATE, "w"), indent=1)
    print("frozen.png tersimpan | ctoken", ch["token"][:14])


if __name__ == "__main__":
    main()
