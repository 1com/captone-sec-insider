#!/usr/bin/env bash
# EDGAR-SENTINEL stock research app (026): start it on this machine and share it.
#
# With WEB_PASSWORD in .env the app asks every visitor for that password, so it is shared by a
# public Tailscale Funnel link (researcher, 10 Nov: option A, one link and one password for the
# team and tutors). Without a password the app shows Tiingo-derived prices to anyone, which must
# never be on a public page (constitution VI): it is then shared with the tailnet only (serve).
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT=8100

echo "=== EDGAR-SENTINEL stock research app ==="

if command -v tailscale >/dev/null 2>&1; then
    if grep -qE '^WEB_PASSWORD=.+' .env 2>/dev/null; then
        tailscale funnel --bg "$PORT" >/dev/null 2>&1 || echo "[!] Tailscale funnel could not start"
        SHARE="public link, password required"
    else
        tailscale funnel --https=443 off >/dev/null 2>&1 || true
        tailscale serve --bg "$PORT" >/dev/null 2>&1 || echo "[!] Tailscale serve could not start"
        SHARE="tailnet only: no WEB_PASSWORD in .env"
    fi
    LINK="$(tailscale serve status 2>/dev/null | awk '/^https:/ {print $1; exit}')"
fi

echo ""
echo "  This machine:   http://localhost:$PORT"
[ -n "${LINK:-}" ] && echo "  Shared link:    $LINK  ($SHARE)"
echo ""
echo "Press Ctrl+C to stop the app (the shared link then shows an error until it is started again)."
echo "=========================================="

# under the memory cap (AGENTS.md section 5); the port is checked free by `sentinel web`
exec systemd-run --user --scope -p MemoryMax=3G -p MemorySwapMax=0 uv run sentinel web --port "$PORT"
