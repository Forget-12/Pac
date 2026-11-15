import json, base64, urllib.parse
from curl_cffi import requests

try:
    from alc_ori import AlcaptchaSolver
except ImportError:
    AlcaptchaSolver = None

class AdslabError(Exception): pass

class Adslab:
    def __init__(self, sitekey, siteurl, subid="widget_user", proxy=None, cookies=None):
        self.sitekey = sitekey
        self.siteurl = siteurl
        self.subid = subid
        self.proxy = proxy
        
        parsed_url = urllib.parse.urlparse(siteurl)
        if not parsed_url.scheme:
            siteurl = f"https://{siteurl}"
            parsed_url = urllib.parse.urlparse(siteurl)
            
        self.origin = f"{parsed_url.scheme}://{parsed_url.netloc}"
        self.referer = siteurl
        self.hostname = parsed_url.netloc
        
        self.cookies = {}
        if cookies:
            if isinstance(cookies, str):
                for c in cookies.split(";"):
                    if "=" in c:
                        k, v = c.strip().split("=", 1)
                        self.cookies[k] = v
            elif isinstance(cookies, dict):
                self.cookies = cookies

        self.session = requests.Session(impersonate="chrome110")
        if self.proxy: self.session.proxies = {"http": self.proxy, "https": self.proxy}
        if self.cookies: self.session.cookies.update(self.cookies)
            
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
            "Origin": self.origin,
            "Referer": self.referer,
        }

    def solve(self):
        init_data = self._init_captcha()
        challenge_id = init_data.get("challenge_id")
        img_base64 = init_data.get("image")
        
        if not challenge_id or not img_base64:
            raise AdslabError(f"Gagal dapat challenge. Respons: {init_data}")

        try:
            if not AlcaptchaSolver: raise AdslabError("File alc_ori.py tidak ditemukan")
            solver = AlcaptchaSolver()
            if "," in img_base64: img_base64 = img_base64.split(",", 1)[1]
            result = solver.solve(img_base64, expected=3)
            if not result or not result.get("answer") or not result["answer"].get("coord"):
                raise AdslabError("Gagal mendeteksi koordinat")
            coords_raw = result["answer"]["coord"]
            answers = []
            for c in coords_raw:
                x, y = c.split(":")
                answers.append({"x": int(x), "y": int(y)})
        except Exception as e:
            raise AdslabError(f"OpenCV Error: {str(e)}")

        token = self._verify(challenge_id, answers)
        if not token: raise AdslabError("Server menolak jawaban")
        return token

    def _init_captcha(self):
        # KITA UBAH URL-NYA DI SINI: Gunakan /api/v1/...
        url = "https://adslab.me/api/v1/alcaptcha/init"
        payload = {
            "sitekey": self.sitekey, "subid": self.subid,
            "domain": self.hostname
        }
        resp = self.session.post(url, json=payload, headers=self.headers, timeout=30)
        if resp.status_code != 200: raise AdslabError(f"Init failed HTTP {resp.status_code}: {resp.text[:100]}")
        return resp.json()

    def _verify(self, challenge_id, answers):
        # KITA UBAH URL-NYA DI SINI: Gunakan /api/v1/...
        url = "https://adslab.me/api/v1/alcaptcha/verify"
        payload = {
            "challenge_id": challenge_id, "sitekey": self.sitekey,
            "subid": self.subid, "answers": answers
        }
        resp = self.session.post(url, json=payload, headers=self.headers, timeout=30)
        if resp.status_code == 200: return resp.json().get("token")
        else: raise AdslabError(f"Verify failed: {resp.text}")
