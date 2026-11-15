import sys, json, traceback
from adslab import Adslab
from utils import CaptchaError

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

        solver = Adslab(sitekey, siteurl, subid, proxy, cookies)
        result = solver.solve() # Sinkron!
        
        if isinstance(result, CaptchaError):
            raise Exception(str(result))
            
        print(json.dumps({"ok": True, "token": result["token"]}))
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {str(e)}"}))
        traceback.print_exc(file=sys.stderr)

if __name__ == "__main__":
    main()
