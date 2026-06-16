#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="nexdownsave"

echo "== systemd =="
systemctl status "$SERVICE_NAME" --no-pager || true

echo
echo "== journald =="
journalctl -u "$SERVICE_NAME" -n 50 --no-pager || true
