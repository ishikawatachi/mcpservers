#!/usr/bin/env bash
# setup_keychain.sh — Store Portainer credentials in macOS Keychain
#
# Usage:
#   ./scripts/setup_keychain.sh
#
# The script prompts for your Portainer base URL and API token.
# Values are stored under the "portainer-mcp" service in your login Keychain.
# Nothing is echoed to the terminal or written to disk.

set -euo pipefail

SERVICE="portainer-mcp"

_store() {
    local account="$1"
    local value="$2"
    # Delete first (ignore error if absent), then add
    security delete-generic-password -s "$SERVICE" -a "$account" 2>/dev/null || true
    security add-generic-password -s "$SERVICE" -a "$account" -w "$value"
    echo "  ✓ Stored '$account'"
}

echo ""
echo "=== Portainer MCP Keychain Setup ==="
echo ""

read -r -p "Portainer base URL [https://pr.local.defaultvaluation.com]: " url
url="${url:-https://pr.local.defaultvaluation.com}"
_store "portainer-url" "$url"

echo -n "Portainer API token (ptr_…): "
read -r -s token
echo ""
if [[ -z "$token" ]]; then
    echo "ERROR: API token cannot be empty."
    exit 1
fi
_store "portainer-token" "$token"

echo ""
echo "Credentials stored. Verify with:"
echo "  security find-generic-password -s portainer-mcp -a portainer-url -w"
echo ""
