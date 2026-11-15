import runpy, time, json, base64, sys, re

ns = runpy.run_path('satoshifaucet-noproxy.py')
Bot = ns['Bot']; norm = ns['norm_proxy']; mask = ns['mask_proxy']

AUTH = 'acbcb24e410dbeb9'
PASS = '8654fd49a819de6a'
SESS = 'sess-bc2'          # sesi FR baru
PROXY = f'http://{AUTH}-geo-fr-{SESS}-life-7200:{PASS}@gate-eu.vaultproxies.com:80'

b = Bot()
b.proxy = norm(PROXY)
b.proxy_idx = 97
print('[T] proxy', mask(b.proxy), flush=True)

ok = b.login()
print('[T] login ok:', ok, flush=True)
if not ok:
    sys.exit(1)

d = b.browser_claim_start()
if not d:
    print('[T] daemon gagal', flush=True); sys.exit(1)
f = d.get('fields') or {}
m = re.search(ns['DAILY_RE'], f.get('bodyText') or '')
print('[T] daily sebelum:', (m.group(1) + '/' + m.group(2)) if m else '?', flush=True)

r = b.bc_cmd({'cmd': 'challenge'}, timeout=60)
if not (r or {}).get('ok'):
    print('[T] challenge gagal:', json.dumps(r)[:150], flush=True)
    b.browser_claim_stop(); sys.exit(1)
ch = r['challenge']
img = ch['img']
open(ns['IMG'], 'wb').write(base64.b64decode(img.split(',', 1)[1] if ',' in img else img))

pts, mode, assign = b.pick_points()
print('[T] solver pts:', pts, 'mode:', mode, flush=True)
if not pts:
    print('[T] NOT CONFIDENT — batal submit', flush=True)
    b.browser_claim_stop(); sys.exit(1)

r2 = b.bc_cmd({'cmd': 'check', 'csrf': f['csrf'], 'token': ch['token'], 'pts': pts}, timeout=90)
j = (r2 or {}).get('json') or {}
print('[T] check ->', json.dumps(r2, ensure_ascii=False)[:400], flush=True)
if not (j.get('ok') and j.get('pass')):
    print('[T] CHECK GAGAL', flush=True)
    b.browser_claim_stop(); sys.exit(1)

r3 = b.bc_cmd({'cmd': 'verify', 'csrf': j.get('csrf') or f['csrf'],
               'token': f['token'], 'nonce': f['nonce'],
               'uf': b.fp, 'utt': ns['TZ'], 'ls': ns['LANGS'],
               'pass': j['pass'], 'wallet': ns['EMAIL']}, timeout=90)
print('[T] verify ->', json.dumps(r3, ensure_ascii=False)[:600], flush=True)
r4 = b.bc_cmd({'cmd': 'page'}, timeout=120)
print('[T] page ->', json.dumps(r4, ensure_ascii=False)[:300], flush=True)
b.browser_claim_stop()
print('[T] selesai (klaim proxy penuh)', flush=True)
