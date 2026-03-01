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
#   SYNOLOGY_TOKEN='xxxxxxxxxx' \
#   ./scripts/setup_keychain.sh
#
# How to create a Personal Access Token (PAT) in DSM 7.2.2+:
#   1. DSM → Control Panel → Personal → Security → Account
#   2. Scroll to "Personal Access Tokens" → Add
#   3. Give it a name (e.g. "mcp-server") and confirm
#   4. Copy the token — it is shown only once!
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

# --- Personal Access Token ---
# DSM 7.2.2+: Control Panel → Personal → Security → Account → Personal Access Tokens
if [[ -n "${SYNOLOGY_TOKEN:-}" ]]; then
    NAS_TOKEN="$SYNOLOGY_TOKEN"
else
    echo ""
    echo "Personal Access Token (DSM 7.2.2+):"
    echo "  DSM → Control Panel → Personal → Security → Account → Personal Access Tokens → Add"
    echo ""
    read -rsp "Synology PAT (input hidden): " NAS_TOKEN
    echo ""
fi

echo ""
echo "Storing credentials…"
store "synology-url"   "$NAS_URL"
store "synology-token" "$NAS_TOKEN"

echo ""
echo "Done! To verify:"
echo "  security find-generic-password -s '$SERVICE' -a 'synology-url' -w"
echo "  security find-generic-password -s '$SERVICE' -a 'synology-token' -w"
