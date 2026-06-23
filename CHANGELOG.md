# Changelog

## 1.2.0 - 2026-06-24

- added search by track name: plain text is treated as a `yt-dlp` `ytsearch` query with numbered, selectable results
- added inline mode (`@bot query`) serving cached tracks instantly and deep-linking new queries into the bot
- added a `tracks` cache table that stores Telegram `file_id` for instant repeats and inline delivery without re-downloading
- added a `search_cache` table with TTL pruning to back numbered result selection and inline deep links
- routed link repeats through the cache for instant re-sends
- added `SEARCH_TIMEOUT` and `SEARCH_RESULTS` settings
- added unit tests for the track cache, search cache, and search-result handling
- refreshed start, help, and stats UX to surface search and inline features

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
