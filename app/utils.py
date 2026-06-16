from __future__ import annotations

import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

DIRECT_AUDIO_EXTENSIONS = (".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac", ".opus")
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)



def extract_url(text: str) -> Optional[str]:
    match = URL_RE.search(text.strip())
    return match.group(0) if match else None



def looks_like_direct_audio_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(DIRECT_AUDIO_EXTENSIONS)



def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"



def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w\-. ]+", "_", name, flags=re.UNICODE).strip()
    return cleaned[:120] or "audio"



def source_title_from_url(url: str) -> str:
    return safe_filename(Path(urlparse(url).path).stem or "audio")
