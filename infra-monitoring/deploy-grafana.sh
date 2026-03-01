#!/usr/bin/env bash
# deploy-grafana.sh — Push dashboards and alerting to Grafana
# Run from the infra-monitoring directory

set -euo pipefail

GRAFANA_URL="https://grafana.local.defaultvaluation.com"
# Export GRAFANA_TOKEN and DISCORD_WEBHOOK before running this script
TOKEN="${GRAFANA_TOKEN:?GRAFANA_TOKEN env var not set}"
DISCORD_WEBHOOK="${DISCORD_WEBHOOK:?DISCORD_WEBHOOK env var not set}"

HEADERS=(-H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json")

echo "=== 1. Create Infrastructure folder ==="
curl -s -X POST "$GRAFANA_URL/api/folders" \
  "${HEADERS[@]}" \
  -d '{"uid":"infrastructure","title":"Infrastructure"}' | python3 -m json.tool || true

echo ""
echo "=== 2. Delete old incomplete Proxmox dashboard ==="
curl -s -X DELETE "$GRAFANA_URL/api/dashboards/uid/0cb0b22d-a686-4728-bc95-c765f4c79d3b" \
  "${HEADERS[@]}" | python3 -m json.tool || true

echo ""
echo "=== 3. Delete old MCP Dry-Run dashboards ==="
curl -s -X DELETE "$GRAFANA_URL/api/dashboards/uid/49f3567e-7d25-44b9-ba80-2de53b484519" \
  "${HEADERS[@]}" | python3 -m json.tool || true
curl -s -X DELETE "$GRAFANA_URL/api/dashboards/uid/6afc3916-150c-456c-ba2b-a1bf98857102" \
  "${HEADERS[@]}" | python3 -m json.tool || true

echo ""
echo "=== 4. Create Proxmox dashboard ==="
PROXMOX_DASH=$(cat grafana/dashboards/proxmox-dashboard.json)
PROXMOX_PAYLOAD=$(python3 -c "
import json, sys
dash = json.loads(sys.stdin.read())
payload = {
    'dashboard': dash,
    'folderUid': 'infrastructure',
    'message': 'Full Proxmox dashboard with pve-exporter metrics',
    'overwrite': True
}
print(json.dumps(payload))
" <<< "$PROXMOX_DASH")
curl -s -X POST "$GRAFANA_URL/api/dashboards/db" \
  "${HEADERS[@]}" \
  -d "$PROXMOX_PAYLOAD" | python3 -m json.tool

echo ""
echo "=== 5. Create Portainer dashboard ==="
PORTAINER_DASH=$(cat grafana/dashboards/portainer-dashboard.json)
PORTAINER_PAYLOAD=$(python3 -c "
import json, sys
dash = json.loads(sys.stdin.read())
payload = {
    'dashboard': dash,
    'folderUid': 'infrastructure',
    'message': 'Portainer container overview via cAdvisor',
    'overwrite': True
}
print(json.dumps(payload))
" <<< "$PORTAINER_DASH")
curl -s -X POST "$GRAFANA_URL/api/dashboards/db" \
  "${HEADERS[@]}" \
  -d "$PORTAINER_PAYLOAD" | python3 -m json.tool

echo ""
echo "=== 6. Create Discord contact point ==="
CONTACT_POINT=$(python3 -c "
import json
cp = {
    'name': 'Discord',
    'type': 'discord',
    'settings': {
        'url': '$DISCORD_WEBHOOK',
        'message': '{{ template \"default.message\" . }}'
    },
    'disableResolveMessage': False
}
print(json.dumps(cp))
")
curl -s -X POST "$GRAFANA_URL/api/v1/provisioning/contact-points" \
  "${HEADERS[@]}" \
  -d "$CONTACT_POINT" | python3 -m json.tool || true

echo ""
echo "=== 7. Update default notification policy → Discord ==="
POLICY=$(python3 -c "
import json
policy = {
    'receiver': 'Discord',
    'group_by': ['alertname', 'instance', 'job'],
    'group_wait': '30s',
    'group_interval': '5m',
    'repeat_interval': '4h',
    'routes': []
}
print(json.dumps(policy))
")
curl -s -X PUT "$GRAFANA_URL/api/v1/provisioning/policies" \
  "${HEADERS[@]}" \
  -d "$POLICY" | python3 -m json.tool || true

echo ""
echo "=== 8. Create alert rules ==="
# NOTE: Alert rules POST to /api/v1/provisioning/alert-rules
# Each rule needs a folderUID — use 'infrastructure'

# Rule: Proxmox node down
RULE_PVE_DOWN=$(python3 -c "
import json
rule = {
    'title': 'Proxmox Node Down',
    'ruleGroup': 'Proxmox',
    'folderUID': 'infrastructure',
    'noDataState': 'NoData',
    'execErrState': 'Error',
    'for': '2m',
    'labels': {'severity': 'critical', 'team': 'infra'},
    'annotations': {
        'summary': 'Proxmox node {{ \$labels.node }} is DOWN',
        'description': 'pve-exporter cannot reach the Proxmox node. Check the host at pm.local.defaultvaluation.com'
    },
    'data': [
        {
            'refId': 'A',
            'queryType': '',
            'relativeTimeRange': {'from': 300, 'to': 0},
            'datasourceUid': 'ceb67eiok1qf4d',
            'model': {
                'expr': 'pve_up{job=\"pve\"}',
                'instant': True,
                'intervalMs': 1000,
                'maxDataPoints': 43200,
                'refId': 'A'
            }
        },
        {
            'refId': 'C',
            'queryType': '',
            'relativeTimeRange': {'from': 300, 'to': 0},
            'datasourceUid': '-100',
            'model': {
                'conditions': [
                    {
                        'evaluator': {'params': [1], 'type': 'lt'},
                        'operator': {'type': 'and'},
                        'query': {'params': ['A']},
                        'reducer': {'params': [], 'type': 'last'},
                        'type': 'query'
                    }
                ],
                'datasource': {'type': '__expr__', 'uid': '-100'},
                'expression': 'A',
                'hide': False,
                'intervalMs': 1000,
                'maxDataPoints': 43200,
                'refId': 'C',
                'type': 'classic_conditions'
            }
        }
    ]
}
print(json.dumps(rule))
")
curl -s -X POST "$GRAFANA_URL/api/v1/provisioning/alert-rules" \
  "${HEADERS[@]}" \
  -d "$RULE_PVE_DOWN" | python3 -m json.tool || true

# Rule: Node memory > 90%
RULE_MEM=$(python3 -c "
import json
rule = {
    'title': 'Proxmox Node Memory High',
    'ruleGroup': 'Proxmox',
    'folderUID': 'infrastructure',
    'noDataState': 'NoData',
    'execErrState': 'Error',
    'for': '15m',
    'labels': {'severity': 'warning', 'team': 'infra'},
    'annotations': {
        'summary': 'Proxmox node {{ \$labels.node }} memory over 90%',
        'description': 'RAM usage has been above 90% for 15 minutes'
    },
    'data': [
        {
            'refId': 'A',
            'queryType': '',
            'relativeTimeRange': {'from': 300, 'to': 0},
            'datasourceUid': 'ceb67eiok1qf4d',
            'model': {
                'expr': '(1 - pve_node_mem_free_bytes{job=\"pve\"} / pve_node_mem_total_bytes{job=\"pve\"}) * 100',
                'instant': True,
                'intervalMs': 1000,
                'maxDataPoints': 43200,
                'refId': 'A'
            }
        },
        {
            'refId': 'C',
            'queryType': '',
            'relativeTimeRange': {'from': 300, 'to': 0},
            'datasourceUid': '-100',
            'model': {
                'conditions': [
                    {
                        'evaluator': {'params': [90], 'type': 'gt'},
                        'operator': {'type': 'and'},
                        'query': {'params': ['A']},
                        'reducer': {'params': [], 'type': 'last'},
                        'type': 'query'
                    }
                ],
                'datasource': {'type': '__expr__', 'uid': '-100'},
                'expression': 'A',
                'hide': False,
                'intervalMs': 1000,
                'maxDataPoints': 43200,
                'refId': 'C',
                'type': 'classic_conditions'
            }
        }
    ]
}
print(json.dumps(rule))
")
curl -s -X POST "$GRAFANA_URL/api/v1/provisioning/alert-rules" \
  "${HEADERS[@]}" \
  -d "$RULE_MEM" | python3 -m json.tool || true

# Rule: Storage > 85%
RULE_DISK=$(python3 -c "
import json
rule = {
    'title': 'Proxmox Storage Critical',
    'ruleGroup': 'Proxmox',
    'folderUID': 'infrastructure',
    'noDataState': 'NoData',
    'execErrState': 'Error',
    'for': '5m',
    'labels': {'severity': 'warning', 'team': 'infra'},
    'annotations': {
        'summary': 'Proxmox storage {{ \$labels.id }} is over 85% full',
        'description': 'A PVE storage pool is running low on space'
    },
    'data': [
        {
            'refId': 'A',
            'queryType': '',
            'relativeTimeRange': {'from': 300, 'to': 0},
            'datasourceUid': 'ceb67eiok1qf4d',
            'model': {
                'expr': '(pve_disk_size_bytes{job=\"pve\", id=~\"storage/.*\"} - pve_disk_free_bytes{job=\"pve\", id=~\"storage/.*\"}) / pve_disk_size_bytes{job=\"pve\", id=~\"storage/.*\"} * 100',
                'instant': True,
                'intervalMs': 1000,
                'maxDataPoints': 43200,
                'refId': 'A'
            }
        },
        {
            'refId': 'C',
            'queryType': '',
            'relativeTimeRange': {'from': 300, 'to': 0},
            'datasourceUid': '-100',
            'model': {
                'conditions': [
                    {
                        'evaluator': {'params': [85], 'type': 'gt'},
                        'operator': {'type': 'and'},
                        'query': {'params': ['A']},
                        'reducer': {'params': [], 'type': 'last'},
                        'type': 'query'
                    }
                ],
                'datasource': {'type': '__expr__', 'uid': '-100'},
                'expression': 'A',
                'hide': False,
                'intervalMs': 1000,
                'maxDataPoints': 43200,
                'refId': 'C',
                'type': 'classic_conditions'
            }
        }
    ]
}
print(json.dumps(rule))
")
curl -s -X POST "$GRAFANA_URL/api/v1/provisioning/alert-rules" \
  "${HEADERS[@]}" \
  -d "$RULE_DISK" | python3 -m json.tool || true

# Rule: Host CPU > 85% for 10m (via node_exporter)
RULE_CPU=$(python3 -c "
import json
rule = {
    'title': 'Host CPU Usage High',
    'ruleGroup': 'Docker Host',
    'folderUID': 'infrastructure',
    'noDataState': 'NoData',
    'execErrState': 'Error',
    'for': '10m',
    'labels': {'severity': 'warning', 'team': 'infra'},
    'annotations': {
        'summary': 'Docker host CPU over 85%',
        'description': 'Synology NAS CPU load has been above 85% for 10 minutes'
    },
    'data': [
        {
            'refId': 'A',
            'queryType': '',
            'relativeTimeRange': {'from': 300, 'to': 0},
            'datasourceUid': 'ceb67eiok1qf4d',
            'model': {
                'expr': '(1 - avg(rate(node_cpu_seconds_total{mode=\"idle\"}[2m]))) * 100',
                'instant': True,
                'intervalMs': 1000,
                'maxDataPoints': 43200,
                'refId': 'A'
            }
        },
        {
            'refId': 'C',
            'queryType': '',
            'relativeTimeRange': {'from': 300, 'to': 0},
            'datasourceUid': '-100',
            'model': {
                'conditions': [
                    {
                        'evaluator': {'params': [85], 'type': 'gt'},
                        'operator': {'type': 'and'},
                        'query': {'params': ['A']},
                        'reducer': {'params': [], 'type': 'last'},
                        'type': 'query'
                    }
                ],
                'datasource': {'type': '__expr__', 'uid': '-100'},
                'expression': 'A',
                'hide': False,
                'intervalMs': 1000,
                'maxDataPoints': 43200,
                'refId': 'C',
                'type': 'classic_conditions'
            }
        }
    ]
}
print(json.dumps(rule))
")
curl -s -X POST "$GRAFANA_URL/api/v1/provisioning/alert-rules" \
  "${HEADERS[@]}" \
  -d "$RULE_CPU" | python3 -m json.tool || true

# Rule: NAS disk > 90%
RULE_NAS_DISK=$(python3 -c "
import json
rule = {
    'title': 'NAS Disk Critical',
    'ruleGroup': 'Docker Host',
    'folderUID': 'infrastructure',
    'noDataState': 'NoData',
    'execErrState': 'Error',
    'for': '5m',
    'labels': {'severity': 'critical', 'team': 'infra'},
    'annotations': {
        'summary': 'NAS disk {{ \$labels.mountpoint }} over 90% full',
        'description': 'The NAS storage is critically low on space'
    },
    'data': [
        {
            'refId': 'A',
            'queryType': '',
            'relativeTimeRange': {'from': 300, 'to': 0},
            'datasourceUid': 'ceb67eiok1qf4d',
            'model': {
                'expr': '(1 - node_filesystem_avail_bytes{fstype!~\"tmpfs|overlay|aufs\"} / node_filesystem_size_bytes{fstype!~\"tmpfs|overlay|aufs\"}) * 100',
                'instant': True,
                'intervalMs': 1000,
                'maxDataPoints': 43200,
                'refId': 'A'
            }
        },
        {
            'refId': 'C',
            'queryType': '',
            'relativeTimeRange': {'from': 300, 'to': 0},
            'datasourceUid': '-100',
            'model': {
                'conditions': [
                    {
                        'evaluator': {'params': [90], 'type': 'gt'},
                        'operator': {'type': 'and'},
                        'query': {'params': ['A']},
                        'reducer': {'params': [], 'type': 'last'},
                        'type': 'query'
                    }
                ],
                'datasource': {'type': '__expr__', 'uid': '-100'},
                'expression': 'A',
                'hide': False,
                'intervalMs': 1000,
                'maxDataPoints': 43200,
                'refId': 'C',
                'type': 'classic_conditions'
            }
        }
    ]
}
print(json.dumps(rule))
")
curl -s -X POST "$GRAFANA_URL/api/v1/provisioning/alert-rules" \
  "${HEADERS[@]}" \
  -d "$RULE_NAS_DISK" | python3 -m json.tool || true

echo ""
echo "=== DONE ==="
echo "Check Grafana → Infrastructure folder for your dashboards"
echo "Check Alerting → Contact points for Discord"
echo "Check Alerting → Alert rules for all rules"
