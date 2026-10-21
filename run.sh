#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

echo "Checking dependencies..."
.venv/bin/python -m pip install -q -r requirements.txt

exec .venv/bin/python -m unipus_web "$@"
