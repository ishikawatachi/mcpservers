#!/usr/bin/env python3
"""Quick status check: verify data_tmp filebeat.yml and recent logs."""
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

cs=docker(base,tok,"GET","containers/json?all=true")
mgr_c=next((c for c in cs if "wazuh-manager" in ",".join(c.get("Names",[]))),None)
detail=docker(base,tok,"GET",f"containers/{cid}/json")
print(f"Manager: {cid[:12]}  restarts={detail.get('RestartCount')}  status={mgr_c.get('Status')}")

out=exec_in(base,tok,cid,"ls -la /var/ossec/data_tmp/permanent/etc/filebeat/ 2>&1; echo ---; ls -la /etc/filebeat/ 2>&1",timeout=10)
print(out)

r=urllib.request.Request(f"{base}/api/endpoints/{EP}/docker/containers/{cid}/logs?stdout=true&stderr=true&tail=30",headers={"X-API-Key":tok})
with urllib.request.urlopen(r,context=ctx(),timeout=15) as resp: logs=stream(resp.read())
print("Recent logs:")
for line in logs.splitlines(): print(line)
