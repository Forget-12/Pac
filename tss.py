import requests
import time
import json

GITHUB_RAW_URL = "https://raw.githubusercontent.com/gi2h/python-scripts/main/solver_url.txt"
TARGET_URL = "https://pandafaucet.com/claim-usdt"
SITEKEY = "0x4AAAAAAAD2b0X0d7gT13Bv" 
PROXY_URL = "http://19cd190a3d8fe4a4:f8806fc3799eca55@gate-us.vaultproxies.com:777"

def get_latest_solver_url():
    try:
        response = requests.get(GITHUB_RAW_URL, timeout=10)
        if response.status_code == 200:
            return response.text.strip()
    except Exception:
        pass
    return None

def test_solver_raw():
    solver_url = get_latest_solver_url()
    if not solver_url: return

    print(f"🌐 URL Solver: {solver_url}")
    
    payload = {
        "method": "CloudflareTask",
        "task": {
            "type": "turnstile",
            "websiteUrl": TARGET_URL,
            "websiteKey": SITEKEY,
            "proxy": PROXY_URL
        }
    }
    
    headers = {"Content-Type": "application/json"}
    
    try:
        print("🚀 Mengirim task...")
        response = requests.post(f"{solver_url}/solve", json=payload, headers=headers, timeout=15)
        print(f"HTTP Status Submit: {response.status_code}")
        
        data = response.json()
        task_id = data.get("taskId") or data.get("id")
        if not task_id:
            print(f"❌ Gagal submit. Raw Response:\n{response.text}")
            return
            
        print(f"✅ Task ID: {task_id}\n⏳ Polling...")

        poll_payload = {"taskId": task_id}
        
        while True:
            poll_resp = requests.post(f"{solver_url}/solve", json=poll_payload, headers=headers, timeout=10)
            poll_text = poll_resp.text
            
            try:
                poll_data = json.loads(poll_text)
                status = poll_data.get("status")
                
                if status == "ready":
                    print(f"\n🎉 BERHASIL! Token didapatkan.")
                    break
                elif status == "error":
                    # MENCETAK PESAN ASLI LENGKAP
                    print(f"\n\n❌ ERROR DITEMUKAN! Raw Response:\n{poll_text}")
                    break
                elif status == "processing":
                    print(".", end="", flush=True)
                    
            except Exception:
                print(f"\n⚠️ Response tidak valid (bukan JSON):\n{poll_text}")
                break
                
            time.sleep(5)
            
    except Exception as e:
        print(f"❌ Gagal terhubung: {e}")

if __name__ == "__main__":
    test_solver_raw()
