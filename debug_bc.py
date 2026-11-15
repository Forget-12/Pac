import subprocess, os, sys, time, select
P='http://acbcb24e410dbeb9-geo-fr-sess-bcf3-life-7200:8654fd49a819de6a@gate-eu.vaultproxies.com:80'
here=os.getcwd()
cmd=["proot-distro","login","ubuntu","--","bash","-c",
f"cd {here} && export DISPLAY=:99 && export CF_PAC=1 && export CF_PROXY='{P}' && export CF_WAIT=200 && node browser_claim.js sf-noproxy-state.json"]
p=subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
t0=time.time()
buf=""
import re
while time.time()-t0 < 240:
    r,_,_=select.select([p.stdout,p.stderr],[],[],1.0)
    if not r:
        time.sleep(0.2); continue
    for f in r:
        line=f.readline()
        if f is p.stdout:
            print("STDOUT:"+line, end="", flush=True)
            try:
                import json; d=json.loads(line)
                if d.get("ready"):
                    print("READY daily/htmlLen:", d.get("htmlLen"), "csrf:", bool((d.get("fields") or {}).get("csrf")) or None, flush=True)
                    sys.exit(0)
            except Exception: pass
        else:
            print("STDERR:"+line, end="", flush=True)
p.kill()
print("[debug] timeout reached, killing")
