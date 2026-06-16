#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$PROJECT_DIR/venv"
PYTHON="$VENV/bin/python"
PIP="$VENV/bin/pip"
SERVICE="nexdownsave"

usage() {
  cat <<'USAGE'
Usage:
  ./run.sh setup            Create venv and install dependencies
  ./run.sh env              Create .env from .env.example if missing
  ./run.sh run              Run bot locally
  ./run.sh compile          Syntax check project
  ./run.sh health           Run healthcheck
  ./run.sh backup           Create database backup
  ./run.sh brand-assets     Generate local brand PNG assets
  ./run.sh service-install  Install/update systemd service
  ./run.sh service-restart  Restart systemd service
  ./run.sh service-status   Show systemd service status
  ./run.sh logs             Tail journald logs
  ./run.sh clean            Remove __pycache__ directories
USAGE
}

ensure_venv() {
  if [[ ! -x "$PYTHON" ]]; then
    python3 -m venv "$VENV"
  fi
}

cmd_setup() {
  ensure_venv
  "$PIP" install -U pip
  "$PIP" install -r "$PROJECT_DIR/requirements.txt"
}

cmd_env() {
  if [[ ! -f "$PROJECT_DIR/.env" ]]; then
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    echo ".env created from template"
  else
    echo ".env already exists"
  fi
}

cmd_run() {
  ensure_venv
  cd "$PROJECT_DIR"
  exec "$PYTHON" bot.py
}

cmd_compile() {
  ensure_venv
  "$PYTHON" -m compileall "$PROJECT_DIR"
}

cmd_health() {
  ensure_venv
  cd "$PROJECT_DIR"
  "$PYTHON" healthcheck.py
}

cmd_backup() {
  cd "$PROJECT_DIR"
  ./backup_db.sh
}

cmd_brand_assets() {
  ensure_venv
  cd "$PROJECT_DIR"
  "$PYTHON" scripts/generate_brand_assets.py
}

cmd_service_install() {
  sudo cp "$PROJECT_DIR/deploy/nexdownsave.service" "/etc/systemd/system/$SERVICE.service"
  sudo systemctl daemon-reload
  sudo systemctl enable --now "$SERVICE"
}

cmd_service_restart() {
  sudo systemctl restart "$SERVICE"
}

cmd_service_status() {
  sudo systemctl status "$SERVICE"
}

cmd_logs() {
  journalctl -u "$SERVICE" -f
}

cmd_clean() {
  find "$PROJECT_DIR" -type d -name '__pycache__' -prune -exec rm -rf {} +
}

case "${1:-help}" in
  setup) cmd_setup ;;
  env) cmd_env ;;
  run) cmd_run ;;
  compile) cmd_compile ;;
  health) cmd_health ;;
  backup) cmd_backup ;;
  brand-assets) cmd_brand_assets ;;
  service-install) cmd_service_install ;;
  service-restart) cmd_service_restart ;;
  service-status) cmd_service_status ;;
  logs) cmd_logs ;;
  clean) cmd_clean ;;
  help|-h|--help) usage ;;
  *)
    usage
    exit 1
    ;;
esac
