import requests

url = "https://von-payroll-athletes-disco.trycloudflare.com/solve"

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
    # Jika server app.js Anda butuh API KEY, buka komentar di bawah ini dan isi:
    # "X-API-Key": "API_KEY_ANDA_DISINI" 
}

print("Mengirim request ke Solver...")
try:
    response = requests.post(url, json=payload, timeout=15)
    print(f"HTTP Status: {response.status_code}")
    print(f"Pesan Asli dari Server: {response.text}") # Kita cetak teks aslinya
except Exception as e:
    print(f"Gagal terhubung: {e}")
