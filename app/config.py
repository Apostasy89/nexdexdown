from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import os
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Settings:
    """Настройки приложения"""
    
    # Telegram
    bot_token: str = os.getenv("BOT_TOKEN", "")
    
    # Database
    db_path: Path = Path("data/music_bot.sqlite3")
    
    # Paths
    downloads_dir: Path = Path("downloads")
    temp_dir: Path = Path("temp")
    
    # Limits
    max_file_mb: int = 100
    download_timeout: int = 600
    ffmpeg_timeout: int = 300
    queue_poll_interval: float = 1.0
    retry_attempts: int = 3
    
    # History
    history_limit: int = 50
    
    # Admin
    admin_user_ids: list[int] = field(default_factory=lambda: [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()])
    
    # Spotify
    spotify_client_id: str = os.getenv("SPOTIFY_CLIENT_ID", "")
    spotify_client_secret: str = os.getenv("SPOTIFY_CLIENT_SECRET", "")
    
    def __post_init__(self):
        self.downloads_dir.mkdir(exist_ok=True)
        self.temp_dir.mkdir(exist_ok=True)
        self.db_path.parent.mkdir(exist_ok=True)


def load_settings() -> Settings:
    """Загружает настройки из переменных окружения"""
    return Settings()
