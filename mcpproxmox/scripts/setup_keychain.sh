#!/usr/bin/env bash
# =============================================================================
# setup_keychain.sh — Store Proxmox MCP credentials in macOS Keychain
# =============================================================================
# Usage:
#   chmod +x scripts/setup_keychain.sh
#   ./scripts/setup_keychain.sh
#
# Alternatively, provide values via env vars to skip interactive prompts:
#   PROXMOX_URL=https://pm.example.com \
#   PROXMOX_TOKEN='root@pam!mcp=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx' \
#   ./scripts/setup_keychain.sh
# =============================================================================

set -euo pipefail

SERVICE="proxmox-mcp"

store() {
    local account="$1" value="$2"
    /usr/bin/security add-generic-password \
        -s "$SERVICE" -a "$account" -w "$value" -U
    echo "  ✓ Stored '$account' in Keychain (service: $SERVICE)"
}

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║    Proxmox MCP — Keychain Setup          ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# --- Proxmox URL ---
if [[ -n "${PROXMOX_URL:-}" ]]; then
    PVE_URL="$PROXMOX_URL"
else
    read -rp "Proxmox URL (e.g. https://pm.local.example.com): " PVE_URL
fi

# --- API Token ---
# Full format: user@realm!tokenid=uuid
# Example:     root@pam!mcp=dfba4d3d-4005-4c42-95be-bb1cc805c857
if [[ -n "${PROXMOX_TOKEN:-}" ]]; then
    PVE_TOKEN="$PROXMOX_TOKEN"
else
    echo ""
    echo "API token format:  user@realm!tokenid=uuid"
    echo "Example:           root@pam!mcp=dfba4d3d-4005-4c42-95be-bb1cc805c857"
    echo ""
    read -rsp "Proxmox API Token (input hidden): " PVE_TOKEN
    echo ""
fi

echo ""
echo "Storing credentials…"
store "proxmox-url"   "$PVE_URL"
store "proxmox-token" "$PVE_TOKEN"

echo ""
echo "Done! To verify, run:"
echo "  security find-generic-password -s '$SERVICE' -a 'proxmox-url' -w"
echo ""
