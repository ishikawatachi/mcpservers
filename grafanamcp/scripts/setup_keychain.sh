#!/usr/bin/env bash
# Setup script — stores Grafana credentials in the macOS Keychain.
# Run once: bash scripts/setup_keychain.sh

set -euo pipefail
SERVICE="grafana-mcp"

read -rp "Grafana URL (e.g. http://192.168.1.x:3000): " GRAFANA_URL
printf '%s' "$GRAFANA_URL" | /usr/bin/security add-generic-password \
  -s "$SERVICE" -a "grafana-url" -w "$(cat)" -U
echo "✓ URL stored"

read -rp "Grafana service account token: " GRAFANA_TOKEN
printf '%s' "$GRAFANA_TOKEN" | /usr/bin/security add-generic-password \
  -s "$SERVICE" -a "grafana-token" -w "$(cat)" -U
echo "✓ Token stored"

echo "Done. Run 'grafana-mcp' to start the server."
