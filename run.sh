#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
apt_in() { command -v apt-get >/dev/null && sudo apt-get install -y "$@"; }
PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then echo "Python not found. Installing..."; apt_in python3 python3-venv python3-pip; PY=$(command -v python3); fi
[ -z "$PY" ] && { echo "Please install Python 3, then run this again."; exit 1; }
if ! "$PY" -c "import venv, ensurepip" 2>/dev/null; then echo "Installing python venv..."; apt_in python3-venv python3-pip; fi
"$PY" app/setup.py || { echo "Setup failed. See the message above."; exit 1; }
exec .venv/bin/python app/server.py
