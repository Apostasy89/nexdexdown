from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import Settings


def setup_logging(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.temp_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = RotatingFileHandler(settings.log_path, maxBytes=1_000_000, backupCount=3)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
