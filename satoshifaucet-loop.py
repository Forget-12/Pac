#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SatoshiFaucet LOOP NONSTOP
Siklus per iterasi:
  1. Pastikan sesi login + cf_clearance valid (auto re-login / re-solve CF)
  2. GET /faucet/currency/<coin> -> csrf/token/nonce + hitung daily claims
  3. GET /cosmos/challenge -> simpan c-cosmos.png + tulis c-ready
  4. TUNGGU pts.txt (koordinat ditulis operator/AI setelah baca gambar)
  5. POST check -> pass -> POST claim
  6. Parse hasil (success / please-wait M:SS / error) -> tunggu timer -> ulang

Error handling:
  - 403 challenge di faucet  -> solve CF ulang via Tertuyul
  - sesi mati / form login   -> sesi baru + login ulang
  - check salah 3x           -> cooldown 60s (aturan server)
  - "banned"                 -> STOP
  - challenge tidak diisi 90s-> capture challenge baru (token basi)
Log: sf-loop.log (juga stdout)
"""
import re
import os
import io
import json
import time
import random
import string
import sys
import traceback
import cloudscraper
import requests

from tertuyul_solver import solve_adslab, API_KEY, BASE as TAPI

BASE = "https://satoshifaucet.io"
EMAIL = "chusmyoh@gmail.com"
ADS_SITEKEY = "lA0LtcfCXUxnBWifcQrqRsmPi6sSV3HtrpyRodRg"
COIN = "ltc"
PI_USER, PI_PASS = "N9MNrSuT", "PEVxW4oEp7"
VAULT_USER, VAULT_PASS = "19cd190a3d8fe4a4", "f8806fc3799eca55"
# Pool proxy DINAMIS: dipilih berdasarkan jumlah gagal beruntun (circuit-breaker)
PROXY_POOL = [
    {"name": "proxying.io", "fails": 0, "cooldown_until": 0.0,
     "make": lambda: f"http://{PI_USER}:{PI_PASS}_session-{rnd()}_lifetime-60_country-FR@proxy.proxying.io:8080"},
    {"name": "vaultproxies", "fails": 0, "cooldown_until": 0.0,
     "make": lambda: f"http://{VAULT_USER}:{VAULT_PASS}@gate-us.vaultproxies.com:777"},
]
PROXY_FAIL_LIMIT = 5
PROXY_COOLDOWN = 600


def pick_proxy():
    now = time.time()
    avail = [p for p in PROXY_POOL if p["cooldown_until"] <= now]
    if not avail:
        for p in PROXY_POOL:
            p["cooldown_until"] = 0.0
        avail = PROXY_POOL
    avail.sort(key=lambda p: (p["fails"], random.random()))
    return avail[0]


def note_proxy(p, ok):
    if ok:
        p["fails"] = 0
        return
    p["fails"] += 1
    if p["fails"] >= PROXY_FAIL_LIMIT:
        p["cooldown_until"] = time.time() + PROXY_COOLDOWN
        log("NET", f"proxy {p['name']} cooldown 10mnt ({p['fails']}x gagal)")
TZ, LANGS = "Europe/Paris", "fr-FR,fr,en-US,en"
STATE = "sf-live.json"
IMG = "c-cosmos.png"
PTSF = "pts.txt"
READY = "c-ready"
WAIT_PTS = 90          # detik menunggu koordinat sebelum capture ulang
WRONG_COOLDOWN = 60
WAIT = 10
MAX_MINUTES = int(os.getenv("MAX_MINUTES", "0"))   # 0 = nonstop


def log(t, m):
    line = f"[{time.strftime('%H:%M:%S')}] [{t}] {m}"
    print(line, flush=True)
    with open("sf-loop.log", "a") as f:
        f.write(line + "\n")


def rnd(n=6):
    return "".join(random.choices(string.ascii_letters + string.digits, k=n))


def fp_hex():
    return "".join(random.choices("0123456789abcdef", k=32))


def save_state(s, fp):
    with open(STATE, "w") as f:
        json.dump({"proxy": s.proxies["http"], "cookies": dict(s.cookies),
                   "fp": fp, "ua": s.headers.get("User-Agent", ""), "email": EMAIL}, f)


def rebuild(state):
    s = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False})
    s.proxies = {"http": state["proxy"], "https": state["proxy"]}
    if state.get("ua"):
        s.headers["User-Agent"] = state["ua"]
    for k, v in state["cookies"].items():
        s.cookies.set(k, v, domain="satoshifaucet.io", path="/")
    return s


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
    raise RuntimeError("CF solve timeout")


class Bot:
    def __init__(self):
        self.s = None
        self.fp = None
        self.cf_count = 0
        self.wrong = 0

    # ---------- infra ----------
    def new_session_logged(self):
        """Sesi baru: CF homepage -> fingerprint -> login AdsLab."""
        for i in range(1, 13):
            p_obj = pick_proxy()
            proxy = p_obj["make"]()
            s = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "mobile": False})
            s.proxies = {"http": proxy, "https": proxy}
            ok = False
            for a in range(3):
                try:
                    r = s.get(f"{BASE}/", timeout=40)
                except Exception as e:
                    log("NET", f"{p_obj['name']} homepage err (coba {a+1}/3) {str(e)[:38]}"); time.sleep(WAIT); continue
                if r.status_code == 200 and "csrf_token_name" in r.text:
                    ok = True; break
                log("CF", f"{p_obj['name']} homepage {r.status_code} (coba {a+1}/3)")
                time.sleep(WAIT)
            note_proxy(p_obj, ok)
            if not ok:
                continue
            self.fp = fp_hex()
            s.cookies.set("uf", self.fp, domain="satoshifaucet.io", path="/")
            s.cookies.set("utt", TZ, domain="satoshifaucet.io", path="/")
            s.cookies.set("ls", LANGS, domain="satoshifaucet.io", path="/")
            try:
                tok = solve_adslab(ADS_SITEKEY, f"{BASE}/", timeout=180)
            except Exception as e:
                log("CAP", f"adslab gagal: {str(e)[:50]}"); continue
            csrf = re.search(r'name="csrf_token_name"[^>]*value="([^"]+)"', r.text).group(1)
            r2 = s.post(f"{BASE}/auth/login", data={
                "wallet": EMAIL, "csrf_token_name": csrf, "ls": LANGS, "uf": self.fp,
                "utt": TZ, "captcha": "adslab", "alcaptcha-response": tok,
            }, allow_redirects=False)
            loc = r2.headers.get("Location")
            body = r2.text
            if loc:
                body = s.get(loc if loc.startswith("http") else BASE + loc, timeout=40).text
            m = re.search(r'alert\s+text-center\s+alert-(\w+)">(?:<[^>]+>)*\s*([^<]+)', body)
            if m:
                log("LOGIN", f"pesan: {m.group(2).strip()}")
                if "banned" in m.group(2).lower():
                    log("FATAL", "AKUN BANNED — STOP"); sys.exit(1)
            if re.search(r'form[^>]*auth/login', body):
                log("LOGIN", "gagal, literasi berikutnya"); continue
            self.s = s
            save_state(self.s, self.fp)
            log("LOGIN", "OK ✅")
            return True
        return False

    def ensure_cf(self):
        """cf_clearance untuk /faucet/* — selalu cek, solve bila challenge.
        Return response faucet terakhir, atau None bila gagal."""
        r = self.s.get(f"{BASE}/faucet/currency/{COIN}", timeout=40)
        low = r.text[:3000].lower()
        if "just a moment" not in low and r.status_code != 403:
            return r
        log("CF2", f"faucet {r.status_code} challenge -> solve CF")
        try:
            cftok, cfua = solve_cf(f"{BASE}/faucet/currency/{COIN}", self.s.proxies["http"])
        except Exception as e:
            log("CF2", f"gagal: {e}"); return False
        self.s.headers["User-Agent"] = cfua
        self.s.cookies.set("cf_clearance", cftok, domain="satoshifaucet.io", path="/")
        self.cf_count += 1
        save_state(self.s, self.fp)   # persist cf_clearance+UA
        log("CF2", f"cf_clearance baru OK (total {self.cf_count})")
        # verifikasi
        r2 = self.s.get(f"{BASE}/faucet/currency/{COIN}", timeout=40)
        ok = r2.status_code == 200 and "just a moment" not in r2.text[:3000].lower()
        log("CF2", f"verifikasi: HTTP {r2.status_code} {'OK' if ok else 'MASIH DIBLOK'}")
        return r2 if ok else None

    def ensure_login(self):
        if self.s is None:
            return self.new_session_logged()
        # tes sesi sekaligus CF (1 GET saja)
        r = self.ensure_cf()
        if r is None:
            log("SESI", "CF gagal")
            return False
        if re.search(r'form[^>]*auth/login', r.text):
            log("SESI", "sesi mati -> login ulang")
            self.s = None
            return self.new_session_logged()
        if r.status_code == 429:
            log("SESI", "429 rate limit -> istirahat")
            time.sleep(45)
            return False
        return r.status_code == 200

    # ---------- siklus ----------
    def cycle(self):
        if not self.ensure_login():
            log("LOOP", "sesi/CF gagal -> retry 30s"); time.sleep(30); return
        rf = getattr(self, "last_faucet", None)
        if rf is None:
            rf = self.ensure_cf()
        if rf is None:
            log("LOOP", "CF gagal -> retry 30s"); time.sleep(30); return
        self.last_faucet = None
        if rf.status_code == 429:
            log("FAUCET", "429 rate limit -> istirahat 45s"); time.sleep(45); return
        if rf.status_code != 200:
            log("FAUCET", f"HTTP {rf.status_code}"); time.sleep(15); return
        mb = re.search(r'alert\s+text-center\s+alert-(\w+)">(?:<[^>]+>)*\s*([^<]+)', rf.text)
        if mb and "banned" in mb.group(2).lower():
            log("FATAL", f"AKUN BANNED — STOP ({mb.group(2).strip()})"); sys.exit(1)
        # timer cooldown? (halaman cooldown tidak punya form claim)
        wait = re.search(r'Please wait\s*(\d+)\s*[:\s]\s*(\d+)', rf.text)
        if wait:
            secs = int(wait.group(1)) * 60 + int(wait.group(2))
            log("TIMER", f"cooldown {secs}s"); time.sleep(secs + 2); return
        if "csrf_token_name" not in rf.text:
            log("FAUCET", f"200 tanpa form: {mb.group(2).strip() if mb else '?'}")
            open("/data/data/com.termux/files/usr/tmp/opencode/sf-cooldown.html", "w").write(rf.text)
            time.sleep(15); return

        csrf = re.search(r'name="csrf_token_name"[^>]*value="([^"]+)"', rf.text)
        ftoken = re.search(r'name="token"\s+value="([^"]+)"', rf.text)
        nonce = re.search(r'name="claim_nonce"\s+value="([^"]+)"', rf.text)
        if not (csrf and ftoken and nonce):
            log("FAUCET", "form tidak lengkap")
            m = re.search(r'alert\s+text-center\s+alert-(\w+)">(?:<[^>]+>)*\s*([^<]+)', rf.text)
            log("FAUCET", f"pesan: {m.group(2).strip() if m else '?'}")
            time.sleep(15); return
        daily = re.search(r'Daily Claims[\s\S]{0,120}?(\d+)\s*/\s*(\d+)', rf.text)
        dinfo = f"{daily.group(1)}/{daily.group(2)}" if daily else "?/?"

        # timer?
        wait = re.search(r'Please wait\s*(\d+)\s*[:\s]\s*(\d+)', rf.text)
        if wait:
            secs = int(wait.group(1)) * 60 + int(wait.group(2))
            log("TIMER", f"cooldown {secs}s (daily {dinfo})")
            time.sleep(secs + 2)
            return

        # challenge
        self.s.headers["X-Requested-With"] = "XMLHttpRequest"
        rc = self.s.get(f"{BASE}/cosmos/challenge/faucet_{COIN}?_={int(time.time()*1000)}", timeout=40)
        if rc.status_code == 429:
            log("CHAL", "429 -> istirahat 45s"); time.sleep(45); return
        try:
            ch = rc.json()
        except Exception:
            log("CHAL", f"challenge bukan JSON: {rc.text[:80]}"); time.sleep(15); return
        if ch.get("error") or not ch.get("img"):
            log("CHAL", f"challenge error: {str(ch)[:80]}")
            if ch.get("wait"):
                log("CHAL", f"server minta tunggu {ch['wait']}s"); time.sleep(ch["wait"])
            return
        with open(IMG, "wb") as f:
            import base64
            raw = ch["img"]
            f.write(base64.b64decode(raw.split(",", 1)[1]))
        os.makedirs("archive", exist_ok=True)
        os.makedirs("archive_raw", exist_ok=True)
        arch_name = f"archive/{time.strftime('%Y%m%d-%H%M%S')}.png"
        open(arch_name, "wb").write(open(IMG, "rb").read())
        open(f"archive_raw/{arch_name.split('/', 1)[1].rsplit('.', 1)[0]}.b64", "w").write(raw)
        open(READY, "w").write(ch["token"])
        if os.path.exists(PTSF):
            os.remove(PTSF)   # buang koordinat basi dari challenge lama
        log("CHAL", f"gambar baru (daily {dinfo})")

        # --- SOLVER OTOMATIS (library prototype) ---
        pts = None
        auto_assign = None
        try:
            import cosmos_lib as cosmos_lib_mod
            r, info = cosmos_lib_mod.match(IMG, out_debug="c-solve-debug.png")
        except Exception as e:
            r, info, cosmos_lib_mod = None, str(e)[:60], None
        if r:
            agree = sum(1 for a in r["assign"] if a["tsem"] == a["bsem"])
            sem_ok = agree == 3
            strong = r["min_score"] >= 0.75 and agree >= 2   # 1 mismatch tapi yakin
            if (r["min_score"] >= 0.55 and sem_ok) or strong:
                pts = r["pts"]
                auto_assign = r["assign"]
                os.remove(READY)
                log("AUTO", f"solver: {pts} (score {r['min_score']:.2f}, agree {agree}/3)")
            else:
                alasan = f"score {r['min_score']:.2f}, agree {agree}/3"
                log("AUTO", f"solver ragu ({alasan}) -> manual")
        else:
            alasan = str(info)[:50]
            log("AUTO", f"solver ragu ({alasan}) -> manual")
        # --- fallback manual: tunggu pts.txt ---
        if pts is None:
            log("CHAL", f"menunggu pts.txt ({WAIT_PTS}s)")
            dl = time.time() + WAIT_PTS
            while time.time() < dl and not os.path.exists(PTSF):
                time.sleep(2)
            if not os.path.exists(PTSF):
                log("CHAL", "koordinat tak datang -> capture ulang")
                os.remove(READY)
                return
            pts = open(PTSF).read().strip()
            os.remove(PTSF); os.remove(READY)
        log("CHAL", f"pts: {pts}")

        rck = self.s.post(f"{BASE}/cosmos/check/faucet_{COIN}", data={
            "csrf_token_name": csrf.group(1), "token": ch["token"], "hp": "", "pts": pts}, timeout=60)
        try:
            j = rck.json()
        except Exception:
            if "just a moment" in rck.text.lower():
                log("CF2", "check kena CF -> solve & retry submit")
                try:
                    self.ensure_cf()
                    rck = self.s.post(f"{BASE}/cosmos/check/faucet_{COIN}",
                                      data={"csrf_token_name": csrf.group(1), "token": ch["token"],
                                            "hp": "", "pts": pts}, timeout=60)
                    j = rck.json()
                except Exception:
                    j = None
            else:
                j = None
            if j is None:
                log("CHECK", f"submit gagal: {rck.text[:80]}"); time.sleep(10); return
        if not (j.get("ok") and j.get("pass")):
            self.wrong += 1
            log("CHECK", f"SALAH ({self.wrong}x) -> capture ulang")
            try:
                idx = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "img": arch_name,
                       "pts": pts, "mode": "auto" if auto_assign else "manual",
                       "assign": auto_assign or [], "result": "wrong"}
                with open("archive_index.jsonl", "a") as f:
                    f.write(__import__("json").dumps(idx, ensure_ascii=False) + "\n")
            except Exception as e:
                log("IDX", f"gagal indeks: {str(e)[:60]}")
            if self.wrong >= 3:
                log("CHECK", f"3x salah -> cooldown {WRONG_COOLDOWN}s")
                time.sleep(WRONG_COOLDOWN); self.wrong = 0
            return
        self.wrong = 0
        log("CHECK", "PASS ✅")
        try:
            idx = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "img": arch_name,
                   "pts": pts, "mode": "auto" if auto_assign else "manual",
                   "assign": auto_assign or [], "result": "pass"}
            with open("archive_index.jsonl", "a") as f:
                f.write(__import__("json").dumps(idx, ensure_ascii=False) + "\n")
        except Exception as e:
            log("IDX", f"gagal indeks: {str(e)[:60]}")
        # library belajar dari jawaban yang dikonfirmasi server
        try:
            if auto_assign:
                n = cosmos_lib_mod.harvest_pass(IMG, auto_assign)
                log("LIB", f"library +{n} prototype (total diperbarui)")
        except Exception as e:
            log("LIB", f"gagal harvest: {str(e)[:50]}")

        rcl = self.s.post(f"{BASE}/faucet/verify/{COIN}", data={
            "csrf_token_name": j.get("csrf") or csrf.group(1), "token": ftoken.group(1),
            "claim_nonce": nonce.group(1), "uf": self.fp, "utt": TZ, "ls": LANGS,
            "captcha": "sf_cosmos", "sfz_pass": j["pass"], "sfz_hp": "",
            "wallet": EMAIL}, allow_redirects=False, timeout=60)
        loc = rcl.headers.get("Location")
        if loc:
            rfin = self.s.get(loc if loc.startswith("http") else BASE + loc, timeout=40)
            page = rfin.text
        else:
            page = rcl.text
            log("CLAIM", f"303 tanpa Location (len body={len(page)}) — cek di siklus berikut")
        mb2 = re.search(r'alert\s+text-center\s+alert-(\w+)">(?:<[^>]+>)*\s*([^<]+)', page)
        if mb2 and "banned" in mb2.group(2).lower():
            log("FATAL", f"AKUN BANNED — STOP ({mb2.group(2).strip()})"); sys.exit(1)
        w = re.search(r'Please wait\s*(\d+)\s*[:\s]\s*(\d+)', page)
        if mb2 and "danger" in mb2.group(1):
            log("CLAIM", f"⚠️ {mb2.group(2).strip()}")
        elif w:
            secs = int(w.group(1)) * 60 + int(w.group(2))
            log("CLAIM", f"🎉 SUKSES! timer {secs}s")
            time.sleep(secs + 2)
        else:
            log("CLAIM", f"status tak dikenal (HTTP {rcl.status_code})")


