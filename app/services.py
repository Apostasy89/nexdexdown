from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import shutil
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .utils import looks_like_direct_audio_url, source_filename_from_url

logger = logging.getLogger(__name__)

ALLOWED_UPLOAD_EXTENSIONS = {
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
}


@dataclass
class AudioMetadata:
    title: str
    artist: str | None
    album: str | None
    duration_seconds: float | None
    bitrate_kbps: int | None
    codec: str | None


@dataclass
class ProcessResult:
    ok: bool
    message: str
    output_path: Path | None = None
    title: str | None = None
    file_size: int = 0
    metadata: AudioMetadata | None = None


class AudioPipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.temp_dir.mkdir(parents=True, exist_ok=True)

    def check_dependencies(self) -> list[str]:
        missing = []
        for command in ('ffmpeg', 'ffprobe', 'curl'):
            if shutil.which(command) is None:
                missing.append(command)
        if importlib.util.find_spec('yt_dlp') is None:
            missing.append('yt-dlp')
        return missing

    async def run_command(self, *args: str, timeout: int) -> tuple[int, str, str]:
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            return 127, '', str(exc)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            return 124, '', 'timeout'
        return (
            process.returncode,
            stdout.decode('utf-8', errors='replace'),
            stderr.decode('utf-8', errors='replace'),
        )

    def reserve_job_dir(self) -> Path:
        job_dir = self.settings.temp_dir / f'job_{uuid.uuid4().hex}'
        job_dir.mkdir(parents=True, exist_ok=True)
        return job_dir

    def cleanup_job_dir(self, job_dir: Path) -> None:
        if job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)

    async def download_direct_url(self, url: str) -> ProcessResult:
        last_message = 'Не удалось скачать файл.'
        for attempt in range(1, self.settings.retry_attempts + 2):
            job_dir = self.reserve_job_dir()
            source_path = job_dir / source_filename_from_url(url)
            code, _, err = await self.run_command(
                'curl',
                '-L',
                '--fail',
                '--silent',
                '--show-error',
                '--max-filesize',
                str(self.settings.max_file_bytes),
                '-o',
                str(source_path),
                url,
                timeout=self.settings.download_timeout,
            )
            if code == 0 and source_path.exists():
                result = await self.prepare_uploaded_file(source_path)
                if result.ok:
                    return result
                last_message = result.message
                self.cleanup_job_dir(job_dir)
                continue

            logger.warning('Direct download failed for %s on attempt %s: %s', url, attempt, err)
            if code == 63:
                last_message = f'Файл больше {self.settings.max_file_mb} МБ.'
            elif err == 'timeout':
                last_message = 'Превышено время ожидания скачивания.'
            else:
                last_message = 'Не удалось скачать файл.'
            self.cleanup_job_dir(job_dir)
        return ProcessResult(False, last_message)

    def _pick_downloaded_audio_file(self, job_dir: Path) -> Path | None:
        candidates = [
            path
            for path in job_dir.rglob('*')
            if path.is_file() and path.suffix.lower() in ALLOWED_UPLOAD_EXTENSIONS
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item.stat().st_size, item.stat().st_mtime))

    async def download_track_url(self, url: str) -> ProcessResult:
        if looks_like_direct_audio_url(url):
            direct_result = await self.download_direct_url(url)
            if direct_result.ok:
                return direct_result
            logger.info('Direct download fallback triggered for %s: %s', url, direct_result.message)

        job_dir = self.reserve_job_dir()
        output_template = str(job_dir / '%(title).160B [%(id)s].%(ext)s')
        timeout = self.settings.download_timeout + self.settings.ffmpeg_timeout + 120
        code, _, err = await self.run_command(
            sys.executable,
            '-m',
            'yt_dlp',
            '--no-playlist',
            '--no-progress',
            '--no-warnings',
            '--extract-audio',
            '--audio-format',
            'mp3',
            '--audio-quality',
            '0',
            '--output',
            output_template,
            url,
            timeout=timeout,
        )
        if code != 0:
            logger.warning('yt-dlp failed for %s: %s', url, err)
            self.cleanup_job_dir(job_dir)
            if err == 'timeout':
                return ProcessResult(False, 'Превышено время ожидания обработки ссылки.')
            return ProcessResult(False, 'Не удалось извлечь аудио по этой ссылке.')

        downloaded_path = self._pick_downloaded_audio_file(job_dir)
        if downloaded_path is None:
            self.cleanup_job_dir(job_dir)
            return ProcessResult(False, 'После обработки ссылки аудиофайл не найден.')

        result = await self.prepare_uploaded_file(downloaded_path)
        if not result.ok:
            self.cleanup_job_dir(job_dir)
        return result

    async def prepare_uploaded_file(self, source_path: Path) -> ProcessResult:
        if not source_path.exists():
            return ProcessResult(False, 'Загруженный файл не найден.')
        if source_path.stat().st_size > self.settings.max_file_bytes:
            return ProcessResult(False, f'Файл больше {self.settings.max_file_mb} МБ.')
        if source_path.suffix and source_path.suffix.lower() not in ALLOWED_UPLOAD_EXTENSIONS:
            return ProcessResult(False, 'Формат файла не поддерживается для импорта.')
        has_audio_stream = await self.has_audio_stream(source_path)
        if not has_audio_stream:
            return ProcessResult(False, 'Файл не содержит корректного аудиопотока.')
        return await self._ensure_mp3(source_path)

    async def has_audio_stream(self, file_path: Path) -> bool:
        code, stdout, err = await self.run_command(
            'ffprobe',
            '-v',
            'quiet',
            '-print_format',
            'json',
            '-show_streams',
            str(file_path),
            timeout=min(self.settings.ffmpeg_timeout, 60),
        )
        if code != 0:
            logger.warning('ffprobe stream check failed for %s: %s', file_path, err)
            return False
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return False
        streams = payload.get('streams', [])
        return any(stream.get('codec_type') == 'audio' for stream in streams)

    async def _ensure_mp3(self, source_path: Path) -> ProcessResult:
        if source_path.suffix.lower() == '.mp3':
            metadata = await self.extract_metadata(source_path)
            title = metadata.title if metadata else source_path.stem
            return ProcessResult(
                True,
                'Готово',
                output_path=source_path,
                title=title,
                file_size=source_path.stat().st_size,
                metadata=metadata,
            )

        mp3_path = source_path.with_suffix('.mp3')
        code, _, err = await self.run_command(
            'ffmpeg',
            '-hide_banner',
            '-loglevel',
            'error',
            '-y',
            '-i',
            str(source_path),
            '-vn',
            '-sn',
            '-dn',
            '-map_metadata',
            '0',
            '-codec:a',
            'libmp3lame',
            '-b:a',
            '320k',
            str(mp3_path),
            timeout=self.settings.ffmpeg_timeout,
        )
        if code != 0:
            logger.warning('ffmpeg failed for %s: %s', source_path, err)
            if err == 'timeout':
                return ProcessResult(False, 'Превышено время ожидания конвертации.')
            return ProcessResult(False, 'Не удалось конвертировать файл в MP3.')
        if not mp3_path.exists():
            return ProcessResult(False, 'MP3-файл не был создан.')
        if mp3_path.stat().st_size > self.settings.max_file_bytes:
            return ProcessResult(False, f'Итоговый MP3 больше {self.settings.max_file_mb} МБ.')
        metadata = await self.extract_metadata(mp3_path)
        title = metadata.title if metadata else mp3_path.stem
        return ProcessResult(
            True,
            'Готово',
            output_path=mp3_path,
            title=title,
            file_size=mp3_path.stat().st_size,
            metadata=metadata,
        )

    async def extract_metadata(self, file_path: Path) -> AudioMetadata | None:
        code, stdout, err = await self.run_command(
            'ffprobe',
            '-v',
            'quiet',
            '-print_format',
            'json',
            '-show_format',
            '-show_streams',
            str(file_path),
            timeout=min(self.settings.ffmpeg_timeout, 60),
        )
        if code != 0:
            logger.warning('ffprobe failed for %s: %s', file_path, err)
            return None
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return None

        fmt = payload.get('format', {})
        tags = fmt.get('tags', {}) or {}
        streams = payload.get('streams', [])
        audio_stream = next((stream for stream in streams if stream.get('codec_type') == 'audio'), {})

        duration_raw = fmt.get('duration')
        duration_seconds = None
        if duration_raw is not None:
            try:
                duration_seconds = float(duration_raw)
            except (TypeError, ValueError):
                duration_seconds = None

        bitrate_raw = fmt.get('bit_rate')
        bitrate_kbps = None
        if bitrate_raw is not None:
            try:
                bitrate_kbps = int(int(bitrate_raw) / 1000)
            except (TypeError, ValueError):
                bitrate_kbps = None

        title = tags.get('title') or file_path.stem
        artist = tags.get('artist')
        album = tags.get('album')
        codec = audio_stream.get('codec_name')
        return AudioMetadata(
            title=title,
            artist=artist,
            album=album,
            duration_seconds=duration_seconds,
            bitrate_kbps=bitrate_kbps,
            codec=codec,
        )
