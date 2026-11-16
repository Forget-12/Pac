import sys
import json
import time
import traceback
import asyncio
from adslab import Adslab
from utils import CaptchaError

MAX_RETRIES_WITH_PROXY = 2
RETRY_DELAY = 2  # seconds between retries


def try_solve(sitekey, siteurl, subid, proxy, cookies, attempt_num):
    """Single attempt; returns (success_dict or None, error_msg or None)."""
    try:
        solver = Adslab(sitekey, siteurl, subid, proxy, cookies)
        result = asyncio.run(solver.solve())
        if isinstance(result, CaptchaError):
            return None, str(result)
        return {"ok": True, "token": result["token"]}, None
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)}"


def solve_with_retries(sitekey, siteurl, subid, proxy, cookies):
    """Attempt with proxy first, then without proxy as a fallback."""
    last_error = None

    # 1) Try with proxy (up to MAX_RETRIES_WITH_PROXY attempts)
    for attempt in range(1, MAX_RETRIES_WITH_PROXY + 1):
        token, err = try_solve(sitekey, siteurl, subid, proxy, cookies, attempt)
        if token:
            return token
        last_error = err
        if attempt < MAX_RETRIES_WITH_PROXY:
            time.sleep(RETRY_DELAY)

    # 2) Fallback: retry WITHOUT proxy
    for attempt in range(1, 3):
        token, err = try_solve(sitekey, siteurl, subid, None, cookies, attempt)
        if token:
            return token
        last_error = err
        time.sleep(RETRY_DELAY)

    return {"ok": False, "error": last_error}


def main():
    line = sys.stdin.readline()
    if not line:
        print(json.dumps({"ok": False, "error": "No input"}))
        return
    try:
        data = json.loads(line)
        task = data.get("task", {})
        sitekey = task.get("websiteKey")
        siteurl = task.get("websiteURL")
        subid = task.get("subId", "widget_user")
        proxy = task.get("proxy")
        cookies = task.get("cookies")

        if not sitekey or not siteurl:
            raise ValueError("websiteKey & websiteURL wajib diisi")

        result = solve_with_retries(sitekey, siteurl, subid, proxy, cookies)
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {str(e)}"}))
        traceback.print_exc(file=sys.stderr)


if __name__ == "__main__":
    main()
