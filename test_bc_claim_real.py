import runpy, sys

ns = runpy.run_path('satoshifaucet-noproxy.py')
Bot = ns['Bot']; norm = ns['norm_proxy']; mask = ns['mask_proxy']

AUTH = 'acbcb24e410dbeb9'
PASS = '8654fd49a819de6a'
SESS = 'sess-bcf9'          # sesi FR baru lagi
PROXY = f'http://{AUTH}-geo-fr-{SESS}-life-7200:{PASS}@gate-eu.vaultproxies.com:80'

b = Bot()
b.proxy = norm(PROXY)
b.proxy_idx = 96
print('[T] proxy', mask(b.proxy), flush=True)
ok = b.login()
print('[T] login ok:', ok, flush=True)
if not ok:
    sys.exit(1)

# jalankan alur klaim produksi apa adanya (refresh loop + check + verify + konfirmasi daily)
res = b.claim_via_browser()
print('[T] claim_via_browser ->', res, flush=True)
print('[T] daily sekarang:', (b.bc_ready or {}), flush=True)
try:
    print('[T] sf-status.json:', open('sf-status.json').read(), flush=True)
except Exception as e:
    print('[T] status read err', e, flush=True)
