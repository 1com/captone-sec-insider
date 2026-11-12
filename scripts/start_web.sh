#!/usr/bin/env bash
# EDGAR-SENTINEL stock research app (026): start it on this computer only.
#
# The researcher, 12 Nov: the app runs locally, with no Tailscale or other link (decision V2-71,
# replacing V2-64's shared link). It listens on 127.0.0.1, which Windows forwards from WSL, so it
# opens at http://localhost:8100 in a browser on this computer. This script never changes any
# Tailscale setting. With WEB_PASSWORD in .env the page asks for that password.
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT=8100

echo "=== EDGAR-SENTINEL stock research app ==="
echo ""
echo "  Open in your browser:   http://localhost:$PORT"
echo "  This computer only: no Tailscale or other link (decision V2-71)."
echo ""
echo "Press Ctrl+C to stop the app."
echo "=========================================="

# under the memory cap (AGENTS.md section 5); the port is checked free by `sentinel web`
exec systemd-run --user --scope -p MemoryMax=3G -p MemorySwapMax=0 uv run sentinel web --port "$PORT"
