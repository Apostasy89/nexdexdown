from __future__ import annotations

from html import escape
import re
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

DIRECT_AUDIO_EXTENSIONS = (
    '.mp3',
    '.m4a',
    '.wav',
    '.ogg',
    '.flac',
    '.aac',
    '.opus',
    '.wma',
    '.aif',
    '.aiff',
)
URL_RE = re.compile(r'https?://\S+', re.IGNORECASE)
STATUS_LABELS = {
    'queued': 'в очереди',
    'done': 'готово',
    'failed': 'ошибка',
    'cancelled': 'отменено',
}
TRAILING_URL_PUNCTUATION = ".,!?;:\"'"
URL_WRAPPER_PAIRS = ((')', '('), (']', '['), ('}', '{'), ('>', '<'))


def normalize_extracted_url(url: str) -> str:
    normalized = url.rstrip(TRAILING_URL_PUNCTUATION)
    for closing, opening in URL_WRAPPER_PAIRS:
        while normalized.endswith(closing) and normalized.count(opening) < normalized.count(closing):
            normalized = normalized[:-1]
    return normalized


def extract_url(text: str) -> Optional[str]:
    match = URL_RE.search(text.strip())
    if not match:
        return None
    return normalize_extracted_url(match.group(0))


def looks_like_direct_audio_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(DIRECT_AUDIO_EXTENSIONS)


def human_size(size: int) -> str:
    value = float(size)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if value < 1024 or unit == 'GB':
            return f'{value:.1f} {unit}'
        value /= 1024
    return f'{size} B'


def human_duration(duration_seconds: float | None) -> str | None:
    if duration_seconds is None:
        return None
    total_seconds = max(0, int(duration_seconds))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f'{hours}:{minutes:02d}:{seconds:02d}'
    return f'{minutes}:{seconds:02d}'


def safe_filename(name: str) -> str:
    cleaned = re.sub(r'[^\w\-. ]+', '_', name, flags=re.UNICODE).strip()
    return cleaned[:120] or 'audio'


def source_title_from_url(url: str) -> str:
    return safe_filename(unquote(Path(urlparse(url).path).stem) or 'audio')


def source_filename_from_url(url: str) -> str:
    return safe_filename(unquote(Path(urlparse(url).path).name) or 'audio')


def html_escape(value: object) -> str:
    return escape(str(value), quote=False)


def html_code(value: object) -> str:
    return f'<code>{html_escape(value)}</code>'


def present_status(status: str) -> str:
    return STATUS_LABELS.get(status, status)
