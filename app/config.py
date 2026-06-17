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
    queue_maxsize: int

    def ensure_runtime_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)


def load_dotenv(base_dir: Path) -> None:
    env_path = base_dir / '.env'
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _parse_int(name: str, default: str, *, minimum: int | None = None) -> int:
    raw_value = os.getenv(name, default).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f'{name} must be an integer, got: {raw_value!r}') from exc
    if minimum is not None and value < minimum:
        raise ValueError(f'{name} must be >= {minimum}, got: {value}')
    return value


def _parse_float(name: str, default: str, *, minimum: float | None = None) -> float:
    raw_value = os.getenv(name, default).strip()
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f'{name} must be a number, got: {raw_value!r}') from exc
    if minimum is not None and value < minimum:
        raise ValueError(f'{name} must be >= {minimum}, got: {value}')
    return value


def _parse_admin_ids(raw_value: str) -> tuple[int, ...]:
    admin_ids: list[int] = []
    for chunk in raw_value.split(','):
        value = chunk.strip()
        if not value:
            continue
        try:
            admin_ids.append(int(value))
        except ValueError as exc:
            raise ValueError(f'ADMIN_USER_IDS must contain only integers, got: {value!r}') from exc
    return tuple(admin_ids)


def load_settings(base_dir: Path | None = None) -> Settings:
    base_dir = Path(base_dir or Path(__file__).resolve().parent.parent)
    load_dotenv(base_dir)

    data_dir = base_dir / 'data'
    temp_dir = data_dir / 'tmp'
    default_db_path = data_dir / 'music_bot.sqlite3'
    default_log_path = data_dir / 'bot.log'

    max_file_mb = _parse_int('MAX_FILE_MB', '50', minimum=1)
    retry_attempts = _parse_int('RETRY_ATTEMPTS', '2', minimum=0)
    history_limit = _parse_int('HISTORY_LIMIT', '100', minimum=1)
    queue_maxsize = _parse_int('QUEUE_MAXSIZE', '100', minimum=1)

    settings = Settings(
        bot_token=os.getenv('BOT_TOKEN', '').strip(),
        admin_user_ids=_parse_admin_ids(os.getenv('ADMIN_USER_IDS', '')),
        base_dir=base_dir,
        data_dir=data_dir,
        temp_dir=temp_dir,
        db_path=Path(os.getenv('DB_PATH', str(default_db_path))).expanduser(),
        log_path=Path(os.getenv('LOG_PATH', str(default_log_path))).expanduser(),
        max_file_mb=max_file_mb,
        max_file_bytes=max_file_mb * 1024 * 1024,
        download_timeout=_parse_int('DOWNLOAD_TIMEOUT', '180', minimum=1),
        ffmpeg_timeout=_parse_int('FFMPEG_TIMEOUT', '300', minimum=1),
        history_limit=history_limit,
        retry_attempts=retry_attempts,
        queue_poll_interval=_parse_float('QUEUE_POLL_INTERVAL', '0.2', minimum=0.0),
        queue_maxsize=queue_maxsize,
    )
    settings.ensure_runtime_dirs()
    return settings
