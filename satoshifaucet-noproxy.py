#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SatoshiFaucet — NONSTOP (fixed build)
=====================================
Email  : gi2h370@gmail.com
Mode   : default direct IP (semua HTTP_PROXY/HTTPS_PROXY dari env DIBUANG).
         Kalau IP langsung terdeteksi VPN/proxy oleh situs (login ditolak) atau
         Cloudflare memblokir /faucet, alur klaim dipindah ke browser asli:
         proot Ubuntu + Xvfb + Chromium (gate-as proxy + gw.pac) untuk CF,
         lalu klaim penuh (fetch challenge/check/verify) di browser, bukan
         cloudscraper.  Proxy dipakai hanya untuk lalu-lintas utama; lewat
         gw.pac trafik challenge Cloudflare (satoshifaucet.io/cdn-cgi/* dan
         challenges.cloudflare.com) dibuat DIRECT agar challenge selesai.

Mode captcha AdsLab (human-in-the-loop, default AKTIF):
  Kalau halaman memuat widget AdsLab (grid captcha), bot TIDAK menebak/auto-solve.
  Bot PAUSE, kirim notifikasi (termux-notification + Telegram opsional), lalu
  menunggu kamu menyelesaikan captcha MANUAL dan menempelkan token
  [name=alcaptcha-response] di terminal (atau 'y' jika token sudah di clipboard).
  SF_HUMAN_CAPTCHA=0 -> kembali ke jalur otomatis lama (tidak disarankan).

Siklus:
  1. Login (email + captcha: sf_cosmos otomatis / AdsLab manual manusia)
  2. Cek /faucet/currency/<coin>
       - 200 -> lanjut claim
       - 403 "Just a moment" -> CF managed challenge -> Chromium Xvfb solve
  3. Ambil gambar captcha sf_cosmos (/cosmos/challenge)
  4. Solver otomatis (template/library/shape) -> kalau yakin, submit;
     kalau ragu -> refresh gambar (maks MAX_REFRESH=4), tidak asal tebak
  5. POST /cosmos/check -> PASS -> POST /faucet/verify -> parse hasil
  6. Pantau status tiap 2 menit -> sf-noproxy.log + sf-status.json

Perintah:
  python satoshifaucet-noproxy.py                 # nonstop
  python satoshifaucet-noproxy.py --look c-cosmos.png   # analisa gambar + koordinat
  python satoshifaucet-noproxy.py --once          # 1 siklus saja
  MAX_MINUTES=60 ...                              # batasi durasi
  SF_PROXY='http://user:pass@host:80' ...         # pakai proxy tetap (opsional)
  SF_PROXY_RANDOM=0 ...                             # 0 = daur ulang PROXY_LIST, 1 = SID acak (default)
  SF_PROXY_GEO=fr SF_PROXY_GATE=gate-eu.vaultproxies.com:80
  SF_PROXY_ACCT=acbcb24e410dbeb9 SF_PROXY_PASS=...   # kredensial gateway
  SF_PROXY_LIFE=7200                                # umur sesi sticky (detik)
  SF_EMAIL=... SF_COIN=ltc                          # ganti akun/koin
  SF_HUMAN_CAPTCHA=0/1        # 1 (default) pause+notifikasi saat AdsLab muncul
  SF_HUMAN_TIMEOUT=0          # batas tunggu manusia (detik), 0 = selamanya
  TG_BOT_TOKEN=... TG_CHAT_ID=...   # notifikasi Telegram (opsional, bisa di .env)
"""
import base64
import json
import os
import random
import re
import string
import subprocess
import sys
import threading
import time
import traceback

# ---------- NO PROXY: bersihkan env SEBELUM import jaringan dipakai ----------
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
           "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"

import cloudscraper                      # noqa: E402
import requests                          # noqa: E402

from tertuyul_solver import solve_adslab, solve_cf_challenge  # noqa: E402

BASE = "https://satoshifaucet.io"
EMAIL = os.getenv("SF_EMAIL", "gi2h370@gmail.com")
COIN = os.getenv("SF_COIN", "ltc")
ADS_SITEKEY = "lA0LtcfCXUxnBWifcQrqRsmPi6sSV3HtrpyRodRg"

# ---------- Human-in-the-loop: AdsLab Grid Captcha (PAUSE & NOTIFY) ----------
def _load_env_file():
    """Baca .env hanya untuk kunci notifikasi (jangan kotori env proxy/CF)."""
    try:
        for ln in open(".env"):
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            k, v = k.strip(), v.strip().strip("\"'")
            if k in ("TG_BOT_TOKEN", "TG_CHAT_ID") and k not in os.environ:
                os.environ[k] = v
    except Exception:
        pass


_load_env_file()
HUMAN_CAPTCHA = os.getenv("SF_HUMAN_CAPTCHA", "1") != "0"   # 1 = pause & notify
HUMAN_TIMEOUT = int(os.getenv("SF_HUMAN_TIMEOUT", "0") or 0)  # 0 = tunggu selamanya
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "").strip()
ADSLAB_MARKERS = ("adslab-captcha", "alcaptcha-container",
                  "adslab.me/alcaptcha", "alcaptcha-response")

STATE = "sf-noproxy-state.json"
LOG = "sf-noproxy.log"
STATUS = "sf-status.json"
IMG = "c-cosmos.png"
PTS = "pts.txt"
READY = "c-ready"
CF_FILE = "cf-clearance.json"          # {"cf_clearance": "...", "ua": "..."}
CF_JS = "cf_solve.js"                  # solver CF via proot Ubuntu + Xvfb
CF_BROWSER_TIMEOUT = int(os.getenv("CF_BROWSER_TIMEOUT", "240"))
BC_SETUP_TIMEOUT = int(os.getenv("BC_SETUP_TIMEOUT", "270"))   # batas menunggu setup browser-claim
CF_BROWSER_COOLDOWN = int(os.getenv("CF_BROWSER_COOLDOWN", "300"))

# Proxy fallback: dipakai hanya jika CF memblokir IP langsung.
# Daftar sesi sticky (life-7200 = 2 jam). Rotasi otomatis bila CF gagal.
PROXY_LIST = [
    "http://acbcb24e410dbeb9-geo-fr-sess-5bjci0yu-life-7200:8654fd49a819de6a@gate-eu.vaultproxies.com:80",
    "http://acbcb24e410dbeb9-geo-fr-sess-f0tkwuur-life-7200:8654fd49a819de6a@gate-eu.vaultproxies.com:80",
    "http://acbcb24e410dbeb9-geo-fr-sess-nywc7j8e-life-7200:8654fd49a819de6a@gate-eu.vaultproxies.com:80",
    "http://acbcb24e410dbeb9-geo-fr-sess-3wx4xjhl-life-7200:8654fd49a819de6a@gate-eu.vaultproxies.com:80",
    "http://acbcb24e410dbeb9-geo-fr-sess-2uhmrtd4-life-7200:8654fd49a819de6a@gate-eu.vaultproxies.com:80",
    "http://acbcb24e410dbeb9-geo-fr-sess-eg1pxgar-life-7200:8654fd49a819de6a@gate-eu.vaultproxies.com:80",
    "http://acbcb24e410dbeb9-geo-fr-sess-cllfc5sv-life-7200:8654fd49a819de6a@gate-eu.vaultproxies.com:80",
    "http://acbcb24e410dbeb9-geo-fr-sess-lrbhosk7-life-7200:8654fd49a819de6a@gate-eu.vaultproxies.com:80",
    "http://acbcb24e410dbeb9-geo-fr-sess-of6fc9vs-life-7200:8654fd49a819de6a@gate-eu.vaultproxies.com:80",
    "http://acbcb24e410dbeb9-geo-fr-sess-xjcunqlh-life-7200:8654fd49a819de6a@gate-eu.vaultproxies.com:80",
]
DEFAULT_PROXY = os.getenv("SF_PROXY", "").strip() or PROXY_LIST[0]

# Proxy SID acak: tiap putaran "CF bandel" dibuat sesi sticky BARU (life-7200)
# jadi exit-IP Prancis yang masih bersih, bukan daur-ulang IP yang sudah di-flag.
PROXY_ACCT = os.getenv("SF_PROXY_ACCT", "acbcb24e410dbeb9")
PROXY_AUTH_PASS = os.getenv("SF_PROXY_PASS", "8654fd49a819de6a")
PROXY_GATE = os.getenv("SF_PROXY_GATE", "gate-eu.vaultproxies.com:80")
PROXY_GEO = os.getenv("SF_PROXY_GEO", "fr")          # Prancis: lolos deteksi VPN situs
PROXY_LIFE = int(os.getenv("SF_PROXY_LIFE", "7200"))
PROXY_RANDOM = os.getenv("SF_PROXY_RANDOM", "1") != "0"   # default: SID acak
_SID_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"


def random_sid(n=8):
    return "".join(random.choice(_SID_CHARS) for _ in range(n))


def make_proxy(geo=None, sid=None):
    """Bangun proxy sticky Prancis dengan SID acak (exit-IP baru)."""
    geo = (geo or PROXY_GEO).strip()
    sid = sid or random_sid(8)
    return norm_proxy(f"http://{PROXY_ACCT}-geo-{geo}-sess-{sid}-life-{PROXY_LIFE}"
                      f":{PROXY_AUTH_PASS}@{PROXY_GATE}")


def norm_proxy(p):
    p = (p or "").strip()
    if not p:
        return None
    if p.startswith("https://"):
        p = "http://" + p[len("https://"):]
    elif not p.startswith("http://"):
        p = "http://" + p
    return p


def mask_proxy(p):
    if not p:
        return "-"
    try:
        at = p.rindex("@")
        scheme = p[:p.index("://") + 3]
        return scheme + "***@" + p[at + 1:]
    except Exception:
        return "***"


FALLBACK_PROXY = norm_proxy(DEFAULT_PROXY)


def _proxy_dict(p):
    """Proxy string -> dict untuk requests.proxies (None bila kosong)."""
    p = norm_proxy(p)
    if not p:
        return None
    return {"http": p, "https": p}


MONITOR_SECS = int(os.getenv("MONITOR_SECS", "120"))   # pantau tiap 2 menit
WAIT_PTS = int(os.getenv("WAIT_PTS", "30"))           # tunggu koordinat AI/manual
# HTML punya tag/newline di antara "Daily Claims" dan angkanya
DAILY_RE = r'Daily\s*Claims[\s\S]{0,240}?(\d+)\s*/\s*(\d+)'
CLAIM_GAP = int(os.getenv("CLAIM_GAP", "75"))   # jeda minimal antar claim (detik)
BLOCK_COOLDOWN = int(os.getenv("BLOCK_COOLDOWN", "900"))  # jeda jika /faucet diblok WAF (detik)
MAX_MINUTES = int(os.getenv("MAX_MINUTES", "0"))       # 0 = nonstop
WAIT = 10
CF_RETRY = MONITOR_SECS
WRONG_COOLDOWN = int(os.getenv("WRONG_COOLDOWN", "240"))

GEO_PROFILE = {
    "ID": ("Asia/Jakarta", "id-ID,id,en-US,en"),
    "FR": ("Europe/Paris", "fr-FR,fr,en-US,en"),
    "US": ("America/New_York", "en-US,en"),
}
TZ, LANGS = "Asia/Jakarta", "id-ID,id,en-US,en"

_ST = {
    "start": time.time(), "cf": "?", "daily": "?", "last": "-",
    "claims_ok": 0, "attempts": 0, "pending_pts": False, "session_age": 0,
}
_LOCK = threading.Lock()


# ------------------------------------------------------------------ util
def log(tag, msg):
    line = f"[{time.strftime('%H:%M:%S')}] [{tag}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def rnd(n=6):
    return "".join(random.choices(string.ascii_letters + string.digits, k=n))


def fp_hex():
    return "".join(random.choices("0123456789abcdef", k=32))


def set_state(**kw):
    with _LOCK:
        _ST.update(kw)


def dump_status():
    with _LOCK:
        snap = dict(_ST)
    snap["uptime_min"] = round((time.time() - snap["start"]) / 60, 1)
    snap["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    snap["email"] = EMAIL
    snap["coin"] = COIN
    try:
        json.dump(snap, open(STATUS, "w"), indent=1)
    except Exception:
        pass


def monitor_loop(stop):
    """Thread: tulis status tiap MONITOR_SECS (default 2 menit)."""
    while not stop.is_set():
        if stop.wait(MONITOR_SECS):
            break
        dump_status()
        with _LOCK:
            s = dict(_ST)
        log("MON", (f"uptime {round((time.time()-s['start'])/60,1)}m | cf={s['cf']} | "
                    f"daily={s['daily']} | claims_ok={s['claims_ok']} | "
                    f"att={s['attempts']} | pending_pts={s['pending_pts']} | last={s['last']}"))


# ------------------------------------------------------------------ session
def new_scraper(proxy=None):
    s = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False})
    s.trust_env = False          # WAJIB: jangan pakai proxy env
    s.proxies = {}
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    return s


