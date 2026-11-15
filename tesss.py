import requests
import time
import sys

# =====================================================================
# KONFIGURASI
# =====================================================================
# URL raw GitHub untuk mengambil file solver_url.txt secara otomatis
GITHUB_RAW_URL = "https://raw.githubusercontent.com/gi2h/python-scripts/main/solver_url.txt"

# Target PandaFaucet (Bisa disesuaikan)
TARGET_URL = "https://pandafaucet.com/claim-usdt"
SITEKEY = "0x4AAAAAAAD2b0X0d7gT13Bv" 

def get_latest_solver_url():
    """Mengambil URL solver terbaru dari GitHub"""
    print("🔍 Mengambil URL terbaru dari GitHub...")
    try:
        response = requests.get(GITHUB_RAW_URL, timeout=10)
        if response.status_code == 200:
            url = response.text.strip()
            if url.startswith("https://"):
                return url
        print(f"❌ Gagal mengambil URL. HTTP Status: {response.status_code}")
    except Exception as e:
        print(f"❌ Koneksi ke GitHub gagal: {e}")
    return None

def test_solver():
    # 1. Ambil URL Otomatis
    solver_url = get_latest_solver_url()
    if not solver_url:
        print("⚠️ Tidak bisa melanjutkan tes tanpa URL Solver.")
        return

    print(f"✅ URL Solver Ditemukan: {solver_url}")
    print("-" * 60)

    # 2. Siapkan Payload
    payload = {
        "method": "CloudflareTask",
        "task": {
            "type": "turnstile",
            "websiteUrl": TARGET_URL,
            "websiteKey": SITEKEY
        }
    }
    
    headers = {"Content-Type": "application/json"}
    
    try:
        # 3. Submit Task
        print("🚀 Mengirim task ke Solver...")
        response = requests.post(f"{solver_url}/solve", json=payload, headers=headers, timeout=15)
        print(f"HTTP Status: {response.status_code}")
        
        if response.status_code not in (200, 202):
            print(f"❌ Gagal Submit: {response.text}")
            return

        data = response.json()
        task_id = data.get("taskId") or data.get("id")
        
        if not task_id:
            print(f"❌ Task ID tidak ditemukan: {data}")
            return
            
        print(f"✅ Task ID Diterima: {task_id}")
        print("⏳ Menunggu solver memproses captcha (Polling)...\n")

        # 4. Polling Status
        poll_payload = {"taskId": task_id}
        start_time = time.time()
        max_wait = 150 # Maksimal tunggu 150 detik (standar solver)
        
        while time.time() - start_time < max_wait:
            try:
                poll_resp = requests.post(f"{solver_url}/solve", json=poll_payload, headers=headers, timeout=10)
                poll_data = poll_resp.json()
                status = poll_data.get("status")
                
                if status == "ready":
                    token = poll_data.get("solution", {}).get("token")
                    print(f"\n\n🎉 BERHASIL! Token didapatkan.")
                    print(f"🔑 Token (50 char): {token[:50]}...")
                    return True
                    
                elif status == "error":
                    err_msg = poll_data.get("err", {})
                    print(f"\n\n❌ Solver Error: {err_msg}")
                    return False
                    
                elif status == "processing":
                    # Menampilkan indikator loading
                    sys.stdout.write(".")
                    sys.stdout.flush()
                    
            except Exception as e:
                print(f"\n⚠️ Koneksi terputus saat polling: {e}")
                
            time.sleep(5) # Cek setiap 5 detik
            
        print("\n\n⏰ Timeout: Solver tidak menyelesaikan task.")
        return False
        
    except Exception as e:
        print(f"❌ Gagal terhubung ke server: {e}")

if __name__ == "__main__":
    test_solver()
