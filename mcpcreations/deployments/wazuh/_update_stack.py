#!/usr/bin/env python3
"""Update existing wazuh Portainer stack with new compose content."""
import json, subprocess, ssl, urllib.request, urllib.error

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
def put(base, tok, path, body, timeout=None):
    data = json.dumps(body).encode()
    r = urllib.request.Request(f"{base}/api/{path}", data=data,
        headers={"X-API-Key": tok, "Content-Type": "application/json"}, method="PUT")
    with urllib.request.urlopen(r, context=ssl_ctx(), timeout=timeout) as resp:
        raw = resp.read(); return json.loads(raw) if raw.strip() else {}

base = ks("portainer-url"); tok = ks("portainer-token"); EP = 2

INDEXER_PASSWORD  = "Wazuh!!Wazuh!!"
DASHBOARD_PASSWORD = "zvpvy.w5U2B3Ej6rPnCVCT.G3I1no.KN"
HOSTNAME          = "wazuh.local.defaultvaluation.com"

compose = open("/Users/nicolas/Library/CloudStorage/ProtonDrive-serialinsert@proton.me/git/mcp/mcpcreations/deployments/wazuh/docker-compose.yml").read()
env = [
    {"name": "WAZUH_HOSTNAME",     "value": HOSTNAME},
    {"name": "INDEXER_PASSWORD",   "value": INDEXER_PASSWORD},
    {"name": "DASHBOARD_PASSWORD", "value": DASHBOARD_PASSWORD},
]

# Find the wazuh stack
stacks = get(base, tok, "stacks")
wazuh = next((s for s in stacks if s["Name"] == "wazuh"), None)
if not wazuh:
    print("ERROR: stack 'wazuh' not found")
    exit(1)

stack_id = wazuh["Id"]
ep_id = wazuh.get("EndpointId", EP)
print(f"Updating stack 'wazuh' (id={stack_id}, endpointId={ep_id})...")

try:
    result = put(base, tok,
                 f"stacks/{stack_id}?endpointId={ep_id}",
                 {"stackFileContent": compose, "env": env, "prune": True},
                 timeout=None)
    print(f"Stack updated: id={result.get('Id', stack_id)}")
    print(f"\nWazuh dashboard will be at: https://{HOSTNAME}")
    print(f"Login: admin / {DASHBOARD_PASSWORD}")
    print("\nWait 5-10 minutes for OpenSearch to fully initialize.")
except urllib.error.HTTPError as e:
    body = e.read().decode(errors="replace")
    print(f"Update failed: HTTP {e.code} — {body[:400]}")
