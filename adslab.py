import json, base64, urllib.parse, hashlib, time, asyncio
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

        self.session = requests.Session(impersonate="chrome124")
        if self.proxy: self.session.proxies = {"http": self.proxy, "https": self.proxy}
        if self.cookies: self.session.cookies.update(self.cookies)
            
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
            "Origin": self.origin,
            "Referer": self.referer,
        }

    def _generate_pow(self, seed="dummy_seed_123"):
        nonce = 0
        while nonce < 500000:
            text = f"{seed}{nonce}"
            h = hashlib.sha256(text.encode()).hexdigest()
            if h.startswith("0000"): 
                return {"seed": seed, "nonce": nonce, "hash": h}
            nonce += 1
        return {"seed": seed, "nonce": nonce, "hash": ""}

    def solve(self):
        init_data = self._init_captcha()
        
        if not init_data.get("success"):
            raise AdslabError(f"Gagal init: {init_data}")

        challenge_token = init_data.get("token")
        expected_len = init_data.get("expectedLength", 3)
        
        img_base64 = None
        if "gifTraps" in init_data and init_data["gifTraps"]:
            img_base64 = init_data["gifTraps"][0]
        elif "base64Traps" in init_data and init_data["base64Traps"]:
            img_base64 = init_data["base64Traps"][0]
        elif "captchaUrl" in init_data:
            url = init_data["captchaUrl"]
            resp = self.session.get(url, headers=self.headers, timeout=30)
            img_base64 = base64.b64encode(resp.content).decode('utf-8')

        if isinstance(img_base64, dict):
            img_base64 = img_base64.get("data") or img_base64.get("image")

        if not challenge_token or not img_base64:
            raise AdslabError(f"Gagal ekstrak gambar dari: {list(init_data.keys())}")

        try:
            if not AlcaptchaSolver: raise AdslabError("File alc_ori.py tidak ditemukan")
            solver = AlcaptchaSolver()
            if "," in img_base64: img_base64 = img_base64.split(",", 1)[1]
            
            # PERBAIKAN: Panggil async function menggunakan asyncio.run()
            result = asyncio.run(solver.solve(img_base64, expected=expected_len))
            
            if not isinstance(result, dict) or not result.get("answer") or not result["answer"].get("coord"):
                raise AdslabError(f"Gagal mendeteksi koordinat: {result}")
                
            coords_raw = result["answer"]["coord"]
            answers = []
            for c in coords_raw:
                x, y = c.split(":")
                answers.append({"x": int(x), "y": int(y)})
        except Exception as e:
            raise AdslabError(f"OpenCV Error: {str(e)}")

        token = self._verify(challenge_token, answers)
        if not token: raise AdslabError("Server menolak jawaban")
        return token

    def _init_captcha(self):
        url = "https://adslab.me/api/v1/alcaptcha/init"
        payload = {
            "sitekey": self.sitekey, 
            "subid": self.subid,
            "domain": self.hostname,
            "pow": self._generate_pow() 
        }
        resp = self.session.post(url, json=payload, headers=self.headers, timeout=30)
        if resp.status_code != 200: raise AdslabError(f"Init failed HTTP {resp.status_code}: {resp.text[:100]}")
        return resp.json()

    def _verify(self, token, answers):
        url = "https://adslab.me/api/v1/alcaptcha/verify"
        payload = {
            "token": token, 
            "sitekey": self.sitekey,
            "subid": self.subid, 
            "answers": answers,
            "pow": self._generate_pow()
        }
        resp = self.session.post(url, json=payload, headers=self.headers, timeout=30)
        if resp.status_code == 200: 
            return resp.json().get("token")
        else: 
            raise AdslabError(f"Verify failed: {resp.text}")
