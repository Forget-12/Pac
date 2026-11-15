import subprocess, sys, json, time, os
P = 'http://acbcb24e410dbeb9-geo-fr-sess-bc4-life-7200:8654fd49a819de6a@gate-eu.vaultproxies.com:80'
env = dict(os.environ)
cmd = ["proot-distro", "login", "ubuntu", "--", "bash", "-c",
       f"cd {os.getcwd()} && export DISPLAY=:99 && export CF_PAC=1 && export CF_PROXY='{P}' && export CF_WAIT=150 && node browser_claim.js sf-noproxy-state.json"]
p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True, bufsize=1)
def getline(timeout=200):
    t0 = time.time()
    while time.time() - t0 < timeout:
        line = p.stdout.readline()
        if line: return line.strip()
        time.sleep(0.5)
    return None
print("[T] spawned", flush=True)
ready = getline(240)
print("[T] ready:", (ready or "TIMEOUT")[:800], flush=True)
if ready:
    try: pd = json.loads(ready)
    except: pd = {}
    if pd.get("ready"):
        p.stdin.write(json.dumps({"cmd": "anchor"}) + "\n"); p.stdin.flush()
        a = getline(30); print("[T] anchor:", (a or "TIMEOUT")[:200], flush=True)
        p.stdin.write(json.dumps({"cmd": "challenge"}) + "\n"); p.stdin.flush()
        c = getline(60); print("[T] challenge:", (c or "TIMEOUT")[:400], flush=True)
p.stdin.write(json.dumps({"cmd": "quit"}) + "\n"); p.stdin.flush()
time.sleep(2)
p.kill()
err = p.stderr.read()
print("[T] STDERR tail:", err[-1500:], flush=True)
print("[T] rc", p.returncode)
