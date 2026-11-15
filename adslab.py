import asyncio
import base64
import hashlib
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from curl_cffi import requests

try:
    from .utils import CaptchaError
except ImportError:
    from utils import CaptchaError

_POW_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"
_INTERNAL_ERROR = "Internal solver error occurred, please try again later"

_alc_solve = None

def _get_alc_solve():
    global _alc_solve
    if _alc_solve is None:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        if current_dir not in sys.path:
            sys.path.insert(0, current_dir)
        try:
            # Kita gunakan class AlcaptchaSolver dari alc_ori.py
            from alc_ori import AlcaptchaSolver
            _alc_solve = AlcaptchaSolver().solve
        except ImportError:
            raise Exception("alc_ori.py tidak ditemukan atau tidak memiliki AlcaptchaSolver")
    return _alc_solve

class Adslab:
    def __init__(self, sitekey, siteurl, sub_id="widget_user", proxy=None, cookies=None):
        self.sitekey = sitekey
        self.siteurl = self._normalize_siteurl(siteurl)
        self.sub_id = sub_id
        self.proxy = proxy
        self.proxy_dict = {"http": proxy, "https": proxy} if proxy else None
        
        self.cookies = {}
        if cookies:
            if isinstance(cookies, str):
                for c in cookies.split(";"):
                    if "=" in c:
                        k, v = c.strip().split("=", 1)
                        self.cookies[k] = v
            elif isinstance(cookies, dict):
                self.cookies = cookies

        self.base_url = "https://adslab.me"
        self.api_path = "/api/v1/alcaptcha"

    @staticmethod
    def _normalize_siteurl(url: str) -> str:
        if not url:
            return ""
        url = str(url).strip()
        for prefix in ("https://", "http://", "//"):
            if url.startswith(prefix):
                url = url[len(prefix):]
                break
        url = url.split("/")[0]
        return url.lower()

    def _get_session(self):
        session = requests.Session(impersonate="chrome124")
        if self.cookies:
            session.cookies.update(self.cookies)
        return session

    def _get_proxy_ip(self, session=None):
        if not self.proxy:
            return ""
        own_session = session is None
        if own_session:
            session = self._get_session()
        try:
            res = session.get(
                "https://api.ipify.org?format=json",
                proxies=self.proxy_dict,
                timeout=10,
            )
            return res.json().get("ip", "")
        except Exception:
            return ""
        finally:
            if own_session:
                try: session.close()
                except Exception: pass

    @staticmethod
    def _parse_css_percent(val):
        if val is None:
            return None
        val = str(val).strip().replace('%', '')
        try:
            return float(val)
        except ValueError:
            return None

    def _generate_pow(self):
        seed = f"{''.join(random.choices(_POW_CHARS, k=13))}{int(time.time() * 1000)}"
        prefix = seed.encode('utf-8')
        sha256 = hashlib.sha256
        nonce = 0
        while True:
            digest = sha256(prefix + str(nonce).encode('utf-8')).digest()
            if digest[0] == 0 and digest[1] < 16:
                return {"seed": seed, "nonce": nonce}
            nonce += 1

    @staticmethod
    def _decode_json(response):
        try: return response.json()
        except Exception: return None

    @staticmethod
    def _error_message(response, data):
        if isinstance(data, dict):
            message = data.get("message") or data.get("error")
            if message: return str(message)
        body = ""
        try: body = (response.text or "").strip().replace("\n", " ")
        except Exception: pass
        if len(body) > 200: body = body[:200] + "…"
        return f"HTTP Error {response.status_code}: {body}"

    def _init_captcha(self, session=None):
        pow_data = self._generate_pow()
        payload = {
            "sitekey": self.sitekey,
            "domain": self.siteurl,
            "subid": self.sub_id,
            "pow": pow_data
        }
        headers = {
            "Accept": "*/*",
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/json",
            "Origin": f"https://{self.siteurl}",
            "Referer": f"https://{self.siteurl}/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site"
        }
        init_url = f"{self.base_url}{self.api_path}/init"
        own_session = session is None
        if own_session: session = self._get_session()

        try:
            response = session.post(init_url, json=payload, headers=headers, proxies=self.proxy_dict, timeout=15)
            data = self._decode_json(response)

            if response.status_code >= 400:
                if own_session: session.close()
                return CaptchaError.unsolvable(self._error_message(response, data), _INTERNAL_ERROR)

            if not isinstance(data, dict):
                if own_session: session.close()
                return CaptchaError.unsolvable(f"Invalid JSON response from AdsLab init (HTTP {response.status_code})", _INTERNAL_ERROR)

            if not data.get("success"):
                if own_session: session.close()
                return CaptchaError.unsolvable(data.get('message', 'Unknown API response'), _INTERNAL_ERROR)
            return data, session
        except Exception as e:
            if own_session: session.close()
            return CaptchaError.unsolvable(str(e), _INTERNAL_ERROR)

    def _load_captcha(self, url, session):
        try:
            response = session.get(url, proxies=self.proxy_dict, timeout=15)
            if response.status_code >= 400:
                return CaptchaError.unsolvable(self._error_message(response, None), _INTERNAL_ERROR)
            return base64.b64encode(response.content).decode('utf-8')
        except Exception as e:
            return CaptchaError.unsolvable(str(e), _INTERNAL_ERROR)

    async def _solve_motion(self, b64_img, debug=False, expected=0):
        try:
            solve_alc = _get_alc_solve()
            result = await solve_alc(b64_img, debug=debug, expected=expected)
            if isinstance(result, CaptchaError): return result
            if not result or not result.get("answer"):
                return CaptchaError.unsolvable("SOLVER_NO_ANSWER", "Solver returned no answer")
            return result
        except Exception as e:
            return CaptchaError.unsolvable(str(e), _INTERNAL_ERROR)

    def _build_verify_payload(self, token, target_ids, indices, start_time_ms):
        vt, ct = [], []
        current_time_ms = int(time.time() * 1000)

        for idx_str in indices:
            col, row = map(int, idx_str.split(":"))
            bbox_str = f"{col * 100}|{row * 50}|100|50"
            vt.append(base64.b64encode(bbox_str.encode('utf-8')).decode('utf-8'))
            ct.append(current_time_ms)

        ht = int(current_time_ms - start_time_ms)
        try: dz = str(datetime.now().astimezone().tzinfo)
        except Exception: dz = "UTC"

        payload_obj = {"a": target_ids, "vt": vt, "hf": "", "ht": ht, "dz": dz, "mm": 0, "ct": ct}
        json_str = json.dumps(payload_obj, separators=(',', ':'))
        b64_str = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
        return {"token": token, "p_payload": b64_str[::-1]}

    def _verify(self, token, target_ids, indices, start_time_ms, session):
        final_payload = self._build_verify_payload(token, target_ids, indices, start_time_ms)
        headers = {
            "Accept": "*/*", "Content-Type": "application/json",
            "Origin": f"https://{self.siteurl}", "Referer": f"https://{self.siteurl}/",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36"
        }
        verify_url = f"{self.base_url}{self.api_path}/verify-click"

        try:
            resp = session.post(verify_url, json=final_payload, headers=headers, proxies=self.proxy_dict, timeout=15)
            result = self._decode_json(resp)
            if resp.status_code >= 400:
                return CaptchaError.unsolvable(self._error_message(resp, result), _INTERNAL_ERROR)
            if not isinstance(result, dict):
                return CaptchaError.unsolvable(f"Invalid JSON response from AdsLab verify (HTTP {resp.status_code})", _INTERNAL_ERROR)
            
            if not result.get("success"):
                return CaptchaError.unsolvable(result.get('message', 'Verify API returned success=false'), "Solver failed to find any valid solution.")
            return result.get("token")
        except Exception as e:
            return CaptchaError.unsolvable(str(e), _INTERNAL_ERROR)

    async def solve(self, debug=False):
        start_time = time.perf_counter()
        loop = asyncio.get_running_loop()
        http_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="adslab-http")
        session = None
        
        try:
            session = await loop.run_in_executor(http_executor, self._get_session)
            init_result = await loop.run_in_executor(http_executor, self._init_captcha, session)
            
            if isinstance(init_result, CaptchaError): return init_result
            data, session = init_result

            b64_img = await loop.run_in_executor(http_executor, self._load_captcha, data["captchaUrl"], session)
            if isinstance(b64_img, CaptchaError): return b64_img

            solved = await self._solve_motion(b64_img, debug=debug, expected=data.get("expectedLength", 0))
            if isinstance(solved, CaptchaError): return solved

            indices = solved.get("answer", {}).get("index", [])

            valid_cells = []
            for cell in data["elementsMap"]:
                css = cell["css"]
                if css.get("opacity", 1) == 0: continue
                cell_top = self._parse_css_percent(css.get("top"))
                cell_left = self._parse_css_percent(css.get("left"))
                if cell_top is None or cell_left is None: continue
                valid_cells.append((cell_top, cell_left, cell["id"]))

            target_elements = []
            for idx_str in indices:
                col, row = map(int, idx_str.split(":"))
                target_top = row * 50.0
                target_left = col * 33.33

                for cell_top, cell_left, cell_id in valid_cells:
                    if abs(cell_top - target_top) < 0.5 and abs(cell_left - target_left) < 0.5:
                        target_elements.append(cell_id)
                        break
                else:
                    return CaptchaError.unsolvable(f"Target index {idx_str} not found in elementsMap", _INTERNAL_ERROR)

            if not target_elements:
                return CaptchaError.unsolvable("Resulted indices mapped to 0 valid targets", _INTERNAL_ERROR)

            final_token = await loop.run_in_executor(
                http_executor, self._verify, data["token"], target_elements, indices, int(start_time * 1000), session
            )
            if isinstance(final_token, CaptchaError): return final_token

            return {"token": final_token}
        finally:
            if session is not None:
                try: await loop.run_in_executor(http_executor, session.close)
                except Exception: pass
            http_executor.shutdown(wait=False)
