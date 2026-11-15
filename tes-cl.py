import requests

# URL dari GitHub Actions Anda
url = "https://von-payroll-athletes-disco.trycloudflare.com/solve"

# Payload dummy untuk mengetes (menggunakan website dan sitekey palsu)
payload = {
    "method": "CloudflareTask",
    "task": {
        "type": "turnstile",
        "websiteUrl": "https://pandafaucet.com",
        "websiteKey": "0x4AAAAAAAD2b0X0d7gT13Bv" 
    }
}

headers = {
    "Content-Type": "application/json"
}

print("Mengirim request ke Solver...")
try:
    response = requests.post(url, json=payload, timeout=15)
    print(f"HTTP Status: {response.status_code}")
    
    # Jika berhasil, server akan membalas dengan JSON berisi taskId
    print("Response dari Solver:")
    print(response.json())
    
except Exception as e:
    print(f"Gagal terhubung: {e}")
