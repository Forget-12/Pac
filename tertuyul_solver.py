#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tertuyul Captcha Solver Client — Python
Dokumentasi: https://tertuyul.my.id/apikey/doc.html (dashboard)
API: 2captcha-style
  POST http://api.tertuyul.my.id/in.php           -> submit task -> task ID
  GET  http://api.tertuyul.my.id/res.php          -> poll hasil
       ?key=...&action=get&id=<task_id>
       ?key=...&action=getbalance

Terverifikasi hidat test (11 Nov 2026):
  method=turnstile : OK  (<5s)  -> token Cloudflare "1.abc..."
  method=adslab    : OK  (~20s) -> token UUID (untuk satoshifaucet.io)

PENTING AdsLab:
  pageurl WAJIB trailing slash ("/"), else ERROR_CAPTCHA_UNSOLVABLE.
  Param "domain=<hostname>" opsional (juga sukses saat dipakai).
"""

import re
import time
import requests

API_KEY = "90d4b91a1c3c2e430fa3e17f62a4d545"
BASE = "http://api.tertuyul.my.id"
POLL_INTERVAL = 5
POLL_MAX = 60          # maksimal putaran polling


class TertuyulError(Exception):
    pass


def _poll(key: str, task_id: str, timeout: int, proxies=None) -> str:
    url = f"{BASE}/res.php"
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(url, params={"key": key, "action": "get", "id": task_id},
                         timeout=20, proxies=proxies)
        answer = r.text.strip()
        if answer != "CAPCHA_NOT_READY":
            if answer.startswith("ERROR_"):
                raise TertuyulError(answer)
            return answer
        time.sleep(POLL_INTERVAL)
    raise TertuyulError("CLIENT_TIMEOUT")


def get_balance(proxies=None) -> str:
    r = requests.get(f"{BASE}/res.php",
                     params={"key": API_KEY, "action": "getbalance"},
                     timeout=20, proxies=proxies)
    return r.text.strip()


def solve_turnstile(sitekey: str, pageurl: str, timeout: int = 120,
                    proxies=None) -> str:
    """Turnstile (Cloudflare) -> token '1...' utk field cf-turnstile-response."""
    r = requests.post(f"{BASE}/in.php", data={
        "key": API_KEY, "method": "turnstile",
        "sitekey": sitekey, "pageurl": pageurl,
    }, timeout=30, proxies=proxies)
    task_id = r.text.strip()
    if task_id.startswith("ERROR_"):
        raise TertuyulError(task_id)
    return _poll(API_KEY, task_id, timeout, proxies)


def solve_adslab(sitekey: str, pageurl: str, timeout: int = 150,
                 proxies=None) -> str:
    """AdsLab Captcha (satoshifaucet.io) -> token UUID utk field 'alcaptcha-response'.

    pageurl HARUS ada trailing slash, contoh: "https://satoshifaucet.io/"
    """
    if not pageurl.endswith("/"):
        pageurl += "/"
    data = {
        "key": API_KEY, "method": "adslab",
        "sitekey": sitekey, "pageurl": pageurl,
        "domain": requests.utils.urlparse(pageurl).hostname,
    }
    r = requests.post(f"{BASE}/in.php", data=data, timeout=30, proxies=proxies)
    task_id = r.text.strip()
    if task_id.startswith("ERROR_"):
        raise TertuyulError(task_id)
    return _poll(API_KEY, task_id, timeout, proxies)


def solve_generic(method: str, proxies=None, **params) -> str:
    """Solver generik utk method lain (hcaptcha, recaptcha, image body, dll)."""
    data = {"key": API_KEY, "method": method, **params}
    r = requests.post(f"{BASE}/in.php", data=data, timeout=30, proxies=proxies)
    task_id = r.text.strip()
    if task_id.startswith("ERROR_"):
        raise TertuyulError(task_id)
    return _poll(API_KEY, task_id, 120, proxies)


def solve_cf_challenge(pageurl: str, html: str = "", timeout: int = 180,
                       proxies=None) -> str:
    """Cloudflare managed challenge -> token, lewat Tertuyul+proxy (full flow proxy).

    Sitekey diambil dari script api.js yang tertanam di halaman challenge
    (mis. `challenges.cloudflare.com/turnstile/v0/g/<sitekey>/api.js`).
    Return token atau raise TertuyulError.
    """
    m = re.search(r'challenges\.cloudflare\.com/turnstile/v0/g/([A-Za-z0-9_-]+)/api\.js',
                  html or "")
    sitekey = m.group(1) if m else "7c7fee70a876"
    return solve_turnstile(sitekey, pageurl, timeout=timeout, proxies=proxies)