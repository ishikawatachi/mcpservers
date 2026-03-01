#!/usr/bin/env python3
"""Check actual pve metric labels from Prometheus via Grafana proxy."""
import urllib.request, urllib.parse, json, ssl, os

TOKEN = os.environ.get("GRAFANA_TOKEN", "")
BASE  = "https://grafana.local.defaultvaluation.com/api/datasources/proxy/uid/ceb67eiok1qf4d"

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def query(promql):
    url = f"{BASE}/api/v1/query?" + urllib.parse.urlencode({"query": promql})
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
            return json.load(r)
    except Exception as e:
        return {"error": str(e)}

metrics = [
    "pve_up", "pve_cpu_usage_ratio", "pve_memory_size_bytes",
    "pve_memory_usage_bytes", "pve_uptime_seconds", "pve_guest_info",
    "pve_disk_size_bytes", "pve_disk_usage_bytes", "pve_network_receive_bytes",
    "pve_network_transmit_bytes", "pve_disk_read_bytes", "pve_disk_write_bytes",
    "pve_not_backed_up_total", "pve_node_info", "pve_subscription_status",
]

for m in metrics:
    print(f"\n{'='*60}")
    print(f"METRIC: {m}")
    d = query(m)
    if "error" in d:
        print(f"  ERROR: {d['error']}")
        continue
    results = d.get("data", {}).get("result", [])
    print(f"  Count: {len(results)}")
    for r in results[:4]:
        labels = {k: v for k, v in r["metric"].items() if k not in ["__name__", "job"]}
        print(f"  labels={labels}  value={r['value'][1]}")
