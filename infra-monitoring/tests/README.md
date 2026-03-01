# infra-monitoring — Test Suites

## Folder Layout

```
tests/
├── README.md            ← this file
├── run_all_tests.sh     ← master runner (runs both suites)
├── backend/
│   └── backend_test.py  ← Prometheus / metric validation
└── frontend/
    └── frontend_test.py ← Grafana dashboard / alert validation
```

---

## Backend Tests (`backend/backend_test.py`)

Tests what **Prometheus** sees — whether metrics are scraped, healthy, and correct.

| Category | What is checked |
|----------|----------------|
| Targets  | All configured scrape targets are UP |
| Metrics  | Key metric families are present with non-empty results |
| Queries  | Every PromQL expression used in dashboard panels returns data |
| Alerts   | All alert rule groups load without error |

**Run:**
```bash
python3 tests/backend/backend_test.py
```

**Known-pending failures** (expected until infra is fixed):
- `pve_*` metrics — pve_exporter is crashing (volume mount typo in Portainer; see Fix section below)
- `snmp_*` metrics — SNMP module `synology` not in snmp.yml yet (see Fix section)
- `speedtest_*` metrics — speedtest_exporter not listening on port 9798

---

## Frontend Tests (`frontend/frontend_test.py`)

Tests what **Grafana** exposes — dashboard integrity, panel data, alert states, notification channels.

| Category | What is checked |
|----------|----------------|
| Dashboards | All dashboards exist and have expected panel count |
| Panels   | Each panel's PromQL target executes without error |
| Alerts   | Alert rules are loaded; firing alerts are expected |
| Notifications | Contact points / notification policies exist |
| Health   | Grafana `/api/health` reports OK |

**Run:**
```bash
python3 tests/frontend/frontend_test.py
```

---

## Master Runner

Runs both suites in sequence and prints a combined summary:

```bash
bash tests/run_all_tests.sh
```

---

## Current Status

| Suite | Pass | Total | % |
|-------|------|-------|---|
| Backend | 56 | 62 | 90 % |
| Frontend | TBD | TBD | — |

Six backend failures are "known-pending" (not code bugs — infra fixes needed).

---

## Outstanding Infra Fixes

### 1 — pve_exporter volume typo (Portainer)

**Symptom:** pve_exporter container restarts every 30 s with:
```
FileNotFoundError: [Errno 2] No such file or directory: '/etc/pve.yml'
```

**Root cause:** Volume binding in Portainer stack has a typo: `:pvc.yml` instead of `:pve.yml`

**Fix (in Portainer web UI):**
1. Open stack `monitoring` → Edit
2. Find the `pve-exporter` service volumes section
3. Change: `/volume1/docker/grafana/pve.yml:/etc/pvc.yml:ro`
4. To:     `/volume1/docker/grafana/pve.yml:/etc/pve.yml:ro`
5. Deploy the stack

### 2 — SNMP missing Synology module

**Symptom:** Prometheus gets HTTP 400 for `module=synology` because that module is not defined in `snmp.yml`.

**Fix:**
```bash
# From this repo:
cp infra-monitoring/snmp/synology-snmp.yml /volume1/docker/grafana/snmp.yml
docker restart SNMP_Exporter

# Verify:
curl "http://localhost:9116/snmp?module=synology&target=localhost" | head -5
```

### 3 — speedtest_exporter port not bound

**Symptom:** Container runs but nothing listens on port 9798.

**Workaround:** Image `ghcr.io/aaronmwelborn/speedtest_exporter:latest` may need `SPEEDTEST_PORT` env var or use a port-mapping in the Portainer stack (`9798:9798`).

---

## Dependencies

```
requests>=2.28
```

Both test scripts are self-contained — no extra test framework needed.
