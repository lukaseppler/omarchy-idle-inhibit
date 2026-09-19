#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)

python3 -m py_compile "$ROOT/bin/idle-inhibit-daemon"
omarchy plugin validate "$ROOT"
if grep -Fq '["python3"' "$ROOT/Service.qml"; then
  echo "Service.qml must not launch PATH python3" >&2
  exit 1
fi
grep -Fq '/usr/bin/python3' "$ROOT/Service.qml"
grep -Fq -- '--check-interpreter' "$ROOT/Service.qml"
python3 "$ROOT/tests/daemon_test.py"
echo "idle-inhibit tests passed"
