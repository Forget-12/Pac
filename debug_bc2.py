import subprocess, os, sys, time, select
P='http://acbcb24e410dbeb9-geo-fr-sess-bcf4-life-7200:8654fd49a819de6a@gate-eu.vaultproxies.com:80'
here=os.getcwd()
cmd=["proot-distro","login","ubuntu","--","bash","-c",
f"cd {here} && export DISPLAY=:99 && export CF_PAC=1 && export CF_PROXY='{P}' && export CF_WAIT=120 && node browser_claim.js sf-noproxy-state.json"]
p=subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
t0=time.time()
buf_iter=iter(p.stderr.readline, '')
while time.time()-t0 < 60:
    r,_,_=select.select([p.stdout,p.stderr],[],[],1.0)
    for f in r:
        line=f.readline()
        if line: print(("STDOUT:" if f is p.stdout else "STDERR:")+line, end="", flush=True)
print("\n[debug] inspect saved page instead...")
p.kill()
