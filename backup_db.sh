#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="$BASE_DIR/data"
DB_PATH="$DATA_DIR/music_bot.sqlite3"
BACKUP_DIR="$DATA_DIR/backups"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$BACKUP_DIR"
if [[ ! -f "$DB_PATH" ]]; then
  echo "database not found: $DB_PATH" >&2
  exit 1
fi

sqlite3 "$DB_PATH" ".backup '$BACKUP_DIR/music_bot-$TIMESTAMP.sqlite3'"

mapfile -t backups < <(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'music_bot-*.sqlite3' | sort)
if (( ${#backups[@]} > 10 )); then
  printf '%s\0' "${backups[@]:0:${#backups[@]}-10}" | xargs -0r rm -f
fi

echo "backup created: $BACKUP_DIR/music_bot-$TIMESTAMP.sqlite3"
