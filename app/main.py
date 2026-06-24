from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import asdict, dataclass

from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InlineQueryResultCachedAudio,
    InputTextMessageContent,
    Message,
    Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    InlineQueryHandler,
    MessageHandler,
    filters,
)

from .config import Settings, load_settings
from .db import Database, HistoryItem
from .keyboards import main_menu, pager, result_actions, search_results
from .logging_setup import setup_logging
from .services import AudioMetadata, AudioPipeline, ProcessResult, SearchHit
from .vibe import VibeInterpreter
from .utils import (
    extract_url,
    html_code,
    html_escape,
    human_duration,
    human_size,
    present_status,
    safe_filename,
    source_title_from_url,
)

logger = logging.getLogger(__name__)
PAGE_SIZE = 5
SEARCH_LIMIT = 10
QUEUE_PREVIEW_LIMIT = 5
INLINE_CACHE_LIMIT = 20
SEARCH_CACHE_TTL_SECONDS = 86_400
DEEPLINK_QUERY_PREFIX = 'q'


@dataclass
class QueueJob:
    user_id: int
    chat_id: int
    history_id: int
    source_type: str
    source_value: str
    file_id: str | None = None
    file_name: str | None = None
    status_message_id: int | None = None


class BotApp:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db = Database(settings.db_path)
        self.pipeline = AudioPipeline(settings)
        self.brand_dir = self.settings.base_dir / 'assets' / 'brand'
        self.user_locks: dict[int, asyncio.Lock] = {}
        self.queue: asyncio.Queue[QueueJob] = asyncio.Queue(maxsize=settings.queue_maxsize)
        self.worker_task: asyncio.Task | None = None
        self.bot_username: str | None = None
        self.vibe = VibeInterpreter(settings)

    @staticmethod
    def new_token() -> str:
        return uuid.uuid4().hex[:12]

    def get_lock(self, user_id: int) -> asyncio.Lock:
        if user_id not in self.user_locks:
            self.user_locks[user_id] = asyncio.Lock()
        return self.user_locks[user_id]

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.settings.admin_user_ids

    async def start_worker(self, app: Application) -> None:
        if self.worker_task is None:
            self.worker_task = asyncio.create_task(self.worker_loop(app))

    async def stop_worker(self) -> None:
        if self.worker_task is not None:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
            self.worker_task = None

    async def worker_loop(self, app: Application) -> None:
        while True:
            job = await self.queue.get()
            try:
                await self.process_job(app, job)
            except Exception:
                logger.exception('Queue job failed outside guarded flow')
                self.db.increment_stat('errors')
                self.db.update_history_status(job.history_id, 'failed')
            finally:
                self.queue.task_done()
                await asyncio.sleep(self.settings.queue_poll_interval)

    async def safe_edit_status_message(self, bot: Bot, job: QueueJob, text: str) -> None:
        if job.status_message_id is None:
            return
        try:
            await bot.edit_message_text(
                chat_id=job.chat_id,
                message_id=job.status_message_id,
                text=text,
            )
        except BadRequest as exc:
            message = str(exc).lower()
            if 'message is not modified' in message or 'message to edit not found' in message:
                return
            logger.warning('Could not edit status message for history_id=%s: %s', job.history_id, exc)
        except (Forbidden, TelegramError) as exc:
            logger.warning('Could not edit status message for history_id=%s: %s', job.history_id, exc)

    async def safe_delete_status_message(self, bot: Bot, job: QueueJob) -> None:
        if job.status_message_id is None:
            return
        try:
            await bot.delete_message(chat_id=job.chat_id, message_id=job.status_message_id)
        except BadRequest as exc:
            if 'message to delete not found' in str(exc).lower():
                return
            logger.warning('Could not delete status message for history_id=%s: %s', job.history_id, exc)
        except (Forbidden, TelegramError) as exc:
            logger.warning('Could not delete status message for history_id=%s: %s', job.history_id, exc)

    async def fail_job(self, bot: Bot, job: QueueJob, message: str) -> None:
        self.db.increment_stat('errors')
        self.db.update_history_status(job.history_id, 'failed')
        await self.safe_edit_status_message(bot, job, message)

    async def reply_queue_busy(self, message: Message) -> None:
        await message.reply_text(
            '◌ Очередь NexDownSave временно перегружена.\n'
            f'└ Лимит задач: {self.settings.queue_maxsize}. Попробуй позже.',
            reply_markup=main_menu(),
        )

    def cancel_pending_jobs(self, user_id: int) -> list[QueueJob]:
        queue_store = self.queue._queue
        removed: list[QueueJob] = []
        retained: list[QueueJob] = []
        for queued_job in list(queue_store):
            if queued_job.user_id == user_id:
                removed.append(queued_job)
            else:
                retained.append(queued_job)
        if not removed:
            return []
        queue_store.clear()
        queue_store.extend(retained)
        for queued_job in removed:
            self.db.update_history_status(queued_job.history_id, 'cancelled')
            self.queue.task_done()
        return removed

    async def enqueue_job(self, message: Message, job: QueueJob, accepted_text: str) -> None:
        status_message = await message.reply_text(f'{accepted_text}\n└ Позиция: {self.queue.qsize() + 1}')
        job.status_message_id = status_message.message_id
        try:
            self.queue.put_nowait(job)
        except asyncio.QueueFull:
            self.db.increment_stat('errors')
            self.db.update_history_status(job.history_id, 'failed')
            await status_message.edit_text(
                '◌ Очередь NexDownSave временно перегружена.\n'
                f'└ Лимит задач: {self.settings.queue_maxsize}. Попробуй позже.'
            )

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        message = update.message
        if message is None:
            return
        if user:
            self.db.upsert_user(user.id, user.first_name, user.username)
        if await self.handle_start_deeplink(message, ctx):
            return
        splash_path = self.brand_dir / 'start-splash.png'
        inline_hint = f'@{self.bot_username} трек' if self.bot_username else '@бот трек'
        caption = (
            '<b>NexDownSave</b>\n'
            '<i>быстрый, чистый и надежный музыкальный utility-бот</i>\n\n'
            'Что внутри:\n'
            '• <b>поиск по названию</b> — просто напиши, что ищешь\n'
            '• <b>подбор по вайбу</b> — <code>/vibe дождливая ночь, инструментал</code>\n'
            f'• <b>inline-режим</b> — <code>{html_escape(inline_hint)}</code> в любом чате\n'
            '• очередь задач без конфликтов\n'
            '• страницы треков, прямые аудиоссылки и загрузки файлов\n'
            '• мгновенная повторная отправка из кеша\n'
            '• история, избранное, очередь и диагностика\n\n'
            f'Текущий лимит файла: <b>{self.settings.max_file_mb} МБ</b>\n\n'
            'Напиши название трека, пришли ссылку или загрузи аудиофайл в чат.'
        )
        if splash_path.exists():
            with splash_path.open('rb') as image_file:
                await message.reply_photo(
                    photo=image_file,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=main_menu(),
                )
            return
        await message.reply_text(caption, parse_mode=ParseMode.HTML, reply_markup=main_menu())

    async def handle_start_deeplink(self, message: Message, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
        args = getattr(ctx, 'args', None) or []
        if not args:
            return False
        payload = args[0]
        if not payload.startswith(DEEPLINK_QUERY_PREFIX):
            return False
        token = payload[len(DEEPLINK_QUERY_PREFIX):]
        cached = self.db.get_search_cache(token)
        if cached is None:
            return False
        try:
            data = json.loads(cached)
        except json.JSONDecodeError:
            return False
        query = data.get('q') if isinstance(data, dict) else None
        if not query:
            return False
        await self.deliver_search(message, query)
        return True

    async def cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        del ctx
        if update.message is None:
            return
        help_text = (
            '<b>Как работает NexDownSave</b>\n\n'
            '1. Напиши <b>название трека</b> — бот покажет варианты, выбери номер\n'
            '2. Или пришли ссылку / прямую ссылку на аудиофайл\n'
            '3. Или загрузи свой аудиофайл или документ прямо в чат\n'
            '4. Бот поставит задачу в очередь, извлечёт аудио и отправит MP3\n\n'
            'В любом чате работает <b>inline-режим</b>: набери имя бота и название трека.\n\n'
            'Подбор по настроению: <code>/vibe дождливая ночь, инструментал</code> — '
            'бот поймёт вайб и соберёт подборку (с учётом твоей истории).\n\n'
            'Дополнительно:\n'
            '• <code>/queue</code> показывает твои ожидающие задачи\n'
            '• <code>/history</code> показывает историю с пагинацией\n'
            '• <code>/favorites</code> показывает избранное\n'
            '• <code>/search текст</code> ищет по истории и избранному\n'
            '• кнопка «Повторить» работает и для ссылок, и для загруженных файлов'
        )
        await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

    async def cmd_stats(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        del ctx
        if update.message is None:
            return
        await update.message.reply_text(self.render_stats(), parse_mode=ParseMode.HTML)

    async def cmd_history(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        del ctx
        user = update.effective_user
        if user is None or update.message is None:
            return
        text, markup = self.render_history_page(user.id, 1)
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)

    async def cmd_favorites(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        del ctx
        user = update.effective_user
        if user is None or update.message is None:
            return
        text, markup = self.render_favorites_page(user.id, 1)
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)

    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        del ctx
        if update.message is None:
            return
        await update.message.reply_text(self.render_status(), parse_mode=ParseMode.HTML)

    async def cmd_queue(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        del ctx
        user = update.effective_user
        if user is None or update.message is None:
            return
        await update.message.reply_text(self.render_queue_overview(user.id), parse_mode=ParseMode.HTML)

    async def cmd_cancel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        del ctx
        user = update.effective_user
        if user is None or update.message is None:
            return
        removed = self.cancel_pending_jobs(user.id)
        if not removed:
            await update.message.reply_text('◌ У тебя нет ожидающих задач для отмены.', reply_markup=main_menu())
            return
        await update.message.reply_text(
            '◆ Очередь очищена\n'
            f'└ Снято задач: {len(removed)}',
            reply_markup=main_menu(),
        )

    async def cmd_search(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if user is None or update.message is None:
            return
        query = ' '.join(ctx.args).strip()
        if not query:
            await update.message.reply_text(
                'Используй <code>/search название</code> для поиска по истории и избранному.',
                parse_mode=ParseMode.HTML,
            )
            return
        self.db.increment_stat('search_requests')
        await update.message.reply_text(self.render_search(user.id, query), parse_mode=ParseMode.HTML)

    async def cmd_admin(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        del ctx
        user = update.effective_user
        if update.message is None or user is None:
            return
        if not self.is_admin(user.id):
            await update.message.reply_text('Требуется доступ администратора.')
            return
        summary = self.db.get_global_summary()
        await update.message.reply_text(
            '<b>NexDownSave Admin</b>\n\n'
            f"Пользователей: <b>{summary['users']}</b>\n"
            f"Записей истории: <b>{summary['history_items']}</b>\n"
            f"Избранного: <b>{summary['favorites']}</b>\n"
            f"Задач в ожидании: <b>{summary['queued']}</b>\n"
            f"Успешных задач: <b>{summary['completed']}</b>\n"
            f"Неудачных задач: <b>{summary['failed']}</b>\n"
            f"Размер очереди в памяти: <b>{self.queue.qsize()}</b>",
            parse_mode=ParseMode.HTML,
        )

    def render_stats(self) -> str:
        stats = self.db.get_stats()
        return (
            '<b>Статистика NexDownSave</b>\n\n'
            f"Запросов: <b>{stats.get('requests', 0)}</b>\n"
            f"Обработано ссылок: <b>{stats.get('direct_downloads', 0)}</b>\n"
            f"Загруженных файлов: <b>{stats.get('uploaded_files', 0)}</b>\n"
            f"Добавлений в избранное: <b>{stats.get('favorites_added', 0)}</b>\n"
            f"Поисковых запросов: <b>{stats.get('search_requests', 0)}</b>\n"
            f"Inline-запросов: <b>{stats.get('inline_requests', 0)}</b>\n"
            f"Подборок по вайбу: <b>{stats.get('vibe_requests', 0)}</b>\n"
            f"Ошибок: <b>{stats.get('errors', 0)}</b>\n"
            f"Пользователей: <b>{stats.get('users', 0)}</b>\n"
            f"Записей истории: <b>{stats.get('history', 0)}</b>\n"
            f"Элементов в избранном: <b>{stats.get('favorites', 0)}</b>"
        )

    def render_history_page(self, user_id: int, page: int) -> tuple[str, object]:
        items, pages = self.db.get_history_page(user_id, page, PAGE_SIZE)
        if not items:
            return 'История NexDownSave пока пуста.', main_menu()
        lines = ['<b>Последние задачи</b>']
        for item in items:
            lines.append(
                f"• {html_code(item.title)} | <code>{html_escape(present_status(item.status))}</code> | {html_escape(item.created_at)}"
            )
        return '\n'.join(lines), pager('history', page, pages)

    def render_favorites_page(self, user_id: int, page: int) -> tuple[str, object]:
        items, pages = self.db.get_favorites_page(user_id, page, PAGE_SIZE)
        if not items:
            return 'В избранном пока ничего нет.', main_menu()
        lines = ['<b>Избранное NexDownSave</b>']
        for item in items:
            lines.append(f"• {html_code(item.title)} | {html_escape(item.created_at)}")
        return '\n'.join(lines), pager('favorites', page, pages)

    def render_search(self, user_id: int, query: str) -> str:
        history_items = self.db.search_history(user_id, query, SEARCH_LIMIT)
        favorite_items = self.db.search_favorites(user_id, query, SEARCH_LIMIT)
        if not history_items and not favorite_items:
            return f'Ничего не найдено по запросу: {html_code(query)}'
        lines = [f'<b>Поиск:</b> {html_code(query)}']
        if history_items:
            lines.append('')
            lines.append('<b>История</b>')
            for item in history_items:
                lines.append(f"• {html_code(item.title)} | <code>{html_escape(present_status(item.status))}</code>")
        if favorite_items:
            lines.append('')
            lines.append('<b>Избранное</b>')
            for item in favorite_items:
                lines.append(f"• {html_code(item.title)}")
        return '\n'.join(lines)

    def render_status(self) -> str:
        return (
            '<b>Состояние NexDownSave</b>\n\n'
            f'• Очередь: <b>{self.queue.qsize()}</b> из <b>{self.settings.queue_maxsize}</b>\n'
            f'• Повторных попыток: <b>{self.settings.retry_attempts}</b>\n'
            f'• Лимит файла: <b>{self.settings.max_file_mb} МБ</b>\n'
            f'• Таймаут скачивания: <b>{self.settings.download_timeout} сек</b>\n'
            f'• Таймаут ffmpeg: <b>{self.settings.ffmpeg_timeout} сек</b>\n'
            f'• Интервал опроса очереди: <b>{self.settings.queue_poll_interval:.1f} сек</b>'
        )

    def render_queue_overview(self, user_id: int) -> str:
        queued_total = self.db.count_history_by_status(user_id, 'queued')
        queued_items = self.db.get_history_by_status(user_id, 'queued', QUEUE_PREVIEW_LIMIT)
        lines = [
            '<b>Очередь NexDownSave</b>',
            '',
            f'Глобальная очередь: <b>{self.queue.qsize()}</b> из <b>{self.settings.queue_maxsize}</b>',
            f'Твои ожидающие задачи: <b>{queued_total}</b>',
            'Для очистки используй <code>/cancel</code> или кнопку ниже.',
        ]
        if queued_items:
            lines.append('')
            lines.append('<b>Последние ожидающие задачи</b>')
            for item in queued_items:
                lines.append(f"• {html_code(item.title)} | {html_escape(item.created_at)}")
        else:
            lines.append('')
            lines.append('У тебя нет задач в ожидании.')
        return '\n'.join(lines)

    def render_metadata_card(self, metadata: AudioMetadata | None, file_size: int) -> str:
        details = [f'Размер: {human_size(file_size)}']
        if metadata is not None:
            if metadata.artist:
                details.append(f'Исполнитель: {metadata.artist}')
            if metadata.album:
                details.append(f'Альбом: {metadata.album}')
            duration = human_duration(metadata.duration_seconds)
            if duration:
                details.append(f'Длительность: {duration}')
            if metadata.bitrate_kbps:
                details.append(f'Битрейт: {metadata.bitrate_kbps} kbps')
            if metadata.codec:
                details.append(f'Кодек: {metadata.codec}')
        lines = ['◆ NexDownSave']
        for index, detail in enumerate(details):
            connector = '└' if index == len(details) - 1 else '├'
            lines.append(f'{connector} {detail}')
        return '\n'.join(lines)

    def build_repeat_job(self, message: Message, user_id: int, target: HistoryItem) -> tuple[int, QueueJob, str] | None:
        new_history_id = self.db.add_history(user_id, target.source_type, target.source_value, target.title, 0, 'queued')
        if target.source_type == 'url':
            return (
                new_history_id,
                QueueJob(
                    user_id=user_id,
                    chat_id=message.chat_id,
                    history_id=new_history_id,
                    source_type='url',
                    source_value=target.source_value,
                ),
                f'◌ Повторно добавлено в очередь NexDownSave\n└ {target.title}',
            )
        if target.source_type == 'upload':
            return (
                new_history_id,
                QueueJob(
                    user_id=user_id,
                    chat_id=message.chat_id,
                    history_id=new_history_id,
                    source_type='upload',
                    source_value=target.source_value,
                    file_id=target.source_value,
                    file_name=target.title or f'upload_{target.id}',
                ),
                f'◌ Повторно добавлено в очередь NexDownSave\n└ {target.title}',
            )
        self.db.update_history_status(new_history_id, 'failed')
        return None

    async def handle_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        del ctx
        message = update.message
        user = update.effective_user
        if message is None or user is None:
            return
        self.db.upsert_user(user.id, user.first_name, user.username)
        self.db.increment_stat('requests')

        text = (message.text or '').strip()
        url = extract_url(text)
        if url:
            await self.submit_url(
                message,
                user.id,
                url,
                source_title_from_url(url),
                '◌ Ссылка принята в очередь NexDownSave',
            )
            return

        if not text:
            await message.reply_text(
                '◌ Пришли ссылку на трек, название для поиска или загрузи файл.',
                reply_markup=main_menu(),
            )
            return
        await self.deliver_search(message, text)

    async def submit_url(
        self,
        message: Message,
        user_id: int,
        url: str,
        title: str,
        accepted_text: str,
    ) -> None:
        if await self.try_send_cached(message.get_bot(), message.chat_id, user_id, url):
            return
        if self.queue.full():
            await self.reply_queue_busy(message)
            return
        history_id = self.db.add_history(user_id, 'url', url, title, 0, 'queued')
        await self.enqueue_job(
            message,
            QueueJob(
                user_id=user_id,
                chat_id=message.chat_id,
                history_id=history_id,
                source_type='url',
                source_value=url,
            ),
            accepted_text,
        )

    async def try_send_cached(self, bot: Bot, chat_id: int, user_id: int, url: str) -> bool:
        track = self.db.get_track(url)
        if track is None:
            return False
        history_id = self.db.add_history(user_id, 'url', url, track.title, 0, 'done')
        try:
            await bot.send_audio(
                chat_id=chat_id,
                audio=track.tg_file_id,
                title=track.title,
                performer=track.performer,
                caption='◆ NexDownSave\n└ Мгновенно из кеша',
                reply_markup=result_actions(history_id),
            )
        except (BadRequest, Forbidden, TelegramError) as exc:
            logger.warning('Cached send failed for %s: %s', url, exc)
            self.db.update_history_status(history_id, 'failed')
            return False
        self.db.update_history_status(history_id, 'done', file_size=0, title=track.title)
        self.db.increment_stat('direct_downloads')
        return True

    async def deliver_search(self, message: Message, query: str) -> None:
        self.db.increment_stat('search_requests')
        await message.get_bot().send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)
        hits = await self.pipeline.search_tracks(query, self.settings.search_results)
        if not hits:
            await message.reply_text(
                f'◌ По запросу {html_code(query)} ничего не найдено.\n'
                '└ Уточни название или пришли прямую ссылку.',
                parse_mode=ParseMode.HTML,
                reply_markup=main_menu(),
            )
            return
        token = self.new_token()
        self.db.prune_search_cache(SEARCH_CACHE_TTL_SECONDS)
        self.db.save_search_cache(token, json.dumps([asdict(hit) for hit in hits]))
        await message.reply_text(
            self.render_search_results(query, hits),
            parse_mode=ParseMode.HTML,
            reply_markup=search_results(token, len(hits)),
        )

    def render_search_results(self, query: str, hits: list[SearchHit]) -> str:
        lines = [f'<b>Результаты поиска:</b> {html_code(query)}', '']
        for index, hit in enumerate(hits, start=1):
            meta_parts = []
            if hit.uploader:
                meta_parts.append(hit.uploader)
            duration = human_duration(hit.duration_seconds)
            if duration:
                meta_parts.append(duration)
            lines.append(f'<b>{index}.</b> {html_escape(hit.title)}')
            if meta_parts:
                lines.append(f'   <i>{html_escape(" · ".join(meta_parts))}</i>')
        lines.append('')
        lines.append('Нажми номер трека, чтобы скачать.')
        return '\n'.join(lines)

    async def cmd_vibe(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if user is None or update.message is None:
            return
        self.db.upsert_user(user.id, user.first_name, user.username)
        query = ' '.join(ctx.args).strip()
        await self.deliver_vibe(update.message, user.id, query)

    async def deliver_vibe(self, message: Message, user_id: int, query: str) -> None:
        taste = self.db.get_taste_profile(user_id, 8)
        if not query and not taste:
            await message.reply_text(
                '◌ Опиши настроение или вайб после команды, например:\n'
                '<code>/vibe дождливая ночь, инструментал, ~90 BPM</code>\n'
                'Когда у тебя появится история — смогу подбирать и под твой вкус.',
                parse_mode=ParseMode.HTML,
                reply_markup=main_menu(),
            )
            return
        self.db.increment_stat('vibe_requests')
        await message.get_bot().send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)
        vibe = await self.vibe.interpret(query, taste)
        hits = await self.aggregate_vibe_hits(vibe.queries)
        if not hits:
            await message.reply_text(
                f'◌ Не удалось собрать подборку под {html_code(query or "твой вкус")}.\n'
                '└ Попробуй описать вайб другими словами.',
                parse_mode=ParseMode.HTML,
                reply_markup=main_menu(),
            )
            return
        token = self.new_token()
        self.db.prune_search_cache(SEARCH_CACHE_TTL_SECONDS)
        self.db.save_search_cache(token, json.dumps([asdict(hit) for hit in hits]))
        await message.reply_text(
            self.render_vibe_results(vibe.interpretation, hits),
            parse_mode=ParseMode.HTML,
            reply_markup=search_results(token, len(hits)),
        )

    async def aggregate_vibe_hits(self, queries: list[SearchHit] | list[str]) -> list[SearchHit]:
        if not queries:
            return []
        per_query = max(2, (self.settings.vibe_results // len(queries)) + 2)
        searches = await asyncio.gather(
            *(self.pipeline.search_tracks(query, per_query) for query in queries),
            return_exceptions=True,
        )
        result_lists: list[list[SearchHit]] = []
        for outcome in searches:
            if isinstance(outcome, Exception):
                logger.warning('Vibe sub-search failed: %s', outcome)
                continue
            result_lists.append(outcome)
        # Round-robin interleave so the podborka stays diverse across queries.
        merged: list[SearchHit] = []
        seen: set[str] = set()
        position = 0
        while len(merged) < self.settings.vibe_results:
            advanced = False
            for hits in result_lists:
                if position < len(hits):
                    advanced = True
                    hit = hits[position]
                    if hit.video_id not in seen:
                        seen.add(hit.video_id)
                        merged.append(hit)
                        if len(merged) >= self.settings.vibe_results:
                            break
            if not advanced:
                break
            position += 1
        return merged

    def render_vibe_results(self, interpretation: str, hits: list[SearchHit]) -> str:
        lines = [f'<b>◆ Подборка по вайбу</b>\n<i>{html_escape(interpretation)}</i>', '']
        for index, hit in enumerate(hits, start=1):
            meta_parts = []
            if hit.uploader:
                meta_parts.append(hit.uploader)
            duration = human_duration(hit.duration_seconds)
            if duration:
                meta_parts.append(duration)
            lines.append(f'<b>{index}.</b> {html_escape(hit.title)}')
            if meta_parts:
                lines.append(f'   <i>{html_escape(" · ".join(meta_parts))}</i>')
        lines.append('')
        lines.append('Нажми номер трека, чтобы скачать.')
        return '\n'.join(lines)

    async def handle_media(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        del ctx
        message = update.message
        user = update.effective_user
        if message is None or user is None:
            return
        self.db.upsert_user(user.id, user.first_name, user.username)
        self.db.increment_stat('requests')

        media = message.audio or message.document
        if media is None:
            return
        file_size = getattr(media, 'file_size', None)
        if file_size is not None and file_size > self.settings.max_file_bytes:
            await message.reply_text(f'◌ Файл больше {self.settings.max_file_mb} МБ и не будет принят в очередь.')
            return
        if self.queue.full():
            await self.reply_queue_busy(message)
            return

        file_name = getattr(media, 'file_name', None)
        title = file_name or getattr(media, 'title', None) or 'upload'
        history_id = self.db.add_history(
            user.id,
            'upload',
            media.file_id,
            title,
            0,
            'queued',
        )
        await self.enqueue_job(
            message,
            QueueJob(
                user_id=user.id,
                chat_id=message.chat_id,
                history_id=history_id,
                source_type='upload',
                source_value=media.file_id,
                file_id=media.file_id,
                file_name=file_name or f'upload_{media.file_unique_id}',
            ),
            '◌ Файл принят в очередь NexDownSave',
        )

    async def process_job(self, app: Application, job: QueueJob) -> None:
        bot = app.bot
        async with self.get_lock(job.user_id):
            try:
                await self.safe_edit_status_message(
                    bot,
                    job,
                    '◌ NexDownSave обрабатывает задачу\n└ Подготавливаю аудио...',
                )
                await bot.send_chat_action(chat_id=job.chat_id, action=ChatAction.UPLOAD_DOCUMENT)

                if job.source_type == 'url':
                    result = await self.pipeline.download_track_url(job.source_value)
                    if not result.ok or result.output_path is None or result.title is None:
                        await self.fail_job(bot, job, result.message)
                        return
                    await self.send_result(bot, job, result)
                    self.db.increment_stat('direct_downloads')
                    return

                if job.source_type == 'upload' and job.file_id is not None and job.file_name is not None:
                    job_dir = self.pipeline.reserve_job_dir()
                    try:
                        local_path = job_dir / safe_filename(job.file_name)
                        telegram_file = await bot.get_file(job.file_id)
                        await telegram_file.download_to_drive(custom_path=str(local_path))
                        result = await self.pipeline.prepare_uploaded_file(local_path)
                        if not result.ok or result.output_path is None or result.title is None:
                            await self.fail_job(bot, job, result.message)
                            return
                        await self.send_result(bot, job, result)
                        self.db.increment_stat('uploaded_files')
                        return
                    finally:
                        self.pipeline.cleanup_job_dir(job_dir)

                await self.fail_job(bot, job, 'Неподдерживаемый тип задачи.')
            except Exception:
                logger.exception('Queue job failed for history_id=%s', job.history_id)
                await self.fail_job(
                    bot,
                    job,
                    '◌ Внутренняя ошибка NexDownSave\n└ Попробуй еще раз позже.',
                )

    async def send_result(self, bot: Bot, job: QueueJob, result: ProcessResult) -> None:
        if result.output_path is None or result.title is None:
            return
        caption = self.render_metadata_card(result.metadata, result.file_size)
        performer = result.metadata.artist if result.metadata and result.metadata.artist else None
        await self.safe_edit_status_message(
            bot,
            job,
            f'◌ NexDownSave отправляет результат\n└ Размер: {human_size(result.file_size)}',
        )
        sent_message: Message | None = None
        try:
            with result.output_path.open('rb') as audio_file:
                sent_message = await bot.send_audio(
                    chat_id=job.chat_id,
                    audio=audio_file,
                    filename=result.output_path.name,
                    title=result.title,
                    performer=performer,
                    caption=caption,
                    reply_markup=result_actions(job.history_id),
                )
        finally:
            if result.output_path.parent.exists():
                self.pipeline.cleanup_job_dir(result.output_path.parent)
        self.db.update_history_status(job.history_id, 'done', file_size=result.file_size, title=result.title)
        self.cache_sent_track(job, result, performer, sent_message)
        await self.safe_delete_status_message(bot, job)

    def cache_sent_track(
        self,
        job: QueueJob,
        result: ProcessResult,
        performer: str | None,
        sent_message: Message | None,
    ) -> None:
        if job.source_type != 'url' or sent_message is None or sent_message.audio is None:
            return
        if result.title is None:
            return
        duration = None
        if result.metadata and result.metadata.duration_seconds is not None:
            duration = int(result.metadata.duration_seconds)
        self.db.upsert_track(
            job.source_value,
            result.title,
            performer,
            duration,
            sent_message.audio.file_id,
        )

    @staticmethod
    def parse_callback_int(data: str, prefix: str) -> int | None:
        if not data.startswith(prefix):
            return None
        try:
            value = int(data.split(':', 1)[1])
        except ValueError:
            return None
        return value if value > 0 else None

    async def handle_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        del ctx
        query = update.callback_query
        user = update.effective_user
        message = query.message if query is not None else None
        if query is None or user is None or message is None:
            return
        await query.answer()

        data = query.data or ''
        if data == 'noop':
            return
        if data == 'menu:main':
            await message.reply_text('Главное меню NexDownSave', reply_markup=main_menu())
            return
        if data == 'menu:help':
            await message.reply_text(
                'Пришли ссылку на страницу трека, прямую аудиоссылку или загрузи аудио/документ. '
                'NexDownSave попробует извлечь аудио и вернет MP3.'
            )
            return
        if data == 'menu:stats':
            await message.reply_text(self.render_stats(), parse_mode=ParseMode.HTML)
            return
        if data == 'menu:search':
            await message.reply_text(
                'Используй <code>/search название</code> для поиска по истории и избранному.',
                parse_mode=ParseMode.HTML,
            )
            return
        if data == 'menu:vibe':
            await message.reply_text(
                'Опиши настроение или занятие — соберу подборку.\n'
                '<code>/vibe дождливая ночь, инструментал, ~90 BPM</code>\n'
                'Пустой <code>/vibe</code> подберёт под твою историю прослушиваний.',
                parse_mode=ParseMode.HTML,
            )
            return
        if data == 'menu:queue':
            await message.reply_text(self.render_queue_overview(user.id), parse_mode=ParseMode.HTML)
            return
        if data == 'menu:cancel':
            removed = self.cancel_pending_jobs(user.id)
            if not removed:
                await message.reply_text('◌ У тебя нет ожидающих задач для отмены.', reply_markup=main_menu())
                return
            await message.reply_text(
                '◆ Очередь очищена\n'
                f'└ Снято задач: {len(removed)}',
                reply_markup=main_menu(),
            )
            return
        if data == 'menu:status':
            await message.reply_text(self.render_status(), parse_mode=ParseMode.HTML)
            return
        if data.startswith('history:'):
            page = self.parse_callback_int(data, 'history:')
            if page is None:
                return
            text, markup = self.render_history_page(user.id, page)
            await query.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=markup)
            return
        if data.startswith('favorites:'):
            page = self.parse_callback_int(data, 'favorites:')
            if page is None:
                return
            text, markup = self.render_favorites_page(user.id, page)
            await query.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=markup)
            return
        if data.startswith('fav:'):
            history_id = self.parse_callback_int(data, 'fav:')
            if history_id is None:
                return
            target = self.db.get_history_item(user.id, history_id)
            if target is None:
                await message.reply_text('◌ Запись истории не найдена.')
                return
            created = self.db.add_favorite(user.id, target.source_type, target.source_value, target.title)
            if created:
                self.db.increment_stat('favorites_added')
                await message.reply_text(f'◆ Добавлено в избранное NexDownSave\n└ {target.title}')
            else:
                await message.reply_text('◌ Этот элемент уже есть в избранном.')
            return
        if data.startswith('repeat:'):
            history_id = self.parse_callback_int(data, 'repeat:')
            if history_id is None:
                return
            target = self.db.get_history_item(user.id, history_id)
            if target is None:
                await message.reply_text('◌ Запись истории не найдена.')
                return
            if target.source_type == 'url':
                await self.submit_url(
                    message,
                    user.id,
                    target.source_value,
                    target.title,
                    f'◌ Повторно добавлено в очередь NexDownSave\n└ {target.title}',
                )
                return
            if self.queue.full():
                await self.reply_queue_busy(message)
                return
            payload = self.build_repeat_job(message, user.id, target)
            if payload is None:
                await message.reply_text('◌ Повтор для этого типа задачи не поддерживается.')
                return
            _, job, accepted_text = payload
            await self.enqueue_job(message, job, accepted_text)
            return
        if data.startswith('dl:'):
            await self.handle_download_choice(message, user.id, data)
            return

    async def handle_download_choice(self, message: Message, user_id: int, data: str) -> None:
        parts = data.split(':', 2)
        if len(parts) != 3:
            return
        _, token, raw_index = parts
        hit = self.lookup_search_hit(token, raw_index)
        if hit is None:
            await message.reply_text(
                '◌ Результаты поиска устарели.\n└ Повтори поиск и выбери трек заново.',
                reply_markup=main_menu(),
            )
            return
        await self.submit_url(
            message,
            user_id,
            hit.url,
            hit.title,
            f'◌ Трек принят в очередь NexDownSave\n└ {hit.title}',
        )

    def lookup_search_hit(self, token: str, raw_index: str) -> SearchHit | None:
        try:
            index = int(raw_index)
        except ValueError:
            return None
        payload = self.db.get_search_cache(token)
        if payload is None:
            return None
        try:
            entries = json.loads(payload)
        except json.JSONDecodeError:
            return None
        if not isinstance(entries, list) or not 0 <= index < len(entries):
            return None
        try:
            return SearchHit(**entries[index])
        except (TypeError, ValueError):
            return None

    async def handle_inline(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        del ctx
        inline_query = update.inline_query
        if inline_query is None:
            return
        query = (inline_query.query or '').strip()
        self.db.increment_stat('inline_requests')
        results: list[object] = []
        if not query:
            results.append(
                InlineQueryResultArticle(
                    id=self.new_token(),
                    title='Введите название трека',
                    description='NexDownSave найдёт и отправит музыку',
                    input_message_content=InputTextMessageContent(
                        '🔎 Поиск музыки через @{bot}'.format(bot=self.bot_username or 'NexDownSave')
                    ),
                )
            )
            await inline_query.answer(results, cache_time=5, is_personal=True)
            return

        for track in self.db.search_cached_tracks(query, INLINE_CACHE_LIMIT):
            results.append(
                InlineQueryResultCachedAudio(
                    id=self.new_token(),
                    audio_file_id=track.tg_file_id,
                    caption='◆ NexDownSave',
                )
            )
        results.append(self.build_search_deeplink_result(query))
        await inline_query.answer(results, cache_time=10, is_personal=True)

    def build_search_deeplink_result(self, query: str) -> InlineQueryResultArticle:
        token = self.new_token()
        self.db.prune_search_cache(SEARCH_CACHE_TTL_SECONDS)
        self.db.save_search_cache(token, json.dumps({'q': query}))
        bot_name = self.bot_username or 'NexDownSave'
        deeplink = f'https://t.me/{bot_name}?start={DEEPLINK_QUERY_PREFIX}{token}'
        return InlineQueryResultArticle(
            id=self.new_token(),
            title=f'🔎 Найти «{query}» в NexDownSave',
            description='Открыть бота и скачать трек в MP3',
            input_message_content=InputTextMessageContent(f'🔎 Поиск трека: {query}'),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton('Открыть NexDownSave', url=deeplink)]]
            ),
        )

    async def error_handler(self, update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        del update
        logger.exception('Unhandled error', exc_info=ctx.error)


async def on_post_init(application: Application) -> None:
    bot_app: BotApp = application.bot_data['bot_app']
    try:
        me = await application.bot.get_me()
        bot_app.bot_username = me.username
    except TelegramError as exc:
        logger.warning('Could not resolve bot username: %s', exc)
    await bot_app.start_worker(application)


async def on_shutdown(application: Application) -> None:
    bot_app: BotApp = application.bot_data['bot_app']
    await bot_app.stop_worker()


def main() -> None:
    settings = load_settings()
    setup_logging(settings)

    if not settings.bot_token:
        raise SystemExit('Укажи BOT_TOKEN перед запуском NexDownSave')

    bot_app = BotApp(settings)
    missing = bot_app.pipeline.check_dependencies()
    if missing:
        raise SystemExit(f"Не найдены системные зависимости: {', '.join(missing)}")

    application = (
        Application.builder()
        .token(settings.bot_token)
        .concurrent_updates(False)
        .post_init(on_post_init)
        .post_shutdown(on_shutdown)
        .build()
    )
    application.bot_data['bot_app'] = bot_app
    application.add_handler(CommandHandler('start', bot_app.cmd_start))
    application.add_handler(CommandHandler('help', bot_app.cmd_help))
    application.add_handler(CommandHandler('stats', bot_app.cmd_stats))
    application.add_handler(CommandHandler('history', bot_app.cmd_history))
    application.add_handler(CommandHandler('favorites', bot_app.cmd_favorites))
    application.add_handler(CommandHandler('status', bot_app.cmd_status))
    application.add_handler(CommandHandler('queue', bot_app.cmd_queue))
    application.add_handler(CommandHandler('cancel', bot_app.cmd_cancel))
    application.add_handler(CommandHandler('search', bot_app.cmd_search))
    application.add_handler(CommandHandler('vibe', bot_app.cmd_vibe))
    application.add_handler(CommandHandler('admin', bot_app.cmd_admin))
    application.add_handler(CallbackQueryHandler(bot_app.handle_callback))
    application.add_handler(InlineQueryHandler(bot_app.handle_inline))
    application.add_handler(MessageHandler(filters.AUDIO | filters.Document.ALL, bot_app.handle_media))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot_app.handle_text))
    application.add_error_handler(bot_app.error_handler)

    logger.info(
        'NexDownSave started with queue_maxsize=%s history_limit=%s',
        settings.queue_maxsize,
        settings.history_limit,
    )
    application.run_polling(allowed_updates=Update.ALL_TYPES)
