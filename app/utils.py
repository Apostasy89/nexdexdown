import re
from urllib.parse import urlparse
from pathlib import Path


def extract_url(text: str) -> str | None:
    """Извлекает URL из текста"""
    urls = re.findall(
        r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+',
        text
    )
    return urls[0] if urls else None


def looks_like_music_url(url: str) -> bool:
    """Проверяет, похожа ли ссылка на музыкальную платформу"""
    music_domains = [
        'vk.com', 'vkontakte.ru',
        'music.yandex', 'yandex.ru/music',
        'spotify.com',
        'soundcloud.com',
        'youtube.com', 'youtu.be',
    ]
    return any(domain in url.lower() for domain in music_domains)


def human_size(size_bytes: int) -> str:
    """Конвертирует размер в человекочитаемый формат"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} TB"


def safe_filename(filename: str) -> str:
    """Делает имя файла безопасным"""
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    filename = re.sub(r'\s+', '_', filename)
    return filename[:255]


def source_title_from_url(url: str) -> str:
    """Извлекает название из URL"""
    try:
        parsed = urlparse(url)
        return parsed.netloc or 'unknown'
    except:
        return 'unknown'