def detect_geo(proxy=None):
    """Deteksi negara IP (langsung atau via proxy) -> fingerprint konsisten."""
    global TZ, LANGS
    s = requests.Session()
    s.trust_env = False
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    try:
        j = s.get("http://ip-api.com/json/?fields=status,query,country,countryCode,"
                  "city,isp,mobile,proxy,hosting", timeout=20).json()
        if j.get("status") != "success":
            raise ValueError(j.get("message", "?"))
        cc = (j.get("countryCode") or "ID").upper()
        TZ, LANGS = GEO_PROFILE.get(cc, GEO_PROFILE["ID"])
        log("IP", (f"{j.get('query')} {j.get('country')} {j.get('city')} "
                   f"isp={j.get('isp')} mobile={j.get('mobile')} "
                   f"proxy={j.get('proxy')} hosting={j.get('hosting')}"
                   f"{' via ' + mask_proxy(proxy) if proxy else ''}"))
        return j
    except Exception as e:
        log("IP", f"geo gagal: {str(e)[:100]} (pakai ID)")
        return {}


def load_state():
    if os.path.exists(STATE):
        try:
            return json.load(open(STATE))
        except Exception:
            return {}
    return {}


def save_state(s, fp, cf_ua=None, proxy=None, proxy_idx=None):
    prev = load_state()
    cks = dict(s.cookies) if s is not None else dict(prev.get("cookies") or {})
    if cf_ua:
        cks["__ua__"] = cf_ua
    try:
        json.dump({"cookies": cks, "fp": fp or prev.get("fp"), "email": EMAIL,
                   "tz": TZ, "langs": LANGS,
                   "proxy": proxy if proxy is not None else prev.get("proxy"),
                   "proxy_idx": (proxy_idx if proxy_idx is not None
                                 else prev.get("proxy_idx", -1))},
                  open(STATE, "w"), indent=1)
    except Exception as e:
        log("SAVE", f"gagal: {str(e)[:60]}")


def rebuild_from_state(st, proxy=None):
    s = new_scraper(proxy=proxy or st.get("proxy"))
    ua = st.get("cookies", {}).pop("__ua__", None)
    if ua:
        s.headers["User-Agent"] = ua
    for k, v in st.get("cookies", {}).items():
        try:
            s.cookies.set(k, v, domain="satoshifaucet.io", path="/")
        except Exception:
            pass
    return s


def apply_cf_override(s):
    """cf_clearance eksternal (hasil browser user) bila disediakan."""
    data = None
    if os.getenv("CF_CLEARANCE"):
        data = {"cf_clearance": os.getenv("CF_CLEARANCE"),
                "ua": os.getenv("CF_UA", "")}
    elif os.path.exists(CF_FILE):
        try:
            data = json.load(open(CF_FILE))
        except Exception:
            data = None
    if not data or not data.get("cf_clearance") or data.get("ok") is False:
        return False
    if data.get("ua"):
        s.headers["User-Agent"] = data["ua"]
    s.cookies.set("cf_clearance", data["cf_clearance"],
                  domain="satoshifaucet.io", path="/")
    log("CF", "cf_clearance eksternal dipakai (cf-clearance.json)")
    return True


def solve_cf_browser(proxy=None):
    """Jalankan Chromium di proot Ubuntu + Xvfb untuk ambil cf_clearance.
    Return dict {ok, cf_clearance, ua, cookies} atau None.
    """
    if not os.path.exists(CF_JS):
        log("CFB", f"{CF_JS} tidak ada")
        return None
    here = os.getcwd()
    inner = (f"cd {here} && "
             "unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy && "
             "export NO_PROXY='*' && "
             "xvfb-run -a --server-args='-screen 0 1280x1024x24' "
             f"node {CF_JS} {STATE} {CF_FILE}")
    cmd = ["proot-distro", "login", "ubuntu", "--", "bash", "-c", inner]
    env = {k: v for k, v in os.environ.items()
           if k.lower() not in ("http_proxy", "https_proxy", "all_proxy")}
    if proxy:
        env["CF_PROXY"] = proxy
    log("CFB", "Chromium proot Ubuntu + Xvfb: ambil cf_clearance"
               f"{' via ' + mask_proxy(proxy) if proxy else ' (direct)'}...")
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=CF_BROWSER_TIMEOUT, env=env)
    except subprocess.TimeoutExpired:
        log("CFB", f"timeout {CF_BROWSER_TIMEOUT}s")
        return None
    except Exception as e:
        log("CFB", f"gagal spawn: {str(e)[:100]}")
        return None
    out = ((p.stdout or "") + (p.stderr or "")).strip().splitlines()
    tail = " | ".join(l.strip() for l in out[-3:]) if out else "(tanpa output)"
    log("CFB", f"exit {p.returncode} ({time.time()-t0:.0f}s) {tail[:220]}")
    try:
        d = json.load(open(CF_FILE))
    except Exception:
        return None
    if not d.get("ok") or not d.get("cf_clearance"):
        return None
    return d


def _readline_timeout(f, timeout):
    """Baca satu baris dari f dengan batas waktu (pilih-pilih pakai select)."""
    import select
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r, _, _ = select.select([f], [], [], min(1.0, timeout))
        except Exception:
            r = []
        if r:
            line = f.readline()
            if line:
                return line.strip()
        time.sleep(0.2)
    return None


# ------------------------------------------------------------------ solver
def pts_to_idx(pts, cands):
    """Ubah 'x,y;...' -> index blob terdekat (untuk bandingkan 2 solver)."""
    out = []
    for p in pts.split(";"):
        try:
            x, y = map(int, p.split(","))
        except Exception:
            continue
        best = min(cands, key=lambda c: (c["x"] - x) ** 2 + (c["y"] - y) ** 2)
        out.append(best["blob"])
    return out


