#!/bin/bash
# finder-pane: Finder-like file browser for cmux
PORT=${1:-8234}
DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$DIR/server.py" "$PORT"
