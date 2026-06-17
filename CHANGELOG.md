# Changelog

## 1.1.0 - 2026-06-17

- switched bot text rendering to safe HTML to eliminate Markdown escaping bugs with user content
- added queue backpressure via `QUEUE_MAXSIZE` and earlier file-size rejection for uploads
- improved SQLite initialization with pragmas, indexes, and typed favorite records
- hardened healthcheck and systemd startup so first deployment no longer fails on a missing database
- added unit tests, `make test`, `make check`, and a GitHub Actions CI workflow
- improved backup retention logic and deployment scripts

## 1.0.0 - 2026-06-16

- initial GitHub-ready NexDownSave release
- Russian branded Telegram UX
- queue-based processing and retries
- MP3 conversion pipeline with ffmpeg
- metadata extraction with ffprobe
- SQLite-backed stats, history, and favorites
- healthcheck, backup script, and systemd deployment assets
