#!/usr/bin/env bash
# Stop EDGAR-SENTINEL Stock Research App
set -euo pipefail

echo "Stopping EDGAR-SENTINEL web app (port 8100)..."

# Find and stop uvicorn / sentinel web process
PIDS=$(pgrep -f "sentinel web" || true)
if [ -n "$PIDS" ]; then
    kill $PIDS 2>/dev/null || true
    echo "Stopped PID(s): $PIDS"
else
    echo "No running sentinel web process found."
fi

# Also check for any process listening on 8100 in WSL
PORT_PID=$(fuser 8100/tcp 2>/dev/null || true)
if [ -n "$PORT_PID" ]; then
    kill -9 $PORT_PID 2>/dev/null || true
    echo "Killed remaining process on port 8100: $PORT_PID"
fi

echo "Done."

