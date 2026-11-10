#!/usr/bin/env bash
# EDGAR-SENTINEL Stock Research App Launcher
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

PORT=8100

echo "=== EDGAR-SENTINEL Stock Research App ==="

# Check Tailscale status and configure serve / funnel on port 443
if command -v tailscale >/dev/null 2>&1; then
    TS_IP="$(tailscale ip -4 2>/dev/null || true)"
    
    # Ensure Tailscale funnel on default HTTPS (port 443) points to local port 8100
    if tailscale funnel status 2>&1 | grep -q "proxy http://127.0.0.1:$PORT"; then
        echo "[✓] Tailscale link active"
    else
        echo "[*] Setting up Tailscale link..."
        tailscale funnel --bg "$PORT" >/dev/null 2>&1 || true
    fi
fi

echo ""
echo "App URLs:"
echo "  Local (this machine):   http://localhost:$PORT"
echo "  Tailscale link:         https://sic.tail1342f1.ts.net"
if [ -n "${TS_IP:-}" ]; then
echo "  Tailnet direct IP:      http://$TS_IP:$PORT"
fi
echo ""
echo "Press Ctrl+C to stop the web app."
echo "=========================================="

# Run under memory cap (Rule 5: MemoryMax=3G, MemorySwapMax=0)
exec systemd-run --user --scope -p MemoryMax=3G -p MemorySwapMax=0 uv run sentinel web --port "$PORT"
