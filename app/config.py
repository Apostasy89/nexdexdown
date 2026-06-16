from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_user_ids: tuple[int, ...]
    base_dir: Path
    data_dir: Path
    temp_dir: Path
    db_path: Path
    log_path: Path
    max_file_mb: int
    max_file_bytes: int
    download_timeout: int
    ffmpeg_timeout: int
    history_limit: int
    retry_attempts: int
    queue_poll_interval: float


def load_dotenv(base_dir: Path) -> None:
    env_path = base_dir / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_settings() -> Settings:
    base_dir = Path(__file__).resolve().parent.parent
    load_dotenv(base_dir)

    data_dir = base_dir / "data"
    temp_dir = data_dir / "tmp"
    db_path = data_dir / "music_bot.sqlite3"
    log_path = data_dir / "bot.log"
    max_file_mb = int(os.getenv("MAX_FILE_MB", "50"))
    admin_user_ids = tuple(
        int(value.strip())
        for value in os.getenv("ADMIN_USER_IDS", "").split(",")
        if value.strip()
    )

    return Settings(
        bot_token=os.getenv("BOT_TOKEN", ""),
        admin_user_ids=admin_user_ids,
        base_dir=base_dir,
        data_dir=data_dir,
        temp_dir=temp_dir,
        db_path=Path(os.getenv("DB_PATH", db_path)),
        log_path=Path(os.getenv("LOG_PATH", log_path)),
        max_file_mb=max_file_mb,
        max_file_bytes=max_file_mb * 1024 * 1024,
        download_timeout=int(os.getenv("DOWNLOAD_TIMEOUT", "180")),
        ffmpeg_timeout=int(os.getenv("FFMPEG_TIMEOUT", "300")),
        history_limit=int(os.getenv("HISTORY_LIMIT", "10")),
        retry_attempts=int(os.getenv("RETRY_ATTEMPTS", "2")),
        queue_poll_interval=float(os.getenv("QUEUE_POLL_INTERVAL", "0.2")),
    )
