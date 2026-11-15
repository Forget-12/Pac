import requests

# Gunakan URL BARU yang ada di layar Anda
url = "https://inspired-sporting-fitness-interventions.trycloudflare.com/solve"

payload = {
    "method": "CloudflareTask",
    "task": {
        "type": "turnstile",
        "websiteUrl": "https://pandafaucet.com",
        "websiteKey": "0x4AAAAAAAD2b0X0d7gT13Bv" 
    }
}

print("Mengirim request ke Solver...")
try:
    response = requests.post(url, json=payload, timeout=15)
    print(f"HTTP Status: {response.status_code}")
    print("Response:", response.text)
except Exception as e:
    print(f"Gagal terhubung: {e}")
