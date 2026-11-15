import requests
import time
import sys

# 1. KONFIGURASI URL SOLVER (Otomatis dari GitHub)
GITHUB_RAW_URL = "https://raw.githubusercontent.com/gi2h/python-scripts/main/solver_url.txt"

# 2. KONFIGURASI TARGET & PROXY
TARGET_URL = "https://pandafaucet.com/claim-usdt"
SITEKEY = "0x4AAAAAAAD2b0X0d7gT13Bv" 

# Format Proxy: http://username:password@host:port
PROXY_URL = "http://19cd190a3d8fe4a4:f8806fc3799eca55@gate-us.vaultproxies.com:777"

def get_latest_solver_url():
    print("🔍 Mengambil URL terbaru dari GitHub...")
    try:
        response = requests.get(GITHUB_RAW_URL, timeout=10)
        if response.status_code == 200:
            return response.text.strip()
    except Exception as e:
        print(f"❌ Gagal: {e}")
    return None

def test_solver_with_proxy():
    solver_url = get_latest_solver_url()
    if not solver_url:
        return

    print(f"✅ URL Solver: {solver_url}")
    print(f"🌐 Menggunakan Proxy: {PROXY_URL[:30]}...")
    print("-" * 60)

    # Payload dengan tambahan parameter "proxy"
    payload = {
        "method": "CloudflareTask",
        "task": {
            "type": "turnstile",
            "websiteUrl": TARGET_URL,
            "websiteKey": SITEKEY,
            "proxy": PROXY_URL # <--- INI KUNCI UTAMANYA
        }
    }
    
    headers = {"Content-Type": "application/json"}
    
    try:
        print("🚀 Mengirim task...")
        response = requests.post(f"{solver_url}/solve", json=payload, headers=headers, timeout=15)
        print(f"HTTP Status: {response.status_code}")
        
        data = response.json()
        task_id = data.get("taskId") or data.get("id")
        
        if not task_id:
            print(f"❌ Gagal mendapatkan Task ID: {data}")
            return
            
        print(f"✅ Task ID: {task_id}")
        print("⏳ Polling (Menunggu captcha dipecahkan)...")

        # Polling
        poll_payload = {"taskId": task_id}
        start_time = time.time()
        
        while time.time() - start_time < 150:
            poll_resp = requests.post(f"{solver_url}/solve", json=poll_payload, headers=headers, timeout=10)
            poll_data = poll_resp.json()
            status = poll_data.get("status")
            
            if status == "ready":
                token = poll_data.get("solution", {}).get("token")
                print(f"\n\n🎉 BERHASIL! Token didapatkan:\n{token[:60]}...")
                return True
            elif status == "error":
                print(f"\n\n❌ Solver Error: {poll_data.get('err')}")
                return False
            elif status == "processing":
                sys.stdout.write(".")
                sys.stdout.flush()
                
            time.sleep(5)
            
    except Exception as e:
        print(f"❌ Gagal terhubung: {e}")

if __name__ == "__main__":
    test_solver_with_proxy()