def analyze_image(path=IMG, verbose=True):
    """Analisa gambar captcha: template solver (utama) + library + shape.
    Return dict(pts, assign, confidence, agreement, candidates, ...) atau None.
    """
    try:
        import cv2
        import cosmos_solver as cs
        import cosmos_lib as cl
        import cosmos_templates as ct
    except Exception as e:
        log("IMG", f"modul solver tidak tersedia: {str(e)[:60]}")
        return None

    img = cv2.imread(path)
    if img is None:
        log("IMG", f"{path} tidak terbaca")
        return None
    t0 = time.time()
    icons = cs.header_icons(img)
    blobs = cs.grid_blobs(img)
    if verbose:
        log("IMG", f"{path}: ikon header={len(icons)} blob grid={len(blobs)}")

    out = {"pts": None, "assign": [], "min_score": 0.0, "candidates": [],
           "confidence": 0.0, "header_min": 0.0, "content_min": 0.0,
           "assign_margin": 0.0, "class_margin": 0.0,
           "sources": [], "agree_shape": False, "agree_lib": False,
           "lib_shape": False, "template_pts": None, "lib_pts": None,
           "shape_pts": None, "targets": [], "blob_sem": []}

    # daftar kandidat grid (indeks konsisten utk semua solver)
    for i, b in enumerate(blobs, 1):
        cx, cy = cl._tap_point(b, img)
        out["candidates"].append({
            "blob": i, "x": int(cx), "y": int(cy + cs.HEAD),
            "bbox": [int(v) for v in b["bbox"]], "area": int(b["area"]),
        })
    if verbose:
        log("IMG", "kandidat blob (x,y): " +
            ", ".join(f"#{c['blob']}=({c['x']},{c['y']})" for c in out["candidates"]))

    # 1) template solver (utama)
    tres, tinfo = ct.solve(path, debug=True)
    if tres:
        out["template_pts"] = tres["pts"]
        out["targets"] = tres.get("targets") or []
        out["assign"] = tres.get("assign") or []
        out["min_score"] = tres.get("content_min", tres.get("min_score", 0.0))
        out["confidence"] = tres.get("confidence", 0.0)
        out["header_min"] = tres.get("header_min", 0.0)
        out["content_min"] = tres.get("content_min", 0.0)
        out["assign_margin"] = tres.get("assign_margin", 0.0)
        out["class_margin"] = tres.get("class_margin", 0.0)
        out["sources"].append("template")
        if verbose:
            log("TPL", f"template conf={out['confidence']:.2f} "
                       f"hmin={out['header_min']:.2f} cmin={out['content_min']:.2f} "
                       f"am={out['assign_margin']:.2f}")
            for a in out["assign"]:
                log("TPL", (f"  target {a['t']} -> blob {a['blob']} "
                            f"skor {a['score']:.2f} ({a['tsem']})"))
    else:
        log("TPL", f"template ragu: {tinfo}")

    # 2) library solver (opini kedua)
    lres, linfo = cl.match(path, debug=True, out_debug="c-solve-debug.png")
    if lres:
        out["lib_pts"] = lres["pts"]
        out["lib_assign"] = lres.get("assign") or []
        out["lib_min"] = lres.get("min_score", 0.0)
        out["blob_sem"] = lres.get("blob_sem") or []
        out["sources"].append("lib")
        if verbose:
            for a in out["lib_assign"]:
                log("LIB", (f"  target {a['t']} -> blob {a['blob']} "
                            f"skor {a['score']:.2f} ({a['tsem']}~{a['bsem']})"))
    else:
        log("LIB", f"library ragu: {linfo}")

    # 3) shape solver (opini ketiga)
    try:
        shape_pts, _ = cs.solve(path, debug=False)
    except Exception:
        shape_pts = None
    out["shape_pts"] = shape_pts
    if shape_pts:
        out["sources"].append("shape")

    # bandingkan jawaban berdasarkan indeks blob grid
    if out["candidates"]:
        tidx = pts_to_idx(out["template_pts"], out["candidates"]) if out["template_pts"] else None
        lidx = pts_to_idx(out["lib_pts"], out["candidates"]) if out["lib_pts"] else None
        sidx = pts_to_idx(shape_pts, out["candidates"]) if shape_pts else None
        out["template_idx"], out["lib_idx"], out["shape_idx"] = tidx, lidx, sidx
        if tidx and lidx:
            out["agree_lib"] = (tidx == lidx and len(set(tidx)) == 3)
        if tidx and sidx:
            out["agree_shape"] = (tidx == sidx and len(set(tidx)) == 3)
        if lidx and sidx:
            out["lib_shape"] = (lidx == sidx and len(set(lidx)) == 3)
        if verbose:
            log("IMG", f"idx tpl={tidx} lib={lidx} shape={sidx} "
                       f"| tpl=lib:{out['agree_lib']} tpl=shape:{out['agree_shape']} "
                       f"lib=shape:{out['lib_shape']}")

    # pilih jawaban utama
    if out["template_pts"]:
        out["pts"] = out["template_pts"]
    elif out["lib_pts"]:
        out["pts"] = out["lib_pts"]
        out["assign"] = out.get("lib_assign") or []
        out["min_score"] = out.get("lib_min", 0.0)
    elif shape_pts:
        out["pts"] = shape_pts
        out["assign"] = []
    if verbose:
        log("IMG", f"analisa {time.time()-t0:.1f}s sumber={out['sources']}")
    return out


def build_true_assign(pts, res):
    """Pairing target->blob dari pts yang BENAR-BENAR dikirim (bukan tebakan library)."""
    if not res or not res.get("candidates"):
        return res.get("assign") if res else []
    cands = res["candidates"]
    tlabels = [t.get("name") for t in (res.get("targets") or [])]
    bsem = res.get("blob_sem") or []
    out = []
    for i, p in enumerate(pts.split(";")):
        try:
            x, y = map(int, p.split(","))
        except Exception:
            continue
        c = min(cands, key=lambda c: (c["x"] - x) ** 2 + (c["y"] - y) ** 2)
        bi = c["blob"] - 1
        if i < len(tlabels) and tlabels[i] not in (None, "unknown"):
            sem, sc = tlabels[i], 1.0
        elif 0 <= bi < len(bsem):
            sem, sc = bsem[bi]
        else:
            sem, sc = "?", 0.0
        out.append({"t": i + 1, "blob": c["blob"], "tsem": sem,
                    "tsscore": round(float(sc), 3), "bsem": sem,
                    "score": round(float(sc), 3)})
    return out


def solve_adslab_browser(pageurl=None, timeout=180):
    """Solve AdsLab captcha via real Chromium di proot Ubuntu + Xvfb.
    Protokol JSON-lines: node kirim path gambar -> python OCR (tesseract) ->
    python kirim digit ke stdin -> node submit -> node kirim token.
    Return token string atau None."""
    here = os.getcwd()
    js = os.path.join(here, "browser_adslab.js")
    if not os.path.exists(js):
        log("ADSLAB", "browser_adslab.js tidak ada")
        return None
    inner = (f"cd {here} && "
             "unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy && "
             "export NO_PROXY='*' && "
             "xvfb-run -a --server-args='-screen 0 1366x768x24' "
             f"node browser_adslab.js '{pageurl or BASE + '/'}' {int(timeout * 1000)}")
    cmd = ["proot-distro", "login", "ubuntu", "--", "bash", "-c", inner]
    env = {k: v for k, v in os.environ.items()
           if k.lower() not in ("http_proxy", "https_proxy", "all_proxy")}
    t0 = time.time()
    p = None
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, bufsize=1, env=env)
    except Exception as e:
        log("ADSLAB", f"spawn gagal: {str(e)[:80]}")
        return None

    def _kill():
        try:
            p.kill()
        except Exception:
            pass

    try:
        # fase 1: baca path gambar
        line1 = p.stdout.readline().strip()
        if not line1:
            log("ADSLAB", "node tidak balas (kosong)")
            _kill()
            return None
        try:
            j1 = json.loads(line1)
        except Exception:
            log("ADSLAB", f"balasan tidak JSON: {line1[:80]}")
            _kill()
            return None
        if not j1.get("ok"):
            log("ADSLAB", f"node error: {str(j1.get('err'))[:100]}")
            _kill()
            return None
        img = j1.get("img")
        if not img or not os.path.exists(img):
            log("ADSLAB", f"gambar tidak ditemukan: {img}")
            _kill()
            return None
        log("ADSLAB", f"screenshot captcha: {img}")

        # fase 2: OCR via tesseract (Termux)
        try:
            import pytesseract
            from PIL import Image
            txt = pytesseract.image_to_string(Image.open(img)).strip()
        except Exception:
            # fallback: CLI tesseract
            import subprocess as sp
            try:
                txt = sp.run(["tesseract", img, "stdout", "--psm", "7"],
                             capture_output=True, text=True, timeout=60).stdout.strip()
            except Exception as e:
                log("ADSLAB", f"OCR gagal: {str(e)[:60]}")
                txt = ""
        digits = re.sub(r"\D", "", txt)
        log("ADSLAB", f"OCR digit: {digits!r} (raw {txt[:30]!r})")
        if not digits:
            _kill()
            return None

        # fase 3: kirim digit ke stdin node
        try:
            p.stdin.write(digits + "\n")
            p.stdin.flush()
        except Exception as e:
            log("ADSLAB", f"kirim stdin gagal: {str(e)[:60]}")
            _kill()
            return None

        # fase 4: baca token
        line2 = p.stdout.readline().strip()
        try:
            j2 = json.loads(line2)
        except Exception:
            log("ADSLAB", f"balasan akhir tidak JSON: {line2[:80]}")
            _kill()
            return None
        if j2.get("ok") and j2.get("token"):
            log("ADSLAB", f"token diterima len={len(j2['token'])} ({time.time()-t0:.0f}s)")
            return j2["token"]
        log("ADSLAB", f"node akhir: {str(j2)[:100]}")
        return None
    finally:
        try:
            if p and p.poll() is None:
                p.wait(timeout=3)
        except Exception:
            try:
                _kill()
            except Exception:
                pass
        try:
            if p:
                p.stdout.close(); p.stdin.close(); p.stderr.close()
        except Exception:
            pass


# ================================================================
# Human-in-the-loop: AdsLab Grid Captcha (PAUSE & NOTIFY)
# Bot TIDAK menebak/mengklik sendiri. Manusia yang menyelesaikan,
# bot menunggu token lalu melanjutkan alur seperti biasa.
# ================================================================
def notify_human(title, msg):
    """Notifikasi ke Termux (termux-notification) + Telegram (jika dikonfigurasi)."""
    log("HUMAN", msg)
    try:
        subprocess.run(["termux-notification", "-t", title, "-c", msg],
                       timeout=10, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass                                   # Termux API tidak tersedia
    if TG_BOT_TOKEN and TG_CHAT_ID:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                json={"chat_id": TG_CHAT_ID,
                      "text": f"🤖 *{title}*\n{msg}",
                      "parse_mode": "Markdown"},
                timeout=15)
        except Exception as e:
            log("TG", f"notif gagal: {str(e)[:60]}")


