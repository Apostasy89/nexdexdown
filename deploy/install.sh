#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_NAME="nexdownsave"
SERVICE_USER="${SERVICE_USER:-${SUDO_USER:-$USER}}"
RENDERED_SERVICE="/tmp/${SERVICE_NAME}.service"

sudo apt update
sudo apt install -y python3 python3-venv ffmpeg curl sqlite3

python3 -m venv "$PROJECT_DIR/venv"
"$PROJECT_DIR/venv/bin/pip" install -U pip
"$PROJECT_DIR/venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

if [[ ! -f "$PROJECT_DIR/.env" ]]; then
  cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
  echo ".env создан из шаблона. Заполни BOT_TOKEN перед запуском сервиса."
fi

sed \
  -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
  -e "s|__RUN_USER__|$SERVICE_USER|g" \
  "$PROJECT_DIR/deploy/nexdownsave.service" > "$RENDERED_SERVICE"

sudo cp "$RENDERED_SERVICE" "/etc/systemd/system/$SERVICE_NAME.service"
sudo cp "$PROJECT_DIR/deploy/nexdownsave.logrotate" /etc/logrotate.d/nexdownsave
sudo systemctl daemon-reload

echo "Установка завершена. SERVICE_USER=$SERVICE_USER"
echo "После настройки .env выполни: sudo systemctl enable --now $SERVICE_NAME"
