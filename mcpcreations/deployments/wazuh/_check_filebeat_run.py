#!/usr/bin/env python3
"""Check the Filebeat run script, test filebeat config, get full logs."""
import time, json, ssl, struct, subprocess, urllib.request

EP = 2
def ks(a): return subprocess.run(["security","find-generic-password","-s","portainer-mcp","-a",a,"-w"],capture_output=True,text=True).stdout.strip()
def ctx(): c=ssl.create_default_context(); c.check_hostname=False; c.verify_mode=ssl.CERT_NONE; return c
def docker(base,tok,method,path,body=None,timeout=30):
    data=json.dumps(body).encode() if body is not None else (b"{}" if method in ("POST","PUT") else None)
    hdrs={"X-API-Key":tok}
    if data: hdrs["Content-Type"]="application/json"
    r=urllib.request.Request(f"{base}/api/endpoints/{EP}/docker/{path}",data=data,headers=hdrs,method=method)
    with urllib.request.urlopen(r,context=ctx(),timeout=timeout) as resp: raw=resp.read(); return json.loads(raw) if raw.strip() else {}
def stream(raw):
    i=0;parts=[]
    while i+8<=len(raw):
        sz=struct.unpack(">I",raw[i+4:i+8])[0]; i+=8
        if i+sz<=len(raw): parts.append(raw[i:i+sz].decode("utf-8","replace"))
        i+=sz
    return "".join(parts)
def exec_in(base,tok,cid,cmd,timeout=30):
    er=docker(base,tok,"POST",f"containers/{cid}/exec",{"AttachStdout":True,"AttachStderr":True,"Tty":False,"Cmd":["/bin/sh","-c",cmd]})
    r=urllib.request.Request(f"{base}/api/endpoints/{EP}/docker/exec/{er['Id']}/start",data=json.dumps({"Detach":False,"Tty":False}).encode(),headers={"X-API-Key":tok,"Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(r,context=ctx(),timeout=timeout) as resp: return stream(resp.read())

base=ks("portainer-url"); tok=ks("portainer-token")

def get_mgr():
    cs=docker(base,tok,"GET","containers/json?all=true")
    return next((c for c in cs if "wazuh-manager" in ",".join(c.get("Names",[])) and c["State"]=="running"),None)

for i in range(15):
    mgr=get_mgr()
    if mgr: break
    print(f"Waiting {i+1}..."); time.sleep(3)
if not mgr: print("Manager never came up"); exit(1)
cid=mgr["Id"]

# 1. Read the Filebeat run script
print("=" * 60)
print("1. /etc/services.d/filebeat/run (Filebeat startup)")
print("=" * 60)
out=exec_in(base,tok,cid,"cat /etc/services.d/filebeat/run 2>&1",timeout=10)
print(out)

# 2. Read the Filebeat finish script
print("=" * 60)
print("2. /etc/services.d/filebeat/finish")
print("=" * 60)
out=exec_in(base,tok,cid,"cat /etc/services.d/filebeat/finish 2>&1",timeout=10)
print(out)

# 3. Show current filebeat.yml after sed (what Filebeat actually reads)
print("=" * 60)
print("3. Current /etc/filebeat/filebeat.yml content")
print("=" * 60)
out=exec_in(base,tok,cid,"cat /etc/filebeat/filebeat.yml 2>&1",timeout=10)
print(out)

# 4. Test filebeat config
print("=" * 60)
print("4. Test filebeat config (filebeat test config)")
print("=" * 60)
out=exec_in(base,tok,cid,"/usr/bin/filebeat test config -c /etc/filebeat/filebeat.yml 2>&1",timeout=30)
print(out)

# 5. Get full recent logs (look for Filebeat crash message)
print("=" * 60)
print("5. Recent container logs (all)")
print("=" * 60)
r=urllib.request.Request(f"{base}/api/endpoints/{EP}/docker/containers/{cid}/logs?stdout=true&stderr=true&tail=100",headers={"X-API-Key":tok})
with urllib.request.urlopen(r,ctx(),15) as resp: logs=stream(resp.read())
for line in logs.splitlines():
    if any(kw in line.lower() for kw in ["filebeat","error","exiting","fatal","exit"]):
        print(line)
print("---END (filtered)---")
