# NexDownSave
THIS PRE-PRE-PRE ALPHA,BETA VERSION.PLZ DONT ASK MY STARTUP
NexDownSave is a release-ready Telegram bot for direct audio links and uploaded audio files. It is built for clean UX, predictable processing, and production deployment on Ubuntu.

## Highlights

- Russian-first branded Telegram UX
- paginated history and favorites
- in-bot library search
- Queue-based job processing with retry attempts
- MP3 conversion via `ffmpeg`
- Metadata-rich result cards via `ffprobe`
- stronger uploaded-file validation before conversion
- SQLite persistence for users, stats, history, and favorites
- `.env` support without extra runtime dependencies
- Rotating logs, healthcheck, database backup, and `systemd` service support

## Brand direction

NexDownSave positions itself as a fast and clean music utility bot:

- direct audio file intake
- minimal friction in chat
- stable queue processing
- operational visibility for admins

## Repository layout

- `bot.py` - entry point
- `app/config.py` - settings and `.env` loading
- `app/main.py` - Telegram handlers, queue, UX, orchestration
- `app/services.py` - downloading, conversion, metadata extraction
- `app/db.py` - SQLite persistence
- `app/keyboards.py` - inline keyboards
- `healthcheck.py` - runtime health probe
- `backup_db.sh` - SQLite backup utility
- `deploy/nexdownsave.service` - `systemd` service file

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

## Local management

Use either `make` or `run.sh`.

### Makefile

```bash
make help
make install
make env
make run
make health
make backup
```

### run.sh

```bash
./run.sh setup
./run.sh env
./run.sh run
./run.sh health
./run.sh backup
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

## License

                  3wS hlhzk
