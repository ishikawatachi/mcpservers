#!/usr/bin/env python3
"""Check Wazuh manager filebeat setup and init scripts."""
import json, ssl, struct, subprocess, urllib.request

EP = 2

def ks(a):
    return subprocess.run(
        ["security", "find-generic-password", "-s", "portainer-mcp", "-a", a, "-w"],
        capture_output=True, text=True).stdout.strip()

def ctx():
    c = ssl.create_default_context(); c.check_hostname = False; c.verify_mode = ssl.CERT_NONE; return c

def docker(base, tok, method, path, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else (b"{}" if method in ("POST","PUT") else None)
    hdrs = {"X-API-Key": tok}
    if data: hdrs["Content-Type"] = "application/json"
    r = urllib.request.Request(f"{base}/api/endpoints/{EP}/docker/{path}", data=data, headers=hdrs, method=method)
    with urllib.request.urlopen(r, context=ctx(), timeout=timeout) as resp:
        raw = resp.read(); return json.loads(raw) if raw.strip() else {}

def stream(raw):
    i = 0; parts = []
    while i + 8 <= len(raw):
        sz = struct.unpack(">I", raw[i+4:i+8])[0]; i += 8
        if i + sz <= len(raw): parts.append(raw[i:i+sz].decode("utf-8","replace"))
        i += sz
    return "".join(parts)

def exec_in(base, tok, cid, cmd, timeout=30):
    er = docker(base, tok, "POST", f"containers/{cid}/exec", {
        "AttachStdout": True, "AttachStderr": True, "Tty": False,
        "Cmd": ["/bin/sh", "-c", cmd]
    })
    r = urllib.request.Request(
        f"{base}/api/endpoints/{EP}/docker/exec/{er['Id']}/start",
        data=json.dumps({"Detach": False, "Tty": False}).encode(),
        headers={"X-API-Key": tok, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(r, context=ctx(), timeout=timeout) as resp:
        return stream(resp.read())

base = ks("portainer-url"); tok = ks("portainer-token")
cs = docker(base, tok, "GET", "containers/json?all=true")
mgr = next((c for c in cs if "wazuh-manager" in ",".join(c.get("Names",[])) and c["State"] == "running"), None)
if not mgr:
    print("ERROR: wazuh-manager not running"); exit(1)
cid = mgr["Id"]
print(f"Manager: {cid[:12]}\n")

# ── 1. Check /etc/filebeat directory ─────────────────────────────────────────
print("=" * 60)
print("1. /etc/filebeat directory contents")
print("=" * 60)
out = exec_in(base, tok, cid,
    "ls -la /etc/filebeat/ 2>&1 || echo 'DIRECTORY NOT FOUND'",
    timeout=10)
print(out)

# ── 2. Check what filebeat template/config exists in image ───────────────────
print("=" * 60)
print("2. Find any filebeat configurations in the image")
print("=" * 60)
out = exec_in(base, tok, cid,
    "find / -name 'filebeat*' -not -path '*/proc/*' -not -path '*/sys/*' 2>/dev/null | head -30",
    timeout=20)
print(out)

# ── 3. Check the cont-init.d scripts ─────────────────────────────────────────
print("=" * 60)
print("3. Container init scripts (cont-init.d)")
print("=" * 60)
out = exec_in(base, tok, cid,
    "ls -la /var/run/s6/etc/cont-init.d/ 2>/dev/null || ls -la /etc/cont-init.d/ 2>/dev/null || "
    "find / -name 'cont-init.d' -not -path '*/proc/*' 2>/dev/null | head -5",
    timeout=15)
print(out)

# ── 4. Read the config-filebeat init script ───────────────────────────────────
print("=" * 60)
print("4. Content of 1-config-filebeat init script")
print("=" * 60)
out = exec_in(base, tok, cid,
    "cat /var/run/s6/etc/cont-init.d/1-config-filebeat 2>/dev/null || "
    "cat /etc/cont-init.d/1-config-filebeat 2>/dev/null || "
    "find / -name '1-config-filebeat' 2>/dev/null -exec cat {} \\;",
    timeout=15)
print(out if out.strip() else "Script not found")

# ── 5. Check if there's a filebeat.yml template somewhere ────────────────────
print("=" * 60)
print("5. Filebeat template locations")
print("=" * 60)
out = exec_in(base, tok, cid,
    "find / -name 'filebeat.yml*' -not -path '*/proc/*' -not -path '*/sys/*' 2>/dev/null | head -10; "
    "echo '---'; "
    "find / -name 'wazuh-template*' -not -path '*/proc/*' -not -path '*/sys/*' 2>/dev/null | head -10",
    timeout=20)
print(out)

# ── 6. Check services.d for filebeat service ─────────────────────────────────
print("=" * 60)
print("6. s6 services directory (services.d)")
print("=" * 60)
out = exec_in(base, tok, cid,
    "find / -name 'services.d' -not -path '*/proc/*' 2>/dev/null -exec ls -la {} \\; 2>/dev/null | head -20; "
    "echo '---'; "
    "find / -path '*/services.d/filebeat*' -not -path '*/proc/*' 2>/dev/null | head -5",
    timeout=15)
print(out)
