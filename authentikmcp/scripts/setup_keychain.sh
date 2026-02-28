#!/usr/bin/env bash
# Setup script — stores Authentik credentials in the macOS Keychain.
# Run once: bash scripts/setup_keychain.sh

set -euo pipefail
SERVICE="authentik-mcp"

read -rp "Authentik URL (e.g. http://192.168.1.x:9000): " AUTHENTIK_URL
printf '%s' "$AUTHENTIK_URL" | /usr/bin/security add-generic-password \
  -s "$SERVICE" -a "authentik-url" -w "$(cat)" -U
echo "✓ URL stored"

read -rp "Authentik API token (Admin → Directory → Tokens): " AUTHENTIK_TOKEN
printf '%s' "$AUTHENTIK_TOKEN" | /usr/bin/security add-generic-password \
  -s "$SERVICE" -a "authentik-token" -w "$(cat)" -U
echo "✓ Token stored"

echo "Done. Run 'authentik-mcp' to start the server."
