#!/usr/bin/env bash
# mcpcreations/tests/run_tests.sh
# ══════════════════════════════════════════════════════════════════════════════
# Master test runner for mcpcreations scripts.
#
# Usage:
#   bash tests/run_tests.sh [before|after|all]
#
#   before  Run "before" tests (baseline, before applying any fixes)
#   after   Run "after"  tests (validate everything was applied correctly)
#   all     Run after-phase for all suites (default if no argument)
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

PHASE="${1:-all}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PYTHON="${REPO_ROOT}/../grafanamcp/.venv/bin/python3"

# Fall back to system python3 if venv doesn't exist
if [[ ! -x "${VENV_PYTHON}" ]]; then
  VENV_PYTHON="python3"
fi

GREEN='\033[92m'; RED='\033[91m'; YELLOW='\033[93m'; RESET='\033[0m'

pass=0; fail=0

run_suite() {
  local label="$1"; local script="$2"; local phase_arg="$3"
  echo ""
  echo -e "${YELLOW}──────────────────────────────────────────${RESET}"
  echo -e "${YELLOW}  Suite: ${label} (${phase_arg})${RESET}"
  echo -e "${YELLOW}──────────────────────────────────────────${RESET}"

  if "${VENV_PYTHON}" "${REPO_ROOT}/tests/${script}" --phase "${phase_arg}"; then
    pass=$((pass + 1))
    echo -e "  ${GREEN}SUITE PASSED${RESET}"
  else
    fail=$((fail + 1))
    echo -e "  ${RED}SUITE FAILED${RESET}"
  fi
}

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  mcpcreations — Master Test Runner                  ║"
echo "║  Phase: ${PHASE}$(printf '%*s' $((44 - ${#PHASE})) '')║"
echo "╚══════════════════════════════════════════════════════╝"

case "${PHASE}" in
  before)
    run_suite "Proxmox Alert Fixes"   "test_proxmox_alerts.py" "before"
    run_suite "Wazuh Integration"     "test_wazuh.py"          "before"
    ;;
  after|all)
    run_suite "Proxmox Alert Fixes"   "test_proxmox_alerts.py" "after"
    run_suite "Wazuh Integration"     "test_wazuh.py"          "after"
    ;;
  *)
    echo -e "${RED}Unknown phase: ${PHASE}. Use before|after|all${RESET}"
    exit 1
    ;;
esac

echo ""
echo "══════════════════════════════════════════"
echo "  Total suites: $((pass + fail))  Passed: ${pass}  Failed: ${fail}"
echo "══════════════════════════════════════════"

[[ $fail -eq 0 ]] && exit 0 || exit 1
