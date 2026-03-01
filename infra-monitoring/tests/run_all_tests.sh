#!/usr/bin/env bash
# ============================================================
# run_all_tests.sh — Master test runner for infra-monitoring
# Runs backend (Prometheus) and frontend (Grafana) test suites
# and emits a combined summary.
# ============================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$(command -v python3)"
TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"

echo "════════════════════════════════════════════════════"
echo "  infra-monitoring test suite"
echo "  Started: $TIMESTAMP"
echo "════════════════════════════════════════════════════"

BACK_RC=0
FRONT_RC=0

# ── Backend: Prometheus / metric validation ──────────────
echo ""
echo "▶  BACKEND TESTS  (Prometheus targets, metrics, queries)"
echo "──────────────────────────────────────────────────────────"
"$PYTHON" "$SCRIPT_DIR/backend/backend_test.py"
BACK_RC=$?

# ── Frontend: Grafana dashboard / alert validation ────────
echo ""
echo "▶  FRONTEND TESTS  (Grafana dashboards, alerts, health)"
echo "──────────────────────────────────────────────────────────"
"$PYTHON" "$SCRIPT_DIR/frontend/frontend_test.py"
FRONT_RC=$?

# ── Combined result ───────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════"
echo "  COMBINED RESULT"
echo "════════════════════════════════════════════════════"
if [[ $BACK_RC -eq 0 && $FRONT_RC -eq 0 ]]; then
  echo "  ✅  ALL SUITES PASSED"
elif [[ $BACK_RC -ne 0 && $FRONT_RC -ne 0 ]]; then
  echo "  ❌  BOTH SUITES HAD FAILURES"
elif [[ $BACK_RC -ne 0 ]]; then
  echo "  ⚠️   BACKEND had failures; frontend passed"
else
  echo "  ⚠️   FRONTEND had failures; backend passed"
fi
echo "  Backend  exit code: $BACK_RC"
echo "  Frontend exit code: $FRONT_RC"
echo "════════════════════════════════════════════════════"

exit $(( BACK_RC || FRONT_RC ))
