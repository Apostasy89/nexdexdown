# NexDownSave

<p align="center">
  <img src="assets/brand/nexdownsave-logo.png" alt="NexDownSave logo" width="320">
</p>

<p align="center">
  <img src="assets/brand/github-banner.png" alt="NexDownSave GitHub banner" width="100%">
</p>

NexDownSave is a production-oriented Telegram bot for direct audio links and uploaded audio files. It focuses on predictable processing, clean Russian-first UX, and maintainable deployment on Ubuntu.

## Highlights

- Russian-first branded Telegram UX
- safe HTML-formatted bot responses without Markdown escaping bugs
- paginated history and favorites
- in-bot library search
- queue-based job processing with backpressure via `QUEUE_MAXSIZE`
- MP3 conversion via `ffmpeg`
- metadata-rich result cards via `ffprobe`
- stronger uploaded-file validation before conversion
- SQLite persistence for users, stats, history, and favorites
- rotating logs, healthcheck, database backup, and `systemd` service support
- local unit tests and GitHub Actions CI
- local brand asset generation for logo, banner, avatar, splash, and promo card

## Repository layout

- `bot.py` - entry point
- `app/config.py` - settings and `.env` loading
- `app/main.py` - Telegram handlers, queue, UX, and orchestration
- `app/services.py` - downloading, conversion, and metadata extraction
- `app/db.py` - SQLite persistence
- `app/keyboards.py` - inline keyboards
- `healthcheck.py` - runtime health probe
- `backup_db.sh` - SQLite backup utility
- `deploy/nexdownsave.service` - `systemd` service file
- `deploy/install.sh` - first-time VPS setup helper
- `tests/` - unit tests for critical logic
- `.github/workflows/ci.yml` - basic CI pipeline

## Requirements

- Python 3.10+
- `ffmpeg`
- `ffprobe`
- `curl`
- `sqlite3`

## Quick start

```bash
sudo apt update
sudo apt install -y python3 python3-venv ffmpeg curl sqlite3
cd /home/casperhood/.codex/NexDownSave
python3 -m venv venv
source venv/bin/activate
pip install -U pip
pip install -r requirements.txt
cp .env.example .env
python3 bot.py
```

Edit `.env` before first production run.

## Environment

See [`.env.example`](/home/casperhood/.codex/NexDownSave/.env.example).

Main variables:

- `BOT_TOKEN`
- `ADMIN_USER_IDS`
- `MAX_FILE_MB`
- `DOWNLOAD_TIMEOUT`
- `FFMPEG_TIMEOUT`
- `HISTORY_LIMIT`
- `RETRY_ATTEMPTS`
- `QUEUE_POLL_INTERVAL`
- `QUEUE_MAXSIZE`

## Local management

Use either `make` or `run.sh`.

### Makefile

```bash
make help
make install
make env
make test
make check
make run
make health
make backup
make brand-assets
```

### run.sh

```bash
./run.sh setup
./run.sh env
./run.sh test
./run.sh check
./run.sh run
./run.sh health
./run.sh backup
./run.sh brand-assets
```

## Testing

```bash
cd /home/casperhood/.codex/NexDownSave
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall .
```



## Bothost deployment

Bothost builds bots inside Docker containers and supports custom `Dockerfile`. This repository includes a ready-to-use container build for Bothost with `ffmpeg`, `curl`, `sqlite3`, and persistent data in `/app/data`.

### What to configure in Bothost

1. Create a bot from GitHub repository URL: `https://github.com/Apostasy89/nexdexdown.git`
2. Branch: `main`
3. Build mode: custom `Dockerfile`
4. Add environment variables in the Bothost dashboard:
   - `BOT_TOKEN`
   - `ADMIN_USER_IDS`
   - optional: `MAX_FILE_MB`, `DOWNLOAD_TIMEOUT`, `FFMPEG_TIMEOUT`, `QUEUE_MAXSIZE`
5. Keep database and logs in the default container paths:
   - `DB_PATH=/app/data/music_bot.sqlite3`
   - `LOG_PATH=/app/data/bot.log`

### Why this works on Bothost

- Bothost installs Python dependencies from the repo root and supports custom `Dockerfile` for system packages.
- The bot needs `ffmpeg`, so plain `requirements.txt` alone is not enough.
- The application stores runtime files in `data/`, which maps cleanly to Bothost persistent storage guidance.

### Recommended Bothost environment variables

```text
BOT_TOKEN=123456789:AA...
ADMIN_USER_IDS=123456789
DB_PATH=/app/data/music_bot.sqlite3
LOG_PATH=/app/data/bot.log
QUEUE_MAXSIZE=100
MAX_FILE_MB=50
DOWNLOAD_TIMEOUT=180
FFMPEG_TIMEOUT=300
```

## Production deployment

Use `deploy/install.sh` for first-time VPS setup or `make service-install` for an existing machine.

### systemd

```bash
sudo cp deploy/nexdownsave.service /etc/systemd/system/nexdownsave.service
sudo systemctl daemon-reload
sudo systemctl enable --now nexdownsave
sudo systemctl status nexdownsave
```

### journald logs

```bash
journalctl -u nexdownsave -f
```

### healthcheck

```bash
/home/casperhood/.codex/NexDownSave/venv/bin/python /home/casperhood/.codex/NexDownSave/healthcheck.py
```

For first deployment before the database exists:

```bash
/home/casperhood/.codex/NexDownSave/venv/bin/python /home/casperhood/.codex/NexDownSave/healthcheck.py --allow-missing-db
```

### database backup

```bash
/home/casperhood/.codex/NexDownSave/backup_db.sh
```

Optional cron example:

```bash
0 */6 * * * /home/casperhood/.codex/NexDownSave/backup_db.sh
```

## Bot commands

- `/start`
- `/help`
- `/stats`
- `/history`
- `/favorites`
- `/search <text>`
- `/status`
- `/admin`

## Scope

NexDownSave supports:

- direct links to audio files
- audio files uploaded by the user

It does not support general webpage extraction or unsupported media sources.

## Security notes

- use a fresh Telegram bot token
- do not commit `.env`
- keep `data/` out of public repos unless sanitized
- keep `QUEUE_MAXSIZE` realistic to avoid disk pressure during bursts

## License

MIT