def detect_adslab(html):
    """Deteksi widget AdsLab di HTML respons.
    Return sitekey (str) jika ada, '' jika marker ada tapi sitekey tak ditemukan,
    atau None jika tidak ada widget sama sekali."""
    if not html:
        return None
    low = html.lower()
    if not any(m in low for m in ADSLAB_MARKERS):
        return None
    m = re.search(r'data-sitekey="([^"]+)"', html)
    if m:
        return m.group(1)
    m = re.search(r'sitekey=([A-Za-z0-9]+)', html)
    if m:
        return m.group(1)
    return ""


def _clipboard_get():
    try:
        out = subprocess.run(["termux-clipboard-get"], capture_output=True,
                             text=True, timeout=5)
        return (out.stdout or "").strip()
    except Exception:
        return ""


def wait_human_adslab(page_url, sitekey=None):
    """PAUSE sampai manusia menyelesaikan captcha AdsLab.
    Return token (str) atau None (batal / timeout / stdin tutup)."""
    iframe = (f"https://adslab.me/alcaptcha?sitekey={sitekey}"
              f"&domain=satoshifaucet.io&subid=widget_user") if sitekey else page_url
    notify_human(
        "Captcha AdsLab",
        "Grid captcha muncul! Selesaikan MANUAL di browser, lalu paste token "
        "[name=alcaptcha-response] ke terminal bot. "
        f"Widget: {iframe}")
    print("")
    print("╔════════════════════════════════════════════════════════════╗")
    print("║   CAPTCHA ADSLAB TERDETEKSI — BOT DIJEDA (human-in-loop)   ║")
    print("╠════════════════════════════════════════════════════════════╣")
    print("║ 1. Buka halaman ini di browser kamu:                       ║")
    print(f"║    {page_url[:54]:<54}║")
    print("║ 2. Selesaikan grid captcha secara MANUAL (klik gambar).    ║")
    print("║ 3. Copy nilai input hidden [name=alcaptcha-response],      ║")
    print("║    misal via console di halaman login:                     ║")
    print("║    document.querySelector('[name=alcaptcha-response]').value║")
    print("║ 4. Paste token di sini + Enter.                            ║")
    print("║    'y' = ambil dari clipboard, 'cancel' = lewati cycle.    ║")
    print("╚════════════════════════════════════════════════════════════╝")
    deadline = time.time() + HUMAN_TIMEOUT if HUMAN_TIMEOUT > 0 else None
    while True:
        if deadline and time.time() > deadline:
            log("HUMAN", f"timeout {HUMAN_TIMEOUT}s — lanjut tanpa token")
            return None
        try:
            line = input(">> token alcaptcha-response [y/cancel]: ").strip()
        except EOFError:
            log("HUMAN", "stdin tutup (non-interactive) — lewati cycle ini")
            return None
        if not line or line.lower() == "y":
            cb = _clipboard_get()
            if cb:
                log("HUMAN", f"token diambil dari clipboard ({len(cb)} char)")
                return cb
            print("   clipboard kosong — paste token manual atau 'cancel'")
            continue
        if line.lower() in ("cancel", "batal", "skip", "n"):
            log("HUMAN", "dibatalkan oleh manusia")
            return None
        if len(line) < 8:
            print("   token terlalu pendek — paste UUID alcaptcha-response")
            continue
        return line


def confidence_ok(res):
    if not res or not res.get("pts"):
        return False
    assign = res.get("assign") or []
    if len(assign) != 3:
        return False
    if len({a.get("tsem") for a in assign}) < 3:
        log("AUTO", "tolak: semantic target ganda (" +
            ", ".join(str(a.get("tsem")) for a in assign) + ")")
        return False
    if len({a.get("blob") for a in assign}) < 3:
        log("AUTO", "tolak: blob ganda")
        return False
    if res.get("template_pts"):
        hmin = float(res.get("header_min") or 0)
        cmin = float(res.get("content_min") or 0)
        conf = float(res.get("confidence") or 0)
        if hmin >= 0.90 and cmin >= 0.70 and conf >= 0.90:
            log("AUTO", f"template yakin (conf {conf:.2f})")
            return True
        if (hmin >= 0.85 and cmin >= 0.65 and conf >= 0.80
                and res.get("agree_lib") and res.get("agree_shape")):
            log("AUTO", f"template + 2 solver sepakat (conf {conf:.2f})")
            return True
        return False
    # fallback: library + shape sepakat (template tidak tersedia)
    if res.get("agree_shape") and float(res.get("lib_min") or 0) >= 0.60:
        log("AUTO", "library + shape sepakat")
        return True
    return False


