#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)

python3 -m py_compile "$ROOT/bin/idle-inhibit-daemon"
omarchy plugin validate "$ROOT"
python3 "$ROOT/tests/daemon_test.py"
echo "idle-inhibit tests passed"
