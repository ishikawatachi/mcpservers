#!/usr/bin/env python3
"""
Fix the Filebeat crash: change output.opensearch → output.elasticsearch
The standard Filebeat binary only supports output.elasticsearch (not opensearch).
Writes the corrected filebeat.yml to /etc/filebeat/ (persists in container layer)
AND to data_tmp (for fresh container recreation).
"""
import time, json, ssl, struct, subprocess, urllib.request, base64

EP = 2
INDEXER_PASS = "Wazuh!!Wazuh!!"

# FIXED filebeat.yml: output.elasticsearch (not opensearch)
FILEBEAT_CONTENT = "\n".join([
    "# Wazuh - Filebeat configuration file",
    "output.elasticsearch:",
    "  hosts: ['https://wazuh.indexer:9200']",
    "  protocol: https",
    "  username: 'admin'",
    f"  password: '{INDEXER_PASS}'",
    "  ssl.certificate_authorities: ['/etc/ssl/root-ca.pem']",
    "  ssl.certificate: '/etc/ssl/wazuh.manager.pem'",
    "  ssl.key: '/etc/ssl/wazuh.manager-key.pem'",
    "  ssl.verification_mode: 'none'",
    "",
    "filebeat.modules:",
    "  - module: wazuh",
    "    alerts:",
    "      enabled: true",
    "    archives:",
    "      enabled: false",
    "",
    "# Templates managed by indexer init; skip Filebeat template setup",
    "setup.template.json.enabled: false",
    "setup.template.enabled: false",
    "setup.ilm.enabled: false",
])

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

print("Waiting for manager container...")
for i in range(15):
    mgr=get_mgr()
    if mgr: break
    print(f"  Attempt {i+1}: waiting 3s..."); time.sleep(3)
if not mgr: print("FAILED: manager not available"); exit(1)
cid=mgr["Id"]
print(f"Manager: {cid[:12]}\n")

# Encode filebeat.yml as base64 to avoid shell quoting issues
content_b64 = base64.b64encode(FILEBEAT_CONTENT.encode()).decode()
write_cmd = (
    f"mkdir -p /var/ossec/data_tmp/permanent/etc/filebeat /etc/filebeat && "
    f"echo '{content_b64}' | base64 -d > /etc/filebeat/filebeat.yml && "
    f"echo '{content_b64}' | base64 -d > /var/ossec/data_tmp/permanent/etc/filebeat/filebeat.yml && "
    f"echo 'Write OK' && "
    f"head -3 /etc/filebeat/filebeat.yml"
)

print("Writing fixed filebeat.yml (output.elasticsearch)...")
mgr=get_mgr()
if mgr:
    out=exec_in(base,tok,mgr["Id"],write_cmd,timeout=15)
    print(out)

print("Verifying filebeat config test...")
time.sleep(2)
mgr=get_mgr()
if mgr:
    out=exec_in(base,tok,mgr["Id"],
        "/usr/bin/filebeat test config -c /etc/filebeat/filebeat.yml 2>&1",
        timeout=20)
    print(out)

print("Waiting 45s to check if crash loop stops...")
time.sleep(45)

cs=docker(base,tok,"GET","containers/json?all=true")
mgr_c=next((c for c in cs if "wazuh-manager" in ",".join(c.get("Names",[]))),None)
if mgr_c:
    detail=docker(base,tok,"GET",f"containers/{mgr_c['Id']}/json")
    restarts=detail.get("RestartCount",0)
    status=mgr_c.get("Status","")
    state=mgr_c.get("State","")
    print(f"\nFinal status: restarts={restarts}, state={state}, status={status}")
    if state=="running":
        started=detail.get("State",{}).get("StartedAt","?")
        health=detail.get("State",{}).get("Health",{}).get("Status","?")
        print(f"  StartedAt: {started}")
        print(f"  Health: {health}")
        if restarts <= 155:
            print("  → Crash loop appears STOPPED (restart count stable)")
        else:
            print(f"  → Still crashing (>5 more restarts in 45s)")