# ------------------------------------------------------------------ bot
class Bot:
    def __init__(self):
        self.s = None
        self.fp = None
        self.wrong = 0
        self.cf_ok = False
        self.daily = "?"
        self.last_cf_try = 0.0
        self.pending_before = None
        self.last_res = None
        self.proxy = None
        self.proxy_idx = -1
        self.last_proxy_rotate = 0.0
        self.cur_archive = IMG
        self.bc = None
        self.bc_ready = None

    # ---- cf recovery via proot browser ----
    def recover_cf(self, force=False, proxy=None):
        now = time.time()
        if proxy is None:
            proxy = self.proxy
        if not force and (now - self.last_cf_try) < CF_BROWSER_COOLDOWN:
            left = int(CF_BROWSER_COOLDOWN - (now - self.last_cf_try))
            log("CFB", f"cooldown {left}s sebelum coba browser lagi")
            return False
        self.last_cf_try = now
        save_state(self.s, self.fp, proxy=proxy, proxy_idx=self.proxy_idx)   # browser pakai cookie sesi terbaru
        d = solve_cf_browser(proxy=proxy)
        if not d:
            set_state(cf="cf-gagal")
            return False
        self.proxy = proxy
        if self.s is not None:
            self.s.proxies = {"http": proxy, "https": proxy} if proxy else {}
            if d.get("ua"):
                self.s.headers["User-Agent"] = d["ua"]
            self.s.cookies.set("cf_clearance", d["cf_clearance"],
                               domain="satoshifaucet.io", path="/")
        save_state(self.s, self.fp, cf_ua=d.get("ua"), proxy=proxy, proxy_idx=self.proxy_idx)
        set_state(cf="cf-baru", last="cf-clearance")
        log("CFB", f"cf_clearance diterapkan (len {len(d['cf_clearance'])})"
                   f"{' via ' + mask_proxy(proxy) if proxy else ' (direct)'}")
        return True

    def use_next_proxy(self):
        """Pindah ke SID proxy baru yang acak (default), atau daur ulang
        PROXY_LIST bila SF_PROXY_RANDOM=0."""
        self.proxy_idx = (self.proxy_idx + 1) % len(PROXY_LIST)
        if PROXY_RANDOM:
            self.proxy = make_proxy()
            tag = "ROTASI-SID-ACAK"
        else:
            self.proxy = norm_proxy(PROXY_LIST[self.proxy_idx])
            tag = f"#{self.proxy_idx + 1}/{len(PROXY_LIST)}"
        self.last_proxy_rotate = time.time()
        log("PROXY", f"sesi {tag} {mask_proxy(self.proxy)}")
        if self.s is not None:
            self.s.proxies = {"http": self.proxy, "https": self.proxy}
            try:
                self.s.cookies.clear(domain="satoshifaucet.io", path="/",
                                     name="cf_clearance")
            except Exception:
                pass
        # fingerprint geolokasi mengikuti IP proxy (FR)
        detect_geo(proxy=self.proxy)
        save_state(self.s, self.fp, proxy=self.proxy, proxy_idx=self.proxy_idx)
        self.browser_claim_stop()
        return self.proxy

    # ---- browser claim daemon (proot + Xvfb, gate-as PAC) ----
    def browser_claim_start(self):
        """Spawn browser-claim daemon. Return dict ready atau None."""
        if self.bc:
            return self.bc_ready
        if not self.proxy:
            return None
        here = os.getcwd()
        inner = (f"cd {here} && unset DISPLAY HTTP_PROXY HTTPS_PROXY ALL_PROXY "
                 f"http_proxy https_proxy all_proxy && "
                 f"export NO_PROXY='*' && export CF_PAC=1 && "
                 f"export CF_PROXY='{self.proxy}' && export CF_WAIT=150 && "
                 f"xvfb-run -a --server-args='-screen 0 1366x768x24' "
                 f"node browser_claim.js {STATE}")
        cmd = ["proot-distro", "login", "ubuntu", "--", "bash", "-c", inner]
        try:
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True, bufsize=1)
        except Exception as e:
            log("BC", f"spawn gagal: {str(e)[:60]}")
            return None
        self.bc = p
        line = _readline_timeout(p.stdout, BC_SETUP_TIMEOUT)
        if not line:
            log("BC", "timeout menunggu setup browser")
            self.browser_claim_stop()
            return None
        try:
            d = json.loads(line)
        except Exception:
            log("BC", f"balasan tidak valid: {line[:80]}")
            self.browser_claim_stop()
            return None
        if not d.get("ready"):
            log("BC", f"setup gagal: {str(d)[:120]}")
            self.browser_claim_stop()
            return None
        self.bc_ready = d
        fld = (d.get("fields") or {})
        log("BC", f"browser siap: title={str(fld.get('title'))[:40]} "
                  f"html={d.get('htmlLen')} daily="
                  f"{re.search(DAILY_RE, fld.get('bodyText') or '').group(0)[-40:] if re.search(DAILY_RE, fld.get('bodyText') or '') else '?'}")
        return d

    def bc_cmd(self, obj, timeout=120):
        if not self.bc:
            return None
        try:
            self.bc.stdin.write(json.dumps(obj) + "\n")
            self.bc.stdin.flush()
        except Exception as e:
            log("BC", f"kirim perintah gagal: {str(e)[:60]}")
            return None
        line = _readline_timeout(self.bc.stdout, timeout)
        if not line:
            log("BC", "timeout menunggu jawaban")
            return None
        try:
            return json.loads(line)
        except Exception:
            log("BC", f"jawaban tidak valid: {line[:80]}")
            return None

    def browser_claim_stop(self):
        p = self.bc
        self.bc = None
        self.bc_ready = None
        if not p:
            return
        try:
            p.stdin.write('{"cmd":"quit"}\n')
            p.stdin.flush()
        except Exception:
            pass
        try:
            p.wait(timeout=6)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass

    # ---- CF via Tertuyul (full flow proxy) ----
    def try_cf_tertuyul(self):
        """Kirim Cloudflare managed challenge ke Tertuyul lewat proxy.
        Catatan: challenge /faucet tipe 'managed interactive' — token belum tentu
        tembus. Coba lebih dulu, fallback ke browser bila gagal."""
        if not self.proxy:
            log("CF", "tertuyul dilewati (challenge hanya via proxy)")
            return None
        try:
            tok = solve_cf_challenge(f"{BASE}/faucet/currency/{COIN}",
                                     html="", timeout=180,
                                     proxies=_proxy_dict(self.proxy))
            log("CF", f"tertuyul token len={len(tok)} "
                      f"(full flow via {mask_proxy(self.proxy)})")
            return tok
        except Exception as e:
            log("CF", f"tertuyul CF gagal: {str(e)[:80]}")
            return None

    def claim_via_browser(self):
        """Seluruh alur klaim lewat browser (proxy + PAC).
        Coba hingga 3 SID Prancis segar bila challenge CF bandel."""
        set_state(attempts=_ST["attempts"] + 1)
        # full flow via proxy: kirim challenge CF ke Tertuyul dulu (fallback browser)
        self.try_cf_tertuyul()
        d = None
        for _attempt in range(3):
            has_proxy = self.proxy is not None
            if has_proxy and _attempt > 0:
                # rotasi SID HANYA jika challenge CF bandel (attempt pertama coba pakai
                # SID & sesi yang sama — rotasi setiap klaim memicu WAF)
                self.browser_claim_stop()
                self.s = None
                self.use_next_proxy()
                if not self.login():
                    time.sleep(8)
                    continue
            d = self.browser_claim_start()
            if d is not None:
                break
        if d is None:
            time.sleep(15)
            return "retry"
        f = d.get("fields") or {}
        if not f.get("csrf"):
            url = f.get("url") or ""
            title = str(f.get("title") or "")
            bodyText = f.get("bodyText") or ""
            if "dashboard" in url.lower() or "Dashboard" in title or "Menu Dashboard" in bodyText:
                log("WAIT", f"akun diblok WAF untuk /faucet (dashboard stub). "
                            f"cooldown {BLOCK_COOLDOWN}s sebelum coba lagi (jangan rotasi/bakar saldo AdsLab)")
                self.browser_claim_stop()
                time.sleep(BLOCK_COOLDOWN)
                return "retry"
            if "dashboard" in url or re.search(r'form[^>]*auth/login', bodyText):
                log("SESI", "sesi proxy tidak valid untuk faucet -> rotasi SID baru & login ulang")
            else:
                log("BC", f"faucet tidak tampil (title={title[:50]})")
            self.browser_claim_stop()
            self.s = None
            self.use_next_proxy()
            if not self.login():
                time.sleep(10)
            return "retry"
        body = f.get("bodyText") or ""
        mb = re.search(r'alert\s+text-center\s+alert-(\w+)">(?:<[^>]+>)*\s*([^<]+)', body)
        if mb and "banned" in mb.group(2).lower():
            log("FATAL", f"AKUN BANNED — STOP ({mb.group(2).strip()})")
            sys.exit(2)
        daily = re.search(DAILY_RE, body)
        self.daily = f"{daily.group(1)}/{daily.group(2)}" if daily else "?"
        set_state(daily=self.daily)
        log("FAUCET", f"via browser (proxy): title={str(f.get('title'))[:40]} daily={self.daily}")
        # konfirmasi claim siklus sebelumnya
        if self.pending_before and self.daily != "?":
            try:
                b = int(self.pending_before.split("/")[0])
                a = int(self.daily.split("/")[0])
                if a > b:
                    set_state(claims_ok=_ST["claims_ok"] + 1,
                              last=f"claim-ok {self.pending_before}->{self.daily}",
                              last_claim_ts=time.time())
                    log("CLAIM", f"🎉 SUKSES (konfirmasi): daily "
                                 f"{self.pending_before} -> {self.daily}")
                else:
                    log("CLAIM", f"⚠️ daily tidak naik: "
                                 f"{self.pending_before} -> {self.daily}")
            except Exception:
                pass
            self.pending_before = None
        wait = re.search(r'Please wait\s*(\d+)\s*[:\s]\s*(\d+)', body)
        if wait:
            secs = int(wait.group(1)) * 60 + int(wait.group(2))
            log("TIMER", f"cooldown {secs}s (daily {self.daily})")
            time.sleep(min(secs + 2, 300))
            return "retry"

        max_refresh = int(os.getenv("MAX_REFRESH", "4"))
        ch = pts = mode = assign = None
        for attempt in range(max_refresh):
            r = self.bc_cmd({"cmd": "challenge"}, timeout=60)
            if not r or not r.get("ok"):
                log("CHAL", f"gambar error: {str(r)[:80] if r else 'timeout'}")
                self.browser_claim_stop()
                return "retry"
            ch = r["challenge"]
            img = ch.get("img", "")
            try:
                data = base64.b64decode(img.split(",", 1)[1]) if "," in img else base64.b64decode(img)
            except Exception as e:
                log("CHAL", f"gambar base64 gagal: {str(e)[:60]}")
                self.browser_claim_stop()
                return "retry"
            open(IMG, "wb").write(data)
            os.makedirs("archive", exist_ok=True)
            os.makedirs("archive_raw", exist_ok=True)
            name = time.strftime("%Y%m%d-%H%M%S")
            self.cur_archive = f"archive/{name}.png"
            open(self.cur_archive, "wb").write(data)
            open(f"archive_raw/{name}.b64", "w").write(img)
            for p in (PTS, READY):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
            log("CHAL", f"gambar baru (daily {self.daily}, "
                         f"coba {attempt + 1}/{max_refresh})")
            pts, mode, assign = self.pick_points()
            if pts:
                break
            if attempt + 1 < max_refresh:
                time.sleep(2)
        if not pts:
            log("CHAL", f"tidak ada gambar yakin setelah {max_refresh} "
                          f"percobaan -> stop browser, retry")
            self.browser_claim_stop()
            return "retry"
        log("CHAL", f"pts: {pts}")

        r = self.bc_cmd({"cmd": "check", "csrf": f["csrf"], "token": ch["token"],
                         "pts": pts}, timeout=90)
        j = (r or {}).get("json") or {}
        if not (j.get("ok") and j.get("pass")):
            self.wrong += 1
            err = str(j.get("error") or j.get("why") or (r or {}))
            log("CHECK", f"SALAH ({self.wrong}x): {err[:100]}")
            self._index(pts, mode, assign, "wrong")
            if "wrong" in err.lower() or j.get("wait"):
                wait_s = int(j.get("wait") or WRONG_COOLDOWN)
                log("CHECK", f"server cooldown {wait_s}s")
                time.sleep(wait_s + 2)
                self.wrong = 0
            elif self.wrong >= 2:
                log("CHECK", f"2x salah -> cooldown {WRONG_COOLDOWN}s")
                time.sleep(WRONG_COOLDOWN)
                self.wrong = 0
            return "retry"

        self.wrong = 0
        log("CHECK", "PASS ✅")
        true_assign = build_true_assign(pts, self.last_res)
        self._index(pts, mode, true_assign, "pass")
        try:
            if true_assign:
                import cosmos_templates as ct
                labels = [t.get("name") for t in
                          ((self.last_res or {}).get("targets") or [])]
                if len(labels) != 3:
                    labels = None
                n = ct.harvest_from_pass(IMG, pts, header_labels=labels,
                                         content_labels=labels)
                log("TPL", f"template +{n} (header+konten)")
        except Exception as e:
            log("TPL", f"harvest gagal: {str(e)[:50]}")

        before = self.daily
        self.pending_before = before if before != "?" else None
        try:
            gap = CLAIM_GAP - (time.time() - float(_ST.get("last_claim_ts") or 0))
        except Exception:
            gap = 0
        if gap > 0:
            log("CLAIM", f"tunggu {int(gap)}s (jeda minimal {CLAIM_GAP}s)")
            time.sleep(gap)
        r = self.bc_cmd({"cmd": "verify", "csrf": j.get("csrf") or f["csrf"],
                         "token": f["token"], "nonce": f["nonce"],
                         "uf": self.fp, "utt": TZ, "ls": LANGS,
                         "pass": j["pass"], "wallet": EMAIL}, timeout=90)
        log("CLAIM", f"  verify http={(r or {}).get('http')} "
                     f"text={(r or {}).get('text', '')[:1200]}")
        # baca ulang faucet (polling, counter bisa telat update beberapa detik)
        after = "?"
        for poll in range(10):
            r2 = self.bc_cmd({"cmd": "page"}, timeout=120)
            daily_pair = (r2 or {}).get("daily") or []
            cand = f"{daily_pair[0]}/{daily_pair[1]}" if len(daily_pair) == 2 else "?"
            if cand != "?":
                after = cand
            log("CLAIM", f"  polling[{poll + 1}]: daily={after}")
            if (after != "?" and before != "?" and after != before) or \
               (after != "?" and before == "?"):
                break
            time.sleep(5)
        if before != "?" and after != "?" and before != after:
            self.pending_before = None
            set_state(claims_ok=_ST["claims_ok"] + 1,
                      last=f"claim-ok {before}->{after}",
                      last_claim_ts=time.time())
            log("CLAIM", f"🎉 SUKSES! daily {before} -> {after}")
        elif after != "?" and before == "?":
            set_state(claims_ok=_ST["claims_ok"] + 1, last="claim-ok",
                      last_claim_ts=time.time())
            log("CLAIM", f"🎉 SUKSES! daily sekarang {after}")
            self.pending_before = None
        else:
            log("CLAIM", f"status tak dikenal: daily {before} -> {after}")
            set_state(last="claim-unknown")
        time.sleep(45)
        return "retry"

    # ---- session ----
    def session_valid(self):
        if self.s is None:
            return False
        if self.proxy:
            self.s.proxies = {"http": self.proxy, "https": self.proxy}
        try:
            r = self.s.get(f"{BASE}/dashboard", timeout=45)
        except Exception:
            return False
        if r.status_code != 200:
            return False
        if re.search(r'form[^>]*auth/login', r.text):
            return False
        # dashboard bisa 200 walau sesi tidak valid untuk faucet
        try:
            rf = self.s.get(f"{BASE}/faucet/currency/{COIN}", timeout=45,
                            allow_redirects=False)
        except Exception:
            return False
        if rf.status_code in (301, 302, 303, 307, 308):
            return False
        low = rf.text[:3000].lower()
        if rf.status_code == 403 or "just a moment" in low:
            return True          # sesi mungkin valid; CF akan di-solve nanti
        return rf.status_code == 200 and "csrf_token_name" in rf.text

    # ---- login ----
    def login(self):
        cf_fails = 0
        for attempt in range(1, 13):
            s = new_scraper(proxy=self.proxy)
            if not self.proxy:
                apply_cf_override(s)
            try:
                r = s.get(f"{BASE}/", timeout=45)
            except Exception as e:
                log("NET", f"homepage err ({attempt}/12): {str(e)[:70]}")
                time.sleep(WAIT)
                continue
            low = r.text[:3000].lower()
            if r.status_code != 200 or "csrf_token_name" not in r.text:
                cf_hit = (r.status_code == 403 or "just a moment" in low)
                log("CF", f"homepage HTTP {r.status_code} (coba {attempt}/12)"
                          f"{' [CF]' if cf_hit else ''}")
                if cf_hit:
                    cf_fails += 1
                    if cf_fails >= 1:
                        # langsung pindah/rotasi proxy saat CF memblokir IP
                        self.use_next_proxy()
                        cf_fails = 0
                        continue
                time.sleep(WAIT)
                continue

            fp = fp_hex()
            s.cookies.set("uf", fp, domain="satoshifaucet.io", path="/")
            s.cookies.set("utt", TZ, domain="satoshifaucet.io", path="/")
            s.cookies.set("ls", LANGS, domain="satoshifaucet.io", path="/")
            s.headers["Accept-Language"] = ",".join(
                p if i == 0 else f"{p};q={max(0.9 - i * 0.1, 0.1):.1f}"
                for i, p in enumerate(LANGS.split(",")))
            csrf = re.search(r'name="csrf_token_name"[^>]*value="([^"]+)"',
                             r.text).group(1)

            # Situs bisa memakai AdsLab atau SF Cosmos. Deteksi dari option
            # <select id="selectCaptcha">, jangan asumsikan satu jenis saja.
            msel = re.search(r'id="selectCaptcha"[^>]*>.*?<option value="([^"]+)"',
                             r.text, re.S)
            cap_type = msel.group(1) if msel else "sf_cosmos"
            log("CAP", f"jenis captcha login: {cap_type}")

            if cap_type == "adslab":
                sk = detect_adslab(r.text)
                if sk is None:
                    sk = ""
                if HUMAN_CAPTCHA:
                    # Human-in-the-loop: PAUSE + notifikasi, manusia klik gridnya.
                    tok = wait_human_adslab(f"{BASE}/", sk or ADS_SITEKEY)
                    if not tok:
                        log("CAP", "adslab dibatalkan/timeout — lewati cycle ini")
                        time.sleep(WAIT)
                        continue
                    # csrf bisa kedaluwarsa saat pause panjang — ambil ulang
                    try:
                        rf = s.get(f"{BASE}/", timeout=45)
                        if rf.status_code == 200:
                            m2 = re.search(r'name="csrf_token_name"[^>]*value="([^"]+)"',
                                           rf.text)
                            if m2:
                                csrf = m2.group(1)
                                log("CAP", "csrf diperbarui setelah pause")
                    except Exception:
                        pass
                else:
                    # Prioritas: solve AdsLab di Chromium nyata (proot+Xvfb),
                    # tanpa bergantung pada API solver eksternal.
                    tok = None
                    try:
                        tok = solve_adslab_browser(f"{BASE}/", timeout=180)
                    except Exception as e:
                        log("CAP", f"adslab browser error: {str(e)[:60]}")
                    if not tok:
                        try:
                            tok = solve_adslab(ADS_SITEKEY, f"{BASE}/", timeout=180,
                                               proxies=_proxy_dict(self.proxy))
                        except Exception as e:
                            log("CAP", f"adslab gagal: {str(e)[:60]}")
                            continue
                    if not tok:
                        continue
                login_captcha = {"captcha": "adslab",
                                 "alcaptcha-response": tok}
            else:
                # SF Cosmos: fetch challenge -> analyze -> check -> sfz_pass
                sf_pass, csrf = self.solve_cosmos_challenge(
                    s, "login_captcha", "c-cosmos-login.png", csrf)
                if not sf_pass:
                    log("CAP", "login_captcha gagal diselesaikan")
                    continue
                login_captcha = {"captcha": cap_type, "sfz_pass": sf_pass,
                                 "sfz_hp": ""}

            r2 = s.post(f"{BASE}/auth/login", data={
                "wallet": EMAIL, "csrf_token_name": csrf,
                "ls": LANGS, "uf": fp, "utt": TZ,
                **login_captcha,
            }, allow_redirects=False, timeout=45)
            loc = r2.headers.get("Location")
            body = r2.text
            if loc:
                body = s.get(loc if loc.startswith("http") else BASE + loc,
                             timeout=45).text
            m = re.search(r'alert\s+text-center\s+alert-(\w+)">(?:<[^>]+>)*\s*([^<]+)', body)
            if m:
                msg = m.group(2).strip()
                log("LOGIN", f"pesan: {msg}")
                if "banned" in msg.lower():
                    log("FATAL", "AKUN BANNED — STOP")
                    sys.exit(2)
                if "vpn" in msg.lower() or "proxy" in msg.lower():
                    log("LOGIN", "IP terdeteksi VPN/proxy -> pindah sesi proxy")
                    self.use_next_proxy()
                    continue
            if re.search(r'form[^>]*auth/login', body):
                log("LOGIN", "gagal (form masih tampil), ulang")
                continue

            self.s, self.fp = s, fp
            save_state(s, fp, proxy=self.proxy, proxy_idx=self.proxy_idx)
            set_state(cf="login-ok", last="login")
            log("LOGIN", "OK ✅")
            return True
        return False

    # ---- cf / faucet ----
    def faucet(self):
        if self.s is None:
            if not self.login():
                return None
        try:
            r = self.s.get(f"{BASE}/faucet/currency/{COIN}", timeout=45)
        except Exception as e:
            log("NET", f"faucet err: {str(e)[:70]}")
            return None
        # Grid captcha AdsLab bisa muncul di halaman klaim -> PAUSE & notify
        _sk = detect_adslab(r.text)
        if _sk is not None:
            tok = wait_human_adslab(f"{BASE}/faucet/currency/{COIN}",
                                    _sk or ADS_SITEKEY)
            if not tok:
                return None
            log("HUMAN", "token manual diterima — ambil ulang halaman klaim")
            try:
                r2 = self.s.get(f"{BASE}/faucet/currency/{COIN}", timeout=45)
                if detect_adslab(r2.text) is None:
                    r = r2
                    log("HUMAN", "widget hilang setelah solve manual ✅")
                else:
                    log("HUMAN", "widget masih tampil — coba lagi di cycle berikutnya")
                    return None
            except Exception as e:
                log("NET", f"re-get faucet err: {str(e)[:70]}")
                return None
        low = r.text[:3000].lower()
        if r.status_code == 403 or "just a moment" in low:
            self.cf_ok = False
            set_state(cf="blocked")
            solved = False
            # kirim challenge ke Tertuyul (full flow via proxy) — coba lebih dulu
            self.try_cf_tertuyul()
            # 1) coba IP langsung dulu (Xvfb), hanya jika belum pakai proxy
            if self.proxy is None:
                if self.recover_cf(force=True):
                    try:
                        r = self.s.get(f"{BASE}/faucet/currency/{COIN}", timeout=45)
                    except Exception as e:
                        log("NET", f"faucet retry err: {str(e)[:70]}")
                        return None
                    low = r.text[:3000].lower()
                    if r.status_code != 403 and "just a moment" not in low:
                        solved = True
                    else:
                        log("CFB", "clearance direct masih 403 -> fallback proxy")
                else:
                    log("CFB", "solve direct gagal -> fallback proxy")
            # 2) proxy fallback: clearance hasil browser TIDAK diterima cloudscraper,
            #    jadi cukup rotasi ke SID Prancis baru -> claim_cycle akan memakai
            #    claim_via_browser (PAC + challenge DIRECT) yang sudah terbukti jalan.
            if not solved:
                self.use_next_proxy()
                log("PROXY", "direct ditolak -> rotasi SID baru, klaim via browser")
            return r
            log("CFB", f"/faucet tembus ✅ (HTTP {r.status_code})")
            self.cf_ok = True
            set_state(cf="ok")
        self.cf_ok = True
        set_state(cf="ok")
        if re.search(r'form[^>]*auth/login', r.text) or (
                "csrf_token_name" not in r.text and "/dashboard" in (r.url or "")):
            log("SESI", "sesi tidak valid untuk faucet -> login ulang")
            self.s = None
            return None
        return r

    # ---- captcha ----
    def get_challenge(self, kind=None, img_path=IMG, client=None):
        kind = kind or f"faucet_{COIN}"
        s = client or self.s
        s.headers["X-Requested-With"] = "XMLHttpRequest"
        rc = s.get(f"{BASE}/cosmos/challenge/{kind}"
                   f"?_={int(time.time()*1000)}", timeout=45)
        if rc.status_code != 200:
            log("CHAL", f"HTTP {rc.status_code}")
            return None
        try:
            ch = rc.json()
        except Exception:
            log("CHAL", f"bukan JSON: {rc.text[:80]}")
            return None
        if ch.get("error") or not ch.get("img"):
            log("CHAL", f"error: {str(ch)[:90]}")
            if ch.get("wait"):
                time.sleep(ch["wait"])
            return None
        raw = ch["img"]
        data = base64.b64decode(raw.split(",", 1)[1])
        open(img_path, "wb").write(data)
        os.makedirs("archive", exist_ok=True)
        os.makedirs("archive_raw", exist_ok=True)
        name = time.strftime("%Y%m%d-%H%M%S")
        self.cur_archive = f"archive/{name}.png"
        open(self.cur_archive, "wb").write(data)
        open(f"archive_raw/{name}.b64", "w").write(raw)
        for p in (PTS, READY):
            if os.path.exists(p):
                os.remove(p)
        return ch

    def pick_points(self, img_path=IMG):
        """Return (pts, mode, assign) atau (None, 'refresh', assign)."""
        res = analyze_image(img_path)
        self.last_res = res
        if confidence_ok(res):
            log("AUTO", f"solver yakin: {res['pts']} "
                        f"(conf {res.get('confidence', 0):.2f})")
            return res["pts"], "auto", res["assign"]

        # manual/AI override kalau file sudah tersedia (tanpa menunggu lama)
        if os.path.exists(PTS):
            txt = open(PTS).read().strip()
            try:
                os.remove(PTS)
            except Exception:
                pass
            if re.fullmatch(r"\d+,\d+(;\d+,\d+){2}", txt):
                log("MAN", f"koordinat manual/AI: {txt}")
                set_state(pending_pts=False)
                return txt, "manual", (res or {}).get("assign") or []

        if res:
            log("AUTO", f"solver ragu (conf {res.get('confidence', 0):.2f}, "
                        f"hmin {res.get('header_min', 0):.2f}, "
                        f"cmin {res.get('content_min', 0):.2f}) -> refresh gambar")
        set_state(pending_pts=False, last="refresh-gambar")
        return None, "refresh", (res or {}).get("assign") or []

    def solve_cosmos_challenge(self, client, kind, img_path, csrf):
        """Selesaikan SF Cosmos (mis. login_captcha) secara HTTP.

        Mengikuti kontrak endpoint yang dipakai JS halaman:
        challenge mengembalikan {token, img}; check mengirim csrf, token, hp, pts.
        Return (pass_token, csrf) atau (None, csrf)."""
        max_refresh = int(os.getenv("MAX_REFRESH", "4"))
        for attempt in range(max_refresh):
            ch = self.get_challenge(kind, img_path, client)
            if not ch:
                return None, csrf
            log("CHAL", f"{kind} gambar baru (coba {attempt + 1}/{max_refresh})")
            # SERVER menolak jawaban yang terlalu cepat (MIN_MS ~3400ms)
            time.sleep(3.5)
            pts, mode, assign = self.pick_points(img_path)
            if not pts:
                if attempt + 1 < max_refresh:
                    time.sleep(2)
                continue
            log("CHAL", f"{kind} pts: {pts}")
            check = {"csrf_token_name": csrf, "token": ch["token"],
                     "hp": "", "pts": pts}
            try:
                rck = client.post(f"{BASE}/cosmos/check/{kind}",
                                  data=check, timeout=60)
            except Exception as e:
                log("CHECK", f"{kind} submit err: {str(e)[:70]}")
                return None, csrf
            try:
                j = rck.json()
            except Exception:
                log("CHECK", f"{kind} check HTTP {rck.status_code}: "
                              f"{rck.text[:120]}")
                if "just a moment" in (rck.text[:500].lower()):
                    log("CHECK", f"{kind} kena Cloudflare")
                return None, csrf
            if j.get("ok") and j.get("pass"):
                log("CHECK", f"{kind} PASS ✅")
                return j["pass"], j.get("csrf") or csrf
            err = str(j.get("error") or j.get("why") or j)
            log("CHECK", f"{kind} SALAH: {err[:120]}")
            wait = j.get("wait")
            if j.get("expired"):
                continue
            if j.get("locked"):
                time.sleep(int(wait or 60))
            elif wait:
                time.sleep(int(wait))
            else:
                time.sleep(5)
        return None, csrf

    def claim_cycle(self):
        # jika memakai proxy (IP user VPN-terdeteksi), seluruh alur via browser
        if self.proxy:
            return self.claim_via_browser()
        set_state(attempts=_ST["attempts"] + 1)
        rf = self.faucet()
        if rf is None:
            time.sleep(15)
            return "retry"
        if rf.status_code == 403 or "just a moment" in rf.text[:3000].lower():
            return "cf"
        if rf.status_code == 429:
            log("FAUCET", "429 rate limit -> istirahat 45s")
            time.sleep(45)
            return "retry"
        if rf.status_code != 200:
            log("FAUCET", f"HTTP {rf.status_code}")
            time.sleep(15)
            return "retry"

        body = rf.text
        mb = re.search(r'alert\s+text-center\s+alert-(\w+)">(?:<[^>]+>)*\s*([^<]+)', body)
        if mb and "banned" in mb.group(2).lower():
            log("FATAL", f"AKUN BANNED — STOP ({mb.group(2).strip()})")
            sys.exit(2)

        daily = re.search(DAILY_RE, body)
        self.daily = f"{daily.group(1)}/{daily.group(2)}" if daily else "?"
        set_state(daily=self.daily)
        # konfirmasi claim siklus sebelumnya (counter telat update)
        if self.pending_before and self.daily != "?":
            try:
                b = int(self.pending_before.split("/")[0])
                a = int(self.daily.split("/")[0])
                if a > b:
                    set_state(claims_ok=_ST["claims_ok"] + 1,
                              last=f"claim-ok {self.pending_before}->{self.daily}",
                              last_claim_ts=time.time())
                    log("CLAIM", f"🎉 SUKSES (konfirmasi): daily "
                                 f"{self.pending_before} -> {self.daily}")
                else:
                    log("CLAIM", f"⚠️ daily tidak naik: "
                                 f"{self.pending_before} -> {self.daily}")
            except Exception:
                pass
            self.pending_before = None

        wait = re.search(r'Please wait\s*(\d+)\s*[:\s]\s*(\d+)', body)
        if wait:
            secs = int(wait.group(1)) * 60 + int(wait.group(2))
            log("TIMER", f"cooldown {secs}s (daily {self.daily})")
            time.sleep(secs + 2)
            return "retry"

        if "csrf_token_name" not in body:
            log("FAUCET", f"200 tanpa form (daily {self.daily}) — "
                          f"pesan: {mb.group(2).strip() if mb else '?'}")
            time.sleep(15)
            return "retry"

        csrf = re.search(r'name="csrf_token_name"[^>]*value="([^"]+)"', body)
        ftoken = re.search(r'name="token"\s+value="([^"]+)"', body)
        nonce = re.search(r'name="claim_nonce"\s+value="([^"]+)"', body)
        if not (csrf and ftoken and nonce):
            log("FAUCET", "form tidak lengkap")
            time.sleep(15)
            return "retry"

        max_refresh = int(os.getenv("MAX_REFRESH", "4"))
        ch = None
        pts = mode = assign = None
        for attempt in range(max_refresh):
            ch = self.get_challenge()
            if not ch:
                return "retry"
            log("CHAL", f"gambar baru (daily {self.daily}, "
                        f"coba {attempt + 1}/{max_refresh})")
            pts, mode, assign = self.pick_points()
            if pts:
                break
            if attempt + 1 < max_refresh:
                time.sleep(2)
        if not pts:
            log("CHAL", f"tidak ada gambar yakin setelah {max_refresh} "
                        f"percobaan -> retry")
            return "retry"
        log("CHAL", f"pts: {pts}")

        check_data = {"csrf_token_name": csrf.group(1), "token": ch["token"],
                      "hp": "", "pts": pts}
        rck = self.s.post(f"{BASE}/cosmos/check/faucet_{COIN}",
                          data=check_data, timeout=60)
        try:
            j = rck.json()
        except Exception:
            low = rck.text[:3000].lower()
            if "just a moment" in low or rck.status_code == 403:
                log("CHECK", "kena CF -> solve ulang & retry submit")
                j = None
                if self.recover_cf(force=True):
                    try:
                        rck = self.s.post(f"{BASE}/cosmos/check/faucet_{COIN}",
                                          data=check_data, timeout=60)
                        j = rck.json()
                    except Exception:
                        j = None
            else:
                j = None
            if j is None:
                log("CHECK", f"submit gagal: {rck.text[:80]}")
                time.sleep(10)
                return "retry"

        if not (j.get("ok") and j.get("pass")):
            self.wrong += 1
            err = str(j.get("error") or j.get("why") or j)
            log("CHECK", f"SALAH ({self.wrong}x): {err[:100]} -> capture ulang")
            self._index(pts, mode, assign, "wrong")
            if "wrong" in err.lower() or j.get("wait"):
                wait = int(j.get("wait") or WRONG_COOLDOWN)
                log("CHECK", f"server cooldown {wait}s")
                time.sleep(wait + 2)
                self.wrong = 0
            elif self.wrong >= 2:
                log("CHECK", f"2x salah -> cooldown {WRONG_COOLDOWN}s")
                time.sleep(WRONG_COOLDOWN)
                self.wrong = 0
            return "retry"

        self.wrong = 0
        log("CHECK", "PASS ✅")
        # pairing sebenarnya = dari pts yang dikirim, bukan tebakan library
        true_assign = build_true_assign(pts, self.last_res)
        self._index(pts, mode, true_assign, "pass")
        try:
            if true_assign:
                import cosmos_templates as ct
                labels = [t.get("name") for t in
                          ((self.last_res or {}).get("targets") or [])]
                if len(labels) != 3:
                    labels = None
                n = ct.harvest_from_pass(IMG, pts, header_labels=labels,
                                         content_labels=labels)
                log("TPL", f"template +{n} (header+konten)")
        except Exception as e:
            log("TPL", f"harvest gagal: {str(e)[:50]}")

        before = self.daily
        self.pending_before = before if before != "?" else None
        # jaga jeda antar claim (server menolak jika terlalu cepat)
        try:
            gap = CLAIM_GAP - (time.time() - float(_ST.get("last_claim_ts") or 0))
        except Exception:
            gap = 0
        if gap > 0:
            log("CLAIM", f"tunggu {int(gap)}s (jeda minimal {CLAIM_GAP}s)")
            time.sleep(gap)
        log("CLAIM", f"kirim verify: nonce={nonce.group(1)[:10]} "
                     f"token={ftoken.group(1)[:10]} csrf={str(j.get('csrf') or csrf.group(1))[:10]}")
        rcl = self.s.post(f"{BASE}/faucet/verify/{COIN}", data={
            "csrf_token_name": j.get("csrf") or csrf.group(1),
            "token": ftoken.group(1), "claim_nonce": nonce.group(1),
            "uf": self.fp, "utt": TZ, "ls": LANGS,
            "captcha": "sf_cosmos", "sfz_pass": j["pass"], "sfz_hp": "",
            "wallet": EMAIL}, allow_redirects=False, timeout=60)
        loc = rcl.headers.get("Location")
        log("CLAIM", f"  verify HTTP {rcl.status_code} loc={loc} "
                     f"len={len(rcl.text or '')}")
        page = ""
        if loc:
            try:
                page = self.s.get(loc if loc.startswith("http") else BASE + loc,
                                  timeout=45).text
            except Exception:
                page = ""
        # konfirmasi: baca ulang halaman faucet (retry, counter butuh waktu)
        after = "?"
        for _ in range(6):
            if not page:
                try:
                    page = self.s.get(f"{BASE}/faucet/currency/{COIN}",
                                      timeout=45).text
                except Exception:
                    page = ""
            daily2 = re.search(DAILY_RE, page)
            if daily2:
                after = f"{daily2.group(1)}/{daily2.group(2)}"
                if before == "?" or after != before:
                    break
            time.sleep(2)
            page = ""

        mb2 = re.search(r'alert\s+text-center\s+alert-(\w+)">(?:<[^>]+>)*\s*([^<]+)', page)
        if mb2:
            log("CLAIM", f"  alert[{mb2.group(1)}]: {mb2.group(2).strip()[:140]}")
        w = re.search(r'Please wait\s*(\d+)\s*[:\s]\s*(\d+)', page)

        if mb2 and "banned" in mb2.group(2).lower():
            log("FATAL", f"AKUN BANNED — STOP ({mb2.group(2).strip()})")
            sys.exit(2)

        if before != "?" and after != "?" and before != after:
            self.pending_before = None      # sudah terkonfirmasi di sini
            set_state(claims_ok=_ST["claims_ok"] + 1,
                      last=f"claim-ok {before}->{after}",
                      last_claim_ts=time.time())
            log("CLAIM", f"🎉 SUKSES! daily {before} -> {after}"
                         f"{f' | timer {w.group(1)}:{w.group(2)}' if w else ''}")
        elif mb2 and "danger" in mb2.group(1):
            self.pending_before = None
            log("CLAIM", f"⚠️ {mb2.group(2).strip()}")
            set_state(last="claim-gagal")
        elif w:
            self.pending_before = None
            set_state(claims_ok=_ST["claims_ok"] + 1, last="claim-ok",
                      last_claim_ts=time.time())
            log("CLAIM", f"🎉 SUKSES! timer {w.group(1)}:{w.group(2)}")
        else:
            log("CLAIM", f"status tak dikenal (HTTP {rcl.status_code}) "
                         f"daily {before} -> {after}")
            try:
                snippet = re.sub(r"\s+", " ", rcl.text or "")[:220]
            except Exception:
                snippet = "?"
            log("CLAIM", f"  body: {snippet}")
            set_state(last="claim-unknown")

        if w:
            secs = int(w.group(1)) * 60 + int(w.group(2))
            time.sleep(min(secs + 2, 120))
        else:
            time.sleep(45)   # jaga jarak antar claim (server menolak jika terlalu cepat)
        return "retry"

    def _index(self, pts, mode, assign, result):
        try:
            with open("archive_index.jsonl", "a") as f:
                f.write(json.dumps({
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "img": self.cur_archive or IMG,
                    "pts": pts, "mode": mode, "assign": assign or [],
                    "result": result}, ensure_ascii=False) + "\n")
        except Exception:
            pass


