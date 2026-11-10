#!/usr/bin/env bash
# EDGAR-SENTINEL Stock Research App Launcher
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

PORT=8100
TAILSCALE_PORT=8443

echo "=== EDGAR-SENTINEL Stock Research App ==="

# Check Tailscale status and configure serve / funnel on 8443
if command -v tailscale >/dev/null 2>&1; then
    TS_IP="$(tailscale ip -4 2>/dev/null || true)"
    TS_STATUS="$(tailscale status 2>/dev/null || true)"
    
    # Ensure Tailscale funnel/serve on 8443 points to local port 8100
    if tailscale funnel status 2>&1 | grep -q ":8443"; then
        echo "[✓] Tailscale link active on port $TAILSCALE_PORT"
    else
        echo "[*] Setting up Tailscale link on port $TAILSCALE_PORT..."
        tailscale funnel --bg --https "$TAILSCALE_PORT" "$PORT" >/dev/null 2>&1 || \
        tailscale serve --bg --https "$TAILSCALE_PORT" "$PORT" >/dev/null 2>&1 || true
    fi
fi

echo ""
echo "App URLs:"
echo "  Local (this machine):   http://localhost:$PORT"
echo "  Tailscale link:         https://sic.tail1342f1.ts.net:$TAILSCALE_PORT"
if [ -n "${TS_IP:-}" ]; then
echo "  Tailnet direct IP:      http://$TS_IP:$PORT"
fi
echo ""
echo "Press Ctrl+C to stop the web app."
echo "=========================================="

# Run under memory cap (Rule 5: MemoryMax=3G, MemorySwapMax=0)
exec systemd-run --user --scope -p MemoryMax=3G -p MemorySwapMax=0 uv run sentinel web --port "$PORT"

