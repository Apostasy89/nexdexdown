import re
import asyncio
import logging
from pathlib import Path
from typing import Optional
from .base_parser import BaseParser, Track

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

logger = logging.getLogger(__name__)


class UniversalParser(BaseParser):
    """Универсальный парсер на основе yt-dlp для всех платформ"""
    
    SUPPORTED_PLATFORMS = {
        'vk': r'vk\.com|vkontakte\.ru',
        'yandex': r'music\.yandex\.|yandex\.ru/music',
        'spotify': r'spotify\.com',
        'soundcloud': r'soundcloud\.com',
        'youtube': r'youtube\.com|youtu\.be',
    }
    
    async def parse(self, url: str) -> Track:
        """Парсит информацию о треке с любой платформы"""
        try:
            if yt_dlp is None:
                raise Exception("yt-dlp не установлен. Установите: pip install yt-dlp")
            
            loop = asyncio.get_event_loop()
            track = await loop.run_in_executor(None, self._extract_info, url)
            return track
            
        except Exception as e:
            logger.error(f"Ошибка при парсинге трека: {str(e)}")
            raise Exception(f"Ошибка при парсинге трека: {str(e)}")
    
    def _extract_info(self, url: str) -> Track:
        """Извлекает информацию через yt-dlp (синхронная версия)"""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            title = info.get('title', 'Unknown')
            artist = info.get('uploader', 'Unknown Artist')
            duration = info.get('duration')
            platform = self.detect_platform(url)
            cover_url = info.get('thumbnail')
            
            return Track(
                title=title,
                artist=artist,
                url=url,
                duration=duration,
                platform=platform,
                cover_url=cover_url,
            )
    
    def detect_platform(self, url: str) -> str:
        """Определяет платформу по URL"""
        for platform, pattern in self.SUPPORTED_PLATFORMS.items():
            if re.search(pattern, url, re.IGNORECASE):
                return platform
        return "unknown"
    
    async def download(self, track: Track, output_path: str = "downloads") -> str:
        """Скачивает трек с любой платформы"""
        if yt_dlp is None:
            raise Exception("yt-dlp не установлен")
        
        Path(output_path).mkdir(exist_ok=True)
        loop = asyncio.get_event_loop()
        
        def _download():
            ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'outtmpl': f'{output_path}/%(title)s.%(ext)s',
                'quiet': False,
                'no_warnings': False,
                'socket_timeout': 30,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0'
                }
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(track.url, download=True)
                file_path = f"{output_path}/{info.get('title')}.mp3"
                logger.info(f"Трек скачан: {file_path}")
                return file_path
        
        try:
            file_path = await loop.run_in_executor(None, _download)
            track.file_path = file_path
            return file_path
        except Exception as e:
            logger.error(f"Ошибка при скачивании: {str(e)}")
            raise Exception(f"Ошибка при скачивании трека: {str(e)}")
    
    def detect(self, url: str) -> bool:
        """Проверяет, поддерживается ли URL"""
        for pattern in self.SUPPORTED_PLATFORMS.values():
            if re.search(pattern, url, re.IGNORECASE):
                return True
        return False