# ------------------------------------------------------------------ main
def main():
    # singleton: hanya satu instance pada satu saat (hindari dua bot saling rebutan
    # Chromium/profile yang sama)
    try:
        import fcntl
        lock = open(STATE + ".lock", "w")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except Exception:
        log("BOOT", "instance lain sedang berjalan — keluar")
        return 1

    if "--look" in sys.argv:
        p = sys.argv[sys.argv.index("--look") + 1] if len(sys.argv) > sys.argv.index("--look") + 1 else IMG
        r = analyze_image(p)
        if r:
            print(json.dumps({k: r[k] for k in ("pts", "min_score", "candidates")}, indent=1))
        return 0

    once = "--once" in sys.argv
    # pulihkan waktu claim terakhir (jeda antar claim tetap dijaga setelah restart)
    try:
        prev = json.load(open(STATUS))
        if prev.get("last_claim_ts"):
            _ST["last_claim_ts"] = float(prev["last_claim_ts"])
    except Exception:
        pass
    st = load_state()
    # Kalau ada sesi proxy tersimpan, langsung lanjutkan lewat jalur proxy+browser
    # (French residential: lolos deteksi VPN situs). Kalau tidak ada, mulai direct.
    proxy0 = norm_proxy(os.getenv("SF_PROXY", "")) or None
    if "--proxy" in sys.argv:
        proxy0 = make_proxy() if PROXY_RANDOM else norm_proxy(PROXY_LIST[0])
    elif st.get("proxy"):
        proxy0 = st["proxy"]
    detect_geo(proxy=proxy0)
    log("BOOT", f"NONSTOP | email={EMAIL} coin={COIN} "
                f"monitor={MONITOR_SECS}s max={MAX_MINUTES or '∞'}m")
    log("BOOT", f"fingerprint tz={TZ} langs={LANGS}")
    log("BOOT", f"CF: proot Ubuntu + Xvfb (Xvfb) | proxy fallback "
                f"{mask_proxy(proxy0) if proxy0 else 'belum aktif'}")

    bot = Bot()
    bot.proxy = proxy0
    try:
        bot.proxy_idx = int(st.get("proxy_idx", -1))
    except Exception:
        bot.proxy_idx = -1
    if st.get("cookies"):
        bot.s = rebuild_from_state(st, proxy=proxy0)
        bot.fp = st.get("fp")
        if bot.session_valid():
            log("BOOT", "state lama valid — tidak perlu login ulang ✅")
            set_state(cf="login-ok", last="sesi-lama")
        else:
            log("BOOT", "state lama mati -> login ulang")
            bot.s = None
    if bot.s is None and not bot.login():
        log("FATAL", "login awal gagal")
        return 1

    stop = threading.Event()
    threading.Thread(target=monitor_loop, args=(stop,), daemon=True).start()
    t0 = time.time()
    cf_notified = False
    try:
        while True:
            if MAX_MINUTES and (time.time() - t0) > MAX_MINUTES * 60:
                log("BOOT", f"durasi {MAX_MINUTES}m tercapai — selesai")
                break
            try:
                res = bot.claim_cycle()
                if res == "cf" and not cf_notified:
                    cf_notified = True
                    log("CF", "⛔ /faucet masih diblok Cloudflare.")
                    log("CF", f"   Auto-solve: Chromium proot Ubuntu + Xvfb "
                              f"({CF_JS}), cooldown {CF_BROWSER_COOLDOWN}s.")
                    log("CF", f"   Alternatif: taruh cf_clearance di {CF_FILE}.")
                    log("CF", f"   Cek ulang tiap {CF_RETRY}s.")
                elif res != "cf":
                    cf_notified = False
            except SystemExit:
                raise
            except Exception as e:
                log("ERR", f"{type(e).__name__}: {str(e)[:100]}")
                tb = traceback.format_exc().splitlines()
                if tb:
                    log("ERR", tb[-2][:140])
                time.sleep(20)
            if once:
                break
            if not bot.cf_ok:
                time.sleep(CF_RETRY)
    except KeyboardInterrupt:
        log("BOOT", "dihentikan (Ctrl-C)")
    finally:
        stop.set()
        try:
            bot.browser_claim_stop()
        except Exception:
            pass
        dump_status()
    return 0


if __name__ == "__main__":
    sys.exit(main())