#!/usr/bin/env bash
# EDGAR-SENTINEL stock research app (026): start it on this machine and share it with the tailnet.
#
# Sharing uses Tailscale SERVE (tailnet only): only devices in the researcher's tailnet and people
# the machine is shared with can open the link. Never Tailscale FUNNEL: that would make the app
# public, and it shows Tiingo-derived prices, which must never be on a public page (constitution
# VI; researcher, 10 Nov: option A, invited people only).
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT=8100

echo "=== EDGAR-SENTINEL stock research app ==="

if command -v tailscale >/dev/null 2>&1; then
    if tailscale funnel status 2>&1 | grep -qi "funnel on"; then
        echo "[!] Tailscale Funnel is on (public): turning it off"
        tailscale funnel --https=443 off >/dev/null 2>&1 || true
    fi
    tailscale serve --bg "$PORT" >/dev/null 2>&1 || echo "[!] Tailscale serve could not start"
    LINK="$(tailscale serve status 2>/dev/null | awk '/tailnet only/ {print $1; exit}')"
fi

echo ""
echo "  This machine:           http://localhost:$PORT"
[ -n "${LINK:-}" ] && echo "  Invited people:         $LINK  (tailnet only)"
echo ""
echo "Press Ctrl+C to stop the app (the tailnet link then shows an error until it is started again)."
echo "=========================================="

# under the memory cap (AGENTS.md section 5); the port is checked free by `sentinel web`
exec systemd-run --user --scope -p MemoryMax=3G -p MemorySwapMax=0 uv run sentinel web --port "$PORT"
