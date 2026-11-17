import sys, json, time, subprocess
from curl_cffi import requests

def check_cf(html, status):
    if status in (403, 503): return True
    if html and any(m in html.lower() for m in ["just a moment", "cf-challenge", "attention required"]): return True
    return False

def call_hard_solver(url, proxy, ua):
    payload = json.dumps({"url": url, "proxy": proxy, "ua": ua})
    try:
        p = subprocess.Popen(["node", "cf_hard_solver.js"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, err = p.communicate(input=payload, timeout=90)
        return json.loads(out.strip())
    except Exception as e:
        return {"ok": False, "error": f"Hard solver error: {str(e)}"}

def solve_waf(url, proxy=None, cookies=None, ua=None):
    session = requests.Session(impersonate="safari15_5")
    if proxy: session.proxies = {"http": proxy, "https": proxy}
    if cookies: session.cookies.update(cookies)
    if ua: session.headers["User-Agent"] = ua

    try:
        r = session.get(url, timeout=30, allow_redirects=True)
        cf_clearance = session.cookies.get("cf_clearance")
        
        if not check_cf(r.text, r.status_code) and not cf_clearance:
            return {"ok": True, "token": "NO_CF", "ua": session.headers.get("User-Agent"), "type": "none"}

        if cf_clearance and not check_cf(r.text, r.status_code):
            return {"ok": True, "token": cf_clearance, "ua": session.headers.get("User-Agent"), "type": "instant"}

        time.sleep(10)
        r2 = session.get(url, timeout=30, allow_redirects=True)
        cf2 = session.cookies.get("cf_clearance")
        if cf2 and not check_cf(r2.text, r2.status_code):
            return {"ok": True, "token": cf2, "ua": session.headers.get("User-Agent"), "type": "soft"}

        print("[WAF] Gagal. Beralih ke Hard Solver...", file=sys.stderr)
        hard_res = call_hard_solver(url, proxy, ua)
        if hard_res.get("ok"):
            hard_res["type"] = "hard"
            return hard_res
        return {"ok": False, "error": hard_res.get("error", "Gagal menembus CF Kuat")}
    except Exception as e:
        return {"ok": False, "error": str(e)}

if __name__ == "__main__":
    line = sys.stdin.readline()
    if not line: sys.exit(0)
    try:
        data = json.loads(line)
        task = data.get("task", {})
        c_str = task.get("cookies", "")
        cookies = {c.split("=")[0].strip(): c.split("=")[1].strip() for c in c_str.split(";") if "=" in c}
        res = solve_waf(task.get("websiteURL"), task.get("proxy"), cookies, task.get("ua"))
        
        # PASTIKAN HANYA MENGELUARKAN JSON
        print(json.dumps(res))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