def main():
    log("BOOT", f"LOOP NONSTOP coin={COIN} email={EMAIL} max={MAX_MINUTES or '∞'}min")
    t0 = time.time()
    bot = Bot()
    while True:
        if bot.new_session_logged():
            break
        log("BOOT", "login awal gagal, coba lagi 30s")
        time.sleep(30)
    bot.cf_count = 1   # paksa cek CF di siklus pertama? tidak: sudah default
    bot.cf_count = 0
    cyc = 0
    err_streak = 0
    try:
        while True:
            cyc += 1
            if MAX_MINUTES and (time.time() - t0) > MAX_MINUTES * 60:
                log("BOOT", f"durasi {MAX_MINUTES}m tercapai — selesai")
                return
            try:
                bot.cycle()
                err_streak = 0
            except SystemExit:
                raise
            except Exception as e:
                err_streak += 1
                log("ERR", f"{type(e).__name__}: {str(e)[:90]}")
                log("ERR", traceback.format_exc().splitlines()[-2] if traceback.format_exc() else "")
                if err_streak >= 3:
                    log("NET", f"{err_streak}x error beruntun -> sesi baru (login ulang)")
                    bot.new_session_logged()
                    err_streak = 0
                time.sleep(20)
    except KeyboardInterrupt:
        log("BOOT", "dihentikan")


if __name__ == "__main__":
    main()
