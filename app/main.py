from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from telegram import Bot, Message, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import Settings, load_settings
from .db import Database
from .keyboards import main_menu, pager, result_actions
from .logging_setup import setup_logging
from .services import AudioMetadata, AudioPipeline, ProcessResult
from .utils import (
    extract_url,
    html_code,
    html_escape,
    human_duration,
    human_size,
    looks_like_direct_audio_url,
    present_status,
    safe_filename,
    source_title_from_url,
)

logger = logging.getLogger(__name__)
PAGE_SIZE = 5
SEARCH_LIMIT = 10


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
        del ctx
        user = update.effective_user
        message = update.message
        if message is None:
            return
        if user:
            self.db.upsert_user(user.id, user.first_name, user.username)
        splash_path = self.brand_dir / 'start-splash.png'
        caption = (
            '<b>NexDownSave</b>\n'
            '<i>быстрый, чистый и надежный музыкальный utility-бот</i>\n\n'
            'Что внутри:\n'
            '• очередь задач без конфликтов\n'
            '• импорт аудиофайлов и прямых ссылок\n'
            '• автоматическая конвертация в MP3\n'
            '• история, избранное, поиск и диагностика\n\n'
            f'Текущий лимит файла: <b>{self.settings.max_file_mb} МБ</b>\n\n'
            'Отправь ссылку на аудиофайл или загрузи трек в чат.'
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

    async def cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        del ctx
        if update.message is None:
            return
        help_text = (
            '<b>Как работает NexDownSave</b>\n\n'
            '1. Пришли прямую ссылку на аудиофайл: '
            '<code>.mp3</code>, <code>.m4a</code>, <code>.wav</code>, <code>.ogg</code>, '
            '<code>.flac</code>, <code>.aac</code>, <code>.opus</code>, <code>.wma</code>, <code>.aiff</code>\n'
            '2. Или загрузи свой аудиофайл или документ прямо в чат\n'
            '3. Бот поставит задачу в очередь, проверит размер, аудиопоток и метаданные, затем конвертирует в MP3\n\n'
            'Дополнительно:\n'
            '• <code>/history</code> показывает историю с пагинацией\n'
            '• <code>/favorites</code> показывает избранное\n'
            '• <code>/search текст</code> ищет по истории и избранному\n'
            '• <code>/status</code> показывает лимиты и загрузку очереди'
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
            f"Успешных задач: <b>{summary['completed']}</b>\n"
            f"Неудачных задач: <b>{summary['failed']}</b>\n"
            f"Размер очереди: <b>{self.queue.qsize()}</b>",
            parse_mode=ParseMode.HTML,
        )

    def render_stats(self) -> str:
        stats = self.db.get_stats()
        return (
            '<b>Статистика NexDownSave</b>\n\n'
            f"Запросов: <b>{stats.get('requests', 0)}</b>\n"
            f"Прямых загрузок: <b>{stats.get('direct_downloads', 0)}</b>\n"
            f"Загруженных файлов: <b>{stats.get('uploaded_files', 0)}</b>\n"
            f"Добавлений в избранное: <b>{stats.get('favorites_added', 0)}</b>\n"
            f"Поисковых запросов: <b>{stats.get('search_requests', 0)}</b>\n"
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

    async def handle_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        del ctx
        message = update.message
        user = update.effective_user
        if message is None or user is None:
            return
        self.db.upsert_user(user.id, user.first_name, user.username)
        self.db.increment_stat('requests')

        url = extract_url(message.text or '')
        if not url:
            await message.reply_text('◌ Пришли прямую аудиоссылку или загрузи файл.', reply_markup=main_menu())
            return
        if not looks_like_direct_audio_url(url):
            await message.reply_text(
                '◌ NexDownSave принимает только прямые ссылки на аудиофайлы. Пришли ссылку с аудиорасширением или загрузи файл.',
                reply_markup=main_menu(),
            )
            return
        if self.queue.full():
            await self.reply_queue_busy(message)
            return

        history_id = self.db.add_history(user.id, 'url', url, source_title_from_url(url), 0, 'queued')
        await self.enqueue_job(
            message,
            QueueJob(
                user_id=user.id,
                chat_id=message.chat_id,
                history_id=history_id,
                source_type='url',
                source_value=url,
            ),
            '◌ Задача принята в очередь NexDownSave',
        )

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
                    result = await self.pipeline.download_direct_url(job.source_value)
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
        try:
            with result.output_path.open('rb') as audio_file:
                await bot.send_audio(
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
        await self.safe_delete_status_message(bot, job)

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
                'Пришли прямую ссылку на аудиофайл или загрузи аудио или документ. '
                'NexDownSave поставит задачу в очередь, проверит аудиопоток и вернет MP3.'
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
            if target.source_type != 'url':
                await message.reply_text('◌ Повтор доступен только для прямых ссылок.')
                return
            if self.queue.full():
                await self.reply_queue_busy(message)
                return
            new_history_id = self.db.add_history(user.id, 'url', target.source_value, target.title, 0, 'queued')
            await self.enqueue_job(
                message,
                QueueJob(
                    user_id=user.id,
                    chat_id=message.chat_id,
                    history_id=new_history_id,
                    source_type='url',
                    source_value=target.source_value,
                ),
                f'◌ Повторно добавлено в очередь NexDownSave\n└ {target.title}',
            )

    async def error_handler(self, update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        del update
        logger.exception('Unhandled error', exc_info=ctx.error)


async def on_post_init(application: Application) -> None:
    bot_app: BotApp = application.bot_data['bot_app']
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
    application.add_handler(CommandHandler('search', bot_app.cmd_search))
    application.add_handler(CommandHandler('admin', bot_app.cmd_admin))
    application.add_handler(CallbackQueryHandler(bot_app.handle_callback))
    application.add_handler(MessageHandler(filters.AUDIO | filters.Document.ALL, bot_app.handle_media))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot_app.handle_text))
    application.add_error_handler(bot_app.error_handler)

    logger.info(
        'NexDownSave started with queue_maxsize=%s history_limit=%s',
        settings.queue_maxsize,
        settings.history_limit,
    )
    application.run_polling(allowed_updates=Update.ALL_TYPES)
