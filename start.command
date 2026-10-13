#!/bin/bash
# macOS double-click launcher
cd "$(dirname "$0")"
[ -f .venv/bin/activate ] && source .venv/bin/activate
python3 agent.py "$@"
