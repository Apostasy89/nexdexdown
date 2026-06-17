#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_NAME="nexdownsave"

sudo apt update
sudo apt install -y python3 python3-venv ffmpeg curl sqlite3

if [[ ! -x "$PROJECT_DIR/venv/bin/python" ]]; then
  python3 -m venv "$PROJECT_DIR/venv"
fi
"$PROJECT_DIR/venv/bin/pip" install -U pip
"$PROJECT_DIR/venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

mkdir -p "$PROJECT_DIR/data/backups" "$PROJECT_DIR/tmp"
"$PROJECT_DIR/venv/bin/python" -m compileall "$PROJECT_DIR"
"$PROJECT_DIR/venv/bin/python" "$PROJECT_DIR/healthcheck.py" --allow-missing-db

if [[ ! -f "$PROJECT_DIR/.env" ]]; then
  cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
  echo ".env создан из шаблона. Заполни BOT_TOKEN перед запуском сервиса."
fi

sudo cp "$PROJECT_DIR/deploy/nexdownsave.service" "/etc/systemd/system/$SERVICE_NAME.service"
sudo cp "$PROJECT_DIR/deploy/nexdownsave.logrotate" /etc/logrotate.d/nexdownsave
sudo systemctl daemon-reload

echo "Установка завершена. После настройки .env выполни: sudo systemctl enable --now $SERVICE_NAME"
