import runpy, time, json, base64, sys

ns = runpy.run_path('satoshifaucet-noproxy.py')
Bot = ns['Bot']; norm = ns['norm_proxy']; mask = ns['mask_proxy']

AUTH = 'acbcb24e410dbeb9'
PASS = '8654fd49a819de6a'
SESS = 'sess-bc1'          # sesi FR baru, bersih
PROXY = f'http://{AUTH}-geo-fr-{SESS}-life-7200:{PASS}@gate-eu.vaultproxies.com:80'

b = Bot()
b.proxy = norm(PROXY)
b.proxy_idx = 98
print('[T] proxy', mask(b.proxy), flush=True)

ok = b.login()
print('[T] login ok:', ok, flush=True)
if not ok:
    sys.exit(1)

d = b.browser_claim_start()
print('[T] daemon ready:', json.dumps(d, ensure_ascii=False)[:500] if d else None, flush=True)
if not d:
    sys.exit(1)
f = d.get('fields') or {}
print('[T] csrf', bool(f.get('csrf')), 'token', bool(f.get('token')),
      'nonce', bool(f.get('nonce')), 'title', f.get('title'), 'url', f.get('url'), flush=True)
print('[T] bodyText:', re.sub(r'\s+', ' ', f.get('bodyText') or '')[:300], flush=True) if False else None
import re
print('[T] bodyText:', re.sub(r'\s+', ' ', f.get('bodyText') or '')[:300], flush=True)
m = re.search(ns['DAILY_RE'], f.get('bodyText') or '')
print('[T] daily:', (m.group(1) + '/' + m.group(2)) if m else '?', flush=True)

r = b.bc_cmd({'cmd': 'challenge'}, timeout=60)
print('[T] challenge ok:', bool((r or {}).get('ok')), flush=True)
if not (r or {}).get('ok'):
    b.browser_claim_stop(); sys.exit(1)
ch = r['challenge']
img = ch.get('img', '')
print('[T] img len:', len(img), 'token len:', len(ch.get('token', '')), flush=True)
raw = img.split(',', 1)[1] if ',' in img else img
open(ns['IMG'], 'wb').write(base64.b64decode(raw))
open('/data/data/com.termux/files/home/python-scripts/c-cosmos-proxy-test.png', 'wb').write(
    base64.b64decode(raw))

pts, mode, assign = b.pick_points()
print('[T] solver pts:', pts, 'mode:', mode, flush=True)

if not pts:
    print('[T] NOT CONFIDENT — skip check, tidak ada yang dikirim', flush=True)
else:
    r2 = b.bc_cmd({'cmd': 'check', 'csrf': f['csrf'], 'token': ch['token'], 'pts': pts}, timeout=90)
    print('[T] check ->', json.dumps(r2, ensure_ascii=False)[:400], flush=True)
# STOP: tidak panggil verify (tidak ada klaim)
b.browser_claim_stop()
print('[T] selesai (dry-run, tanpa verify/claim)', flush=True)
