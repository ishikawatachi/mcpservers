#!/usr/bin/env bash
# =============================================================================
# setup_keychain.sh — Store Synology MCP credentials in macOS Keychain
# =============================================================================
# Usage:
#   chmod +x scripts/setup_keychain.sh
#   ./scripts/setup_keychain.sh
#
# Alternatively, provide values via env vars to skip interactive prompts:
#   SYNOLOGY_URL=https://nas.local:5001 \
#   SYNOLOGY_USER=admin \
#   SYNOLOGY_PASSWORD='s3cr3t' \
#   ./scripts/setup_keychain.sh
#
# Authentication uses SYNO.API.Auth session login (no Personal Access Token needed).
# The credentials are stored in the macOS Keychain and never written to disk.
# =============================================================================

set -euo pipefail

SERVICE="synology-mcp"

store() {
    local account="$1" value="$2"
    /usr/bin/security add-generic-password \
        -s "$SERVICE" -a "$account" -w "$value" -U
    echo "  ✓ Stored '$account' in Keychain (service: $SERVICE)"
}

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║    Synology MCP — Keychain Setup         ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# --- Synology URL ---
if [[ -n "${SYNOLOGY_URL:-}" ]]; then
    NAS_URL="$SYNOLOGY_URL"
else
    read -rp "Synology DSM URL (e.g. https://nas.local:5001): " NAS_URL
fi

# --- Username ---
if [[ -n "${SYNOLOGY_USER:-}" ]]; then
    NAS_USER="$SYNOLOGY_USER"
else
    echo ""
    read -rp "DSM username (e.g. admin): " NAS_USER
fi

# --- Password ---
if [[ -n "${SYNOLOGY_PASSWORD:-}" ]]; then
    NAS_PASS="$SYNOLOGY_PASSWORD"
else
    echo ""
    read -rsp "DSM password (input hidden): " NAS_PASS
    echo ""
fi

echo ""
echo "Storing credentials…"
store "synology-url"      "$NAS_URL"
store "synology-username" "$NAS_USER"
store "synology-password" "$NAS_PASS"

echo ""
echo "Done! To verify:"
echo "  security find-generic-password -s '$SERVICE' -a 'synology-url' -w"
echo "  security find-generic-password -s '$SERVICE' -a 'synology-username' -w"
echo ""
echo "Note: Password is intentionally not shown. To remove all entries:"
echo "  security delete-generic-password -s '$SERVICE' -a 'synology-url'"
echo "  security delete-generic-password -s '$SERVICE' -a 'synology-username'"
echo "  security delete-generic-password -s '$SERVICE' -a 'synology-password'"
