#!/bin/bash
# Start the Hermes dashboard and (optionally) a cloudflared quick tunnel.
# Usage:
#   ./run.sh           — start on localhost:5000 only
#   ./run.sh --tunnel  — start with a cloudflared quick tunnel (prints public URL)

set -euo pipefail

PORT=5000
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Kill any existing instance on this port
fuser -k "${PORT}/tcp" 2>/dev/null || true

echo "[$(date)] Starting Hermes dashboard on port $PORT"
cd "$SCRIPT_DIR"
python3 app.py &
APP_PID=$!
echo "[$(date)] Dashboard PID: $APP_PID"

if [[ "${1:-}" == "--tunnel" ]]; then
    CLOUDFLARED=$(command -v cloudflared || echo "/home/hermes/bin/cloudflared")
    if [[ ! -x "$CLOUDFLARED" ]]; then
        echo "[error] cloudflared not found. Install it first — see README.md."
        exit 1
    fi
    echo "[$(date)] Starting cloudflared quick tunnel..."
    "$CLOUDFLARED" tunnel --url "http://localhost:$PORT"
else
    echo "[$(date)] Dashboard running at http://localhost:$PORT"
    echo "[$(date)] Press Ctrl+C to stop"
    wait $APP_PID
fi
