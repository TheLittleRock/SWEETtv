#!/usr/bin/env bash
# Sweet.tv IPTV Proxy Server Startup Script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Ensure data directory exists
mkdir -p data

# Virtual Environment Setup
if [ ! -d ".venv" ]; then
    echo "Creating Python virtual environment in .venv..."
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt
fi

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-5000}"

echo "=========================================================="
echo " Starting Sweet.tv IPTV Proxy Server on http://${HOST}:${PORT}"
echo "=========================================================="

exec .venv/bin/python3 -m uvicorn app.main:app --host "$HOST" --port "$PORT"
