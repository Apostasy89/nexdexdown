from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class Track:
    """Модель трека"""
    title: str
    artist: str
    url: str
    duration: Optional[int] = None
    file_path: Optional[str] = None
    platform: Optional[str] = None
    cover_url: Optional[str] = None


class BaseParser(ABC):
    """Базовый класс для парсеров"""
    
    @abstractmethod
    async def parse(self, url: str) -> Track:
        """Парсит трек с URL"""
        pass
    
    @abstractmethod
    async def download(self, track: Track, output_path: str = "downloads") -> str:
        """Скачивает трек и возвращает путь к файлу"""
        pass
    
    @abstractmethod
    def detect(self, url: str) -> bool:
        """Проверяет, принадлежит ли URL этому парсеру"""
        pass
