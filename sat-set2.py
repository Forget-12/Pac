#!/usr/bin/env python3
import re
import os
import json
import time
import base64
import random
import requests
from curl_cffi import requests as cffi_requests
from datetime import datetime

# ==========================================
# KONFIGURASI
# ==========================================
BASE = "https://satoshifaucet.io"
RAILWAY_API = "https://gi8.up.railway.app" # API Solver Hybrid Anda
EMAIL = "gi2h370@gmail.com"               # Email FaucetPay Anda
COIN = "ltc"
TZ, LANGS = "Europe/Paris", "fr-FR,fr,en-US,en"
IMG = "c-cosmos.png"

def log(t, m): 
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [{t}] {m}", flush=True)

def fp_hex():
    return "".join(random.choices("0123456789abcdef", k=32))

class SatoshiBot:
    def __init__(self):
        self.session = cffi_requests.Session(impersonate="chrome120")
        self.fp = fp_hex()
        self.session.cookies.set("uf", self.fp, domain="satoshifaucet.io", path="/")
        self.session.cookies.set("utt", TZ, domain="satoshifaucet.io", path="/")
        self.session.cookies.set("ls", LANGS, domain="satoshifaucet.io", path="/")
        self.session.headers["Accept-Language"] = LANGS.replace(",", ";q=0.9,") + ";q=0.8"

    def get_cf_clearance(self, url):
        """Meminta cf_clearance ke Railway via cfsolve."""
        log("CF", f"Meminta cf_clearance ke Railway untuk {url}")
        try:
            resp = requests.post(f"{RAILWAY_API}/solve", json={
                "method": "CloudflareTask",
                "task": {"type": "interstitial", "websiteUrl": url}
            }, timeout=120).json()
            
            if resp.get("status") == "ready":
                return resp["solution"]["cf_clearance"]
            log("CF", f"Gagal: {resp}")
        except Exception as e:
            log("CF", f"Error koneksi ke Railway: {e}")
        return None

    def safe_get(self, url):
        """GET request dengan auto-bypass CF WAF via Railway."""
        r = self.session.get(url, timeout=30)
        if r.status_code == 403 or "just a moment" in r.text[:1000].lower():
            log("NET", f"CF WAF mendeteksi {url}. Bypass...")
            cf = self.get_cf_clearance(url)
            if cf:
                self.session.cookies.set("cf_clearance", cf, domain="satoshifaucet.io", path="/")
                r = self.session.get(url, timeout=30)
        return r

    def login(self):
        log("LOGIN", "Memulai proses login...")
        
        # 1. Buka homepage untuk CSRF & Cookies
        r = self.safe_get(f"{BASE}/")
        if "csrf_token_name" not in r.text:
            log("LOGIN", "Gagal dapat CSRF. Mungkin IP diblokir atau Cloudflare gagal.")
            return False
            
        csrf = re.search(r'name="csrf_token_name"[^>]*value="([^"]+)"', r.text).group(1)
        ls_val = re.search(r'name="ls"[^>]*value="([^"]*)"', r.text)
        ls_val = ls_val.group(1) if ls_val else LANGS
        
        # 2. Minta token AdsLab ke Railway (via Puppeteer)
        log("ADS", "Meminta token AdsLab ke Railway (Puppeteer)...")
        adslab_token = None
        
        try:
            # Kirim task ke endpoint /solve
            payload = {
                "method": "CloudflareTask",
                "task": {
                    "type": "adslab",
                    "websiteUrl": f"{BASE}/" # URL tempat widget AdsLab berada
                }
            }
            resp = requests.post(f"{RAILWAY_API}/solve", json=payload, timeout=30).json()
            
            if resp.get("status") == "pending" and resp.get("taskId"):
                task_id = resp["taskId"]
                log("ADS", f"Task dibuat: {task_id}. Menunggu hasil...")
                
                # Polling sampai token didapat (maks 60 detik)
                for _ in range(30):
                    time.sleep(2)
                    poll = requests.post(f"{RAILWAY_API}/solve", json={"taskId": task_id}).json()
                    
                    if poll.get("status") == "ready":
                        adslab_token = poll["solution"]["token"]
                        log("ADS", f"✅ Token AdsLab didapat (len={len(adslab_token)})")
                        break
                    elif poll.get("status") == "error":
                        log("ADS", f"❌ Gagal: {poll.get('err')}")
                        break
                else:
                    log("ADS", "❌ Timeout menunggu token.")
            else:
                log("ADS", f"❌ Gagal buat task: {resp}")
                
        except Exception as e:
            log("ADS", f"❌ Error koneksi ke Railway: {e}")

        if not adslab_token:
            log("LOGIN", "Gagal mendapatkan token AdsLab dari Railway.")
            return False

        # 3. POST Login ke SatoshiFaucet
        log("LOGIN", "Mengirim form login...")
        payload = {
            "wallet": EMAIL,
            "csrf_token_name": csrf,
            "ls": ls_val,
            "uf": self.fp,
            "utt": TZ,
            "captcha": "adslab",
            "alcaptcha-response": adslab_token
        }
        r2 = self.session.post(f"{BASE}/auth/login", data=payload, allow_redirects=False)
        
        if r2.status_code in (301, 302, 303):
            log("LOGIN", "✅ Login Sukses (Redirect).")
            return True
        
        log("LOGIN", f"❌ Gagal. HTTP {r2.status_code}")
        return False

    def claim(self):
        log("CLAIM", f"Memulai klaim {COIN}...")
        
        # 1. Buka halaman faucet (auto bypass WAF)
        url_faucet = f"{BASE}/faucet/currency/{COIN}"
        r = self.safe_get(url_faucet)
        
        if r.status_code != 200:
            log("CLAIM", f"Gagal buka faucet: HTTP {r.status_code}")
            return False

        # 2. Ekstrak form claim
        csrf_match = re.search(r'name="csrf_token_name"[^>]*value="([^"]+)"', r.text)
        token_match = re.search(r'name="token"\s+value="([^"]+)"', r.text)
        nonce_match = re.search(r'name="claim_nonce"\s+value="([^"]+)"', r.text)
        
        if not (csrf_match and token_match and nonce_match):
            wait = re.search(r'Please wait\s*(\d+)\s*[:\s]\s*(\d+)', r.text)
            if wait:
                secs = int(wait.group(1)) * 60 + int(wait.group(2))
                log("TIMER", f"Cooldown {secs} detik.")
                time.sleep(secs + 2)
            else:
                log("CLAIM", "Form claim tidak ditemukan. Mungkin akun belum login atau kena limit.")
                time.sleep(15)
            return False

        csrf = csrf_match.group(1)
        ftoken = token_match.group(1)
        nonce = nonce_match.group(1)

        # 3. Minta Challenge Cosmos
        log("CHAL", "Meminta challenge Cosmos...")
        rc = self.session.get(f"{BASE}/cosmos/challenge/faucet_{COIN}?_={int(time.time()*1000)}")
        try:
            ch = rc.json()
        except:
            log("CHAL", "Gagal parse JSON challenge.")
            return False
            
        if ch.get("error") or not ch.get("img"):
            log("CHAL", f"Challenge error: {ch}")
            return False
            
        with open(IMG, "wb") as f:
            f.write(base64.b64decode(ch["img"].split(",", 1)[1]))
        log("CHAL", f"Gambar disimpan di {IMG}")

        # 4. Solve Cosmos (Lokal via OpenCV)
        pts = None
        try:
            import cosmos_lib
            r_solve, info = cosmos_lib.match(IMG, out_debug="c-solve-debug.png")
            if r_solve:
                pts = r_solve["pts"]
                log("AUTO", f"Solver Cosmos sukses: {pts}")
        except Exception as e:
            log("AUTO", f"Gagal solve Cosmos otomatis: {e}")

        if not pts:
            log("CHAL", "Solver ragu. Harap isi koordinat manual (x1,y1;x2,y2;x3,y3) di pts.txt")
            start_wait = time.time()
            while time.time() - start_wait < 90:
                if os.path.exists("pts.txt"):
                    pts = open("pts.txt").read().strip()
                    os.remove("pts.txt")
                    break
                time.sleep(2)
            
            if not pts:
                log("CHAL", "Timeout menunggu manual.")
                return False
