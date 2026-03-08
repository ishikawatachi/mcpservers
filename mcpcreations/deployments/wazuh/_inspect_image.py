#!/usr/bin/env python3
"""Read opensearch.yml from wazuh-indexer image and inspect manager structure."""
import json, subprocess, ssl, time, urllib.request, urllib.error

def ks(a):
    return subprocess.run(
        ["security","find-generic-password","-s","portainer-mcp","-a",a,"-w"],
        capture_output=True, text=True).stdout.strip()
def ssl_ctx():
    c = ssl.create_default_context(); c.check_hostname = False; c.verify_mode = ssl.CERT_NONE; return c
def get(base, tok, path, timeout=20):
    r = urllib.request.Request(f"{base}/api/{path}", headers={"X-API-Key": tok})
    with urllib.request.urlopen(r, context=ssl_ctx(), timeout=timeout) as resp:
        return json.loads(resp.read())
def post(base, tok, path, body, timeout=30):
    data = json.dumps(body).encode()
    r = urllib.request.Request(f"{base}/api/{path}", data=data,
        headers={"X-API-Key": tok, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(r, context=ssl_ctx(), timeout=timeout) as resp:
        raw = resp.read(); return json.loads(raw) if raw.strip() else {}
def docker_del(base, tok, ep, path):
    r = urllib.request.Request(f"{base}/api/endpoints/{ep}/docker/{path}",
        headers={"X-API-Key": tok}, method="DELETE")
    try:
        with urllib.request.urlopen(r, context=ssl_ctx(), timeout=10) as resp: resp.read()
    except urllib.error.HTTPError as e:
        if e.code not in (404, 409): raise
def run_and_log(base, tok, ep, image, name, cmd, timeout=20):
    docker_del(base, tok, ep, f"containers/{name}?force=true")
    body = {"Image": image, "Entrypoint": ["/bin/sh","-c"], "Cmd": [cmd], "User": "root",
            "HostConfig": {"AutoRemove": False}}
    r = post(base, tok, f"endpoints/{ep}/docker/containers/create?name={name}", body)
    cid = r["Id"]
    req = urllib.request.Request(f"{base}/api/endpoints/{ep}/docker/containers/{cid}/start",
        data=b"{}", headers={"X-API-Key": tok, "Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req, context=ssl_ctx(), timeout=15) as resp: resp.read()
    time.sleep(timeout)
    lr = urllib.request.Request(
        f"{base}/api/endpoints/{ep}/docker/containers/{cid}/logs?stdout=true&stderr=true&tail=100",
        headers={"X-API-Key": tok})
    with urllib.request.urlopen(lr, context=ssl_ctx(), timeout=10) as resp:
        logs = resp.read().decode(errors="replace")
    docker_del(base, tok, ep, f"containers/{cid}?force=true")
    return logs

base = ks("portainer-url"); tok = ks("portainer-token"); EP = 2

print("=" * 70)
print("1. wazuh-indexer opensearch.yml (cert paths)")
print("=" * 70)
logs = run_and_log(base, tok, EP,
    "wazuh/wazuh-indexer:4.9.2", "wazuh-inspect-idx",
    "echo '=YML='; cat /usr/share/wazuh-indexer/config/opensearch.yml 2>/dev/null || "
    "cat /etc/wazuh-indexer/opensearch.yml 2>/dev/null && "
    "echo '=CERTS_DIR='; ls /etc/wazuh-indexer/certs/ 2>/dev/null || echo 'no /etc/wazuh-indexer/certs' && "
    "echo '=JAVAOPT_FILES='; find /usr/share/wazuh-indexer/config -name '*.yml' 2>/dev/null | head -10",
    timeout=8)
print(''.join(ch for l in logs.splitlines() for ch in (l+'\n') if ch>=' ' or ch=='\n'))

print("=" * 70)
print("2. wazuh-manager /var/ossec top-level + API config location")
print("=" * 70)
logs = run_and_log(base, tok, EP,
    "wazuh/wazuh-manager:4.9.2", "wazuh-inspect-mgr",
    "echo '=OSSEC_TOP='; ls /var/ossec/ && "
    "echo '=OSSEC_ETC='; ls /var/ossec/etc/ 2>/dev/null | head -10 && "
    "echo '=API_CFG='; cat /var/ossec/api/configuration/admin.json 2>/dev/null | head -5 && "
    "echo '=MGR_SSL_ENV='; printenv | grep -i ssl | head -5 && "
    "echo '=FILEBEAT='; ls /etc/filebeat/ 2>/dev/null | head -5",
    timeout=8)
print(''.join(ch for l in logs.splitlines() for ch in (l+'\n') if ch>=' ' or ch=='\n'))
