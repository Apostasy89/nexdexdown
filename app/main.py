from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from telegram import Update
from telegram.constants import ChatAction, ParseMode
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
from .utils import extract_url, human_size, looks_like_direct_audio_url, safe_filename, source_title_from_url

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
        self.brand_dir = self.settings.base_dir / "assets" / "brand"
        self.user_locks: dict[int, asyncio.Lock] = {}
        self.queue: asyncio.Queue[QueueJob] = asyncio.Queue()
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
                logger.exception("Queue job failed")
                self.db.increment_stat("errors")
            finally:
                self.queue.task_done()
                await asyncio.sleep(self.settings.queue_poll_interval)

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        message = update.message
        if message is None:
            return
        if user:
            self.db.upsert_user(user.id, user.first_name, user.username)
        splash_path = self.brand_dir / "start-splash.png"
        photo_caption = (
            "*NexDownSave*\n"
            "_быстрый, чистый и надежный музыкальный utility-бот_\n\n"
            "Что внутри:\n"
            "• очередь задач без конфликтов\n"
            "• импорт аудиофайлов и прямых ссылок\n"
            "• автоматическая конвертация в MP3\n"
            "• история, избранное, поиск и диагностика\n\n"
            f"Текущий лимит файла: *{self.settings.max_file_mb} МБ*\n\n"
            "Отправь ссылку на аудиофайл или загрузи трек в чат."
        )
        if splash_path.exists():
            with splash_path.open("rb") as image_file:
                await message.reply_photo(
                    photo=image_file,
                    caption=photo_caption,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=main_menu(),
                )
            return
        brand_block = r"""```
 _   _            ____                        ____                  
| \ | | _____  __|  _ \  _____      ___ __ / ___|  __ ___   _____ 
|  \| |/ _ \ \/ /| | | |/ _ \ \ /\ / / '_ \\___ \ / _` \ \ / / _ \
| |\  |  __/>  < | |_| | (_) \ V  V /| | | |___) | (_| |\ V /  __/
|_| \_|\___/_/\_\|____/ \___/ \_/\_/ |_| |_|____/ \__,_| \_/ \___|
```
"""
        text = (
            brand_block
            + "*NexDownSave*\n"
            "_быстрый, чистый и надежный музыкальный utility-бот_\n\n"
            "Что внутри:\n"
            "• очередь задач без конфликтов\n"
            "• прямые аудиоссылки и загрузки файлов\n"
            "• импорт и глубокая проверка пользовательских аудиофайлов\n"
            "• автоматическая конвертация в MP3 и чтение метаданных\n"
            "• история, избранное, поиск и админ-диагностика\n\n"
            f"Текущий лимит файла: *{self.settings.max_file_mb} МБ*\n\n"
            "Отправь ссылку на аудиофайл или загрузи трек в чат."
        )
        await message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=main_menu())

    async def cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        help_text = r"""*Как работает NexDownSave*

1\. Пришли прямую ссылку на аудиофайл: `.mp3`, `.m4a`, `.wav`, `.ogg`, `.flac`, `.aac`, `.opus`
2\. Или загрузи свой аудиофайл/документ прямо в чат
3\. Бот поставит задачу в очередь, проверит размер, аудиопоток и метаданные, затем конвертирует в MP3 и пришлет результат

Дополнительно:
• `/history` показывает историю с пагинацией
• `/favorites` показывает избранное с пагинацией
• `/search текст` ищет по истории и избранному"""
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN_V2)

    async def cmd_stats(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(self.render_stats(), parse_mode=ParseMode.MARKDOWN)

    async def cmd_history(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if user is None:
            return
        text, markup = self.render_history_page(user.id, 1)
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)

    async def cmd_favorites(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if user is None:
            return
        text, markup = self.render_favorites_page(user.id, 1)
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)

    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(self.render_status(), parse_mode=ParseMode.MARKDOWN)

    async def cmd_search(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if user is None or update.message is None:
            return
        query = " ".join(ctx.args).strip()
        if not query:
            await update.message.reply_text("Используй `/search название` для поиска по истории и избранному.", parse_mode=ParseMode.MARKDOWN)
            return
        self.db.increment_stat("search_requests")
        await update.message.reply_text(self.render_search(user.id, query), parse_mode=ParseMode.MARKDOWN)

    async def cmd_admin(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if user is None or not self.is_admin(user.id):
            await update.message.reply_text("Требуется доступ администратора.")
            return
        summary = self.db.get_global_summary()
        await update.message.reply_text(
            "*NexDownSave Admin*\n\n"
            f"Пользователей: *{summary['users']}*\n"
            f"Записей истории: *{summary['history_items']}*\n"
            f"Избранного: *{summary['favorites']}*\n"
            f"Успешных задач: *{summary['completed']}*\n"
            f"Неудачных задач: *{summary['failed']}*\n"
            f"Размер очереди: *{self.queue.qsize()}*",
            parse_mode=ParseMode.MARKDOWN,
        )

    def render_stats(self) -> str:
        stats = self.db.get_stats()
        return (
            "*Статистика NexDownSave*\n\n"
            f"Запросов: *{stats.get('requests', 0)}*\n"
            f"Прямых загрузок: *{stats.get('direct_downloads', 0)}*\n"
            f"Загруженных файлов: *{stats.get('uploaded_files', 0)}*\n"
            f"Добавлений в избранное: *{stats.get('favorites_added', 0)}*\n"
            f"Поисковых запросов: *{stats.get('search_requests', 0)}*\n"
            f"Ошибок: *{stats.get('errors', 0)}*\n"
            f"Пользователей: *{stats.get('users', 0)}*\n"
            f"Записей истории: *{stats.get('history', 0)}*"
        )

    def render_history_page(self, user_id: int, page: int) -> tuple[str, object]:
        items, pages = self.db.get_history_page(user_id, page, PAGE_SIZE)
        if not items:
            return "История NexDownSave пока пуста.", main_menu()
        lines = ["*Последние задачи*"]
        for item in items:
            lines.append(f"• `{item.title}` | `{item.status}` | {item.created_at}")
        return "\n".join(lines), pager("history", page, pages)

    def render_favorites_page(self, user_id: int, page: int) -> tuple[str, object]:
        items, pages = self.db.get_favorites_page(user_id, page, PAGE_SIZE)
        if not items:
            return "В избранном пока ничего нет.", main_menu()
        lines = ["*Избранное NexDownSave*"]
        for item in items:
            lines.append(f"• `{item['title']}` | {item['created_at']}")
        return "\n".join(lines), pager("favorites", page, pages)

    def render_search(self, user_id: int, query: str) -> str:
        history_items = self.db.search_history(user_id, query, SEARCH_LIMIT)
        favorite_items = self.db.search_favorites(user_id, query, SEARCH_LIMIT)
        if not history_items and not favorite_items:
            return f"Ничего не найдено по запросу: `{query}`"
        lines = [f"*Поиск: {query}*"]
        if history_items:
            lines.append("")
            lines.append("*История*")
            for item in history_items:
                lines.append(f"• `{item.title}` | `{item.status}`")
        if favorite_items:
            lines.append("")
            lines.append("*Избранное*")
            for item in favorite_items:
                lines.append(f"• `{item['title']}`")
        return "\n".join(lines)

    def render_status(self) -> str:
        return (
            "*Состояние NexDownSave*\n\n"
            f"• Очередь: *{self.queue.qsize()}*\n"
            f"• Повторных попыток: *{self.settings.retry_attempts}*\n"
            f"• Лимит файла: *{self.settings.max_file_mb} МБ*\n"
            f"• Таймаут скачивания: *{self.settings.download_timeout} сек*\n"
            f"• Таймаут ffmpeg: *{self.settings.ffmpeg_timeout} сек*"
        )

    def render_metadata_card(self, metadata: AudioMetadata | None, file_size: int) -> str:
        if metadata is None:
            return "◆ NexDownSave\n└ Размер: " + human_size(file_size)

        parts = ["◆ NexDownSave", f"├ Размер: {human_size(file_size)}"]
        if metadata.artist:
            parts.append(f"├ Исполнитель: {metadata.artist}")
        if metadata.album:
            parts.append(f"├ Альбом: {metadata.album}")
        if metadata.duration_seconds is not None:
            minutes = int(metadata.duration_seconds // 60)
            seconds = int(metadata.duration_seconds % 60)
            parts.append(f"├ Длительность: {minutes}:{seconds:02d}")
        if metadata.bitrate_kbps:
            parts.append(f"├ Битрейт: {metadata.bitrate_kbps} kbps")
        if metadata.codec:
            parts.append(f"└ Кодек: {metadata.codec}")
        elif len(parts) > 1:
            last = parts.pop()
            parts.append(last.replace("├ ", "└ ", 1))
        return "\n".join(parts)

    async def handle_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.message
        user = update.effective_user
        if message is None or user is None:
            return
        self.db.upsert_user(user.id, user.first_name, user.username)
        self.db.increment_stat("requests")

        url = extract_url(message.text or "")
        if not url:
            await message.reply_text("◌ Пришли прямую аудиоссылку или загрузи файл.", reply_markup=main_menu())
            return
        if not looks_like_direct_audio_url(url):
            await message.reply_text(
                "◌ NexDownSave принимает только прямые ссылки на аудиофайлы. Пришли ссылку с аудиорасширением или загрузи файл.",
                reply_markup=main_menu(),
            )
            return

        history_id = self.db.add_history(user.id, "url", url, source_title_from_url(url), 0, "queued")
        status = await message.reply_text(f"◌ Задача принята в очередь NexDownSave\n└ Позиция: {self.queue.qsize() + 1}")
        await self.queue.put(
            QueueJob(
                user_id=user.id,
                chat_id=message.chat_id,
                history_id=history_id,
                source_type="url",
                source_value=url,
                status_message_id=status.message_id,
            )
        )

    async def handle_media(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.message
        user = update.effective_user
        if message is None or user is None:
            return
        self.db.upsert_user(user.id, user.first_name, user.username)
        self.db.increment_stat("requests")

        media = message.audio or message.document
        if media is None:
            return

        history_id = self.db.add_history(
            user.id,
            "upload",
            media.file_id,
            getattr(media, "file_name", None) or "upload",
            0,
            "queued",
        )
        status = await message.reply_text(f"◌ Файл принят в очередь NexDownSave\n└ Позиция: {self.queue.qsize() + 1}")
        await self.queue.put(
            QueueJob(
                user_id=user.id,
                chat_id=message.chat_id,
                history_id=history_id,
                source_type="upload",
                source_value=media.file_id,
                file_id=media.file_id,
                file_name=getattr(media, "file_name", None) or f"upload_{media.file_unique_id}",
                status_message_id=status.message_id,
            )
        )

    async def process_job(self, app: Application, job: QueueJob) -> None:
        bot = app.bot
        async with self.get_lock(job.user_id):
            if job.status_message_id is not None:
                await bot.edit_message_text(
                    chat_id=job.chat_id,
                    message_id=job.status_message_id,
                    text="◌ NexDownSave обрабатывает задачу\n└ Подготавливаю аудио...",
                )
            await bot.send_chat_action(chat_id=job.chat_id, action=ChatAction.UPLOAD_DOCUMENT)

            if job.source_type == "url":
                result = await self.pipeline.download_direct_url(job.source_value)
                if not result.ok or result.output_path is None or result.title is None:
                    self.db.increment_stat("errors")
                    self.db.update_history_status(job.history_id, "failed")
                    if job.status_message_id is not None:
                        await bot.edit_message_text(chat_id=job.chat_id, message_id=job.status_message_id, text=result.message)
                    return
                await self.send_result(bot, job, result)
                self.db.increment_stat("direct_downloads")
                return

            if job.source_type == "upload" and job.file_id is not None and job.file_name is not None:
                job_dir = self.pipeline.reserve_job_dir()
                local_path = job_dir / safe_filename(job.file_name)
                telegram_file = await bot.get_file(job.file_id)
                await telegram_file.download_to_drive(custom_path=str(local_path))
                result = await self.pipeline.prepare_uploaded_file(local_path)
                if not result.ok or result.output_path is None or result.title is None:
                    self.db.increment_stat("errors")
                    self.db.update_history_status(job.history_id, "failed")
                    self.pipeline.cleanup_job_dir(job_dir)
                    if job.status_message_id is not None:
                        await bot.edit_message_text(chat_id=job.chat_id, message_id=job.status_message_id, text=result.message)
                    return
                await self.send_result(bot, job, result)
                self.db.increment_stat("uploaded_files")
                self.pipeline.cleanup_job_dir(job_dir)
                return

            self.db.increment_stat("errors")
            self.db.update_history_status(job.history_id, "failed")
            if job.status_message_id is not None:
                await bot.edit_message_text(chat_id=job.chat_id, message_id=job.status_message_id, text="Неподдерживаемый тип задачи.")

    async def send_result(self, bot, job: QueueJob, result: ProcessResult) -> None:
        if result.output_path is None or result.title is None:
            return
        caption = self.render_metadata_card(result.metadata, result.file_size)
        performer = result.metadata.artist if result.metadata and result.metadata.artist else None
        if job.status_message_id is not None:
            await bot.edit_message_text(
                chat_id=job.chat_id,
                message_id=job.status_message_id,
                text=f"◌ NexDownSave отправляет результат\n└ Размер: {human_size(result.file_size)}",
            )
        with open(result.output_path, "rb") as audio_file:
            await bot.send_audio(
                chat_id=job.chat_id,
                audio=audio_file,
                filename=result.output_path.name,
                title=result.title,
                performer=performer,
                caption=caption,
                reply_markup=result_actions(job.history_id),
            )
        self.db.update_history_status(job.history_id, "done", file_size=result.file_size, title=result.title)
        if job.status_message_id is not None:
            await bot.delete_message(chat_id=job.chat_id, message_id=job.status_message_id)
        if result.output_path.parent.exists():
            self.pipeline.cleanup_job_dir(result.output_path.parent)

    async def handle_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user = update.effective_user
        if query is None or user is None:
            return
        await query.answer()

        if query.data == "noop":
            return
        if query.data == "menu:main":
            await query.message.reply_text("Главное меню NexDownSave", reply_markup=main_menu())
            return
        if query.data == "menu:help":
            await query.message.reply_text(
                "Пришли прямую ссылку на аудиофайл или загрузи аудио/документ. NexDownSave поставит задачу в очередь, проверит аудиопоток и вернет MP3."
            )
            return
        if query.data == "menu:stats":
            await query.message.reply_text(self.render_stats(), parse_mode=ParseMode.MARKDOWN)
            return
        if query.data == "menu:search":
            await query.message.reply_text("Используй `/search название` для поиска по истории и избранному.", parse_mode=ParseMode.MARKDOWN)
            return
        if query.data == "menu:status":
            await query.message.reply_text(self.render_status(), parse_mode=ParseMode.MARKDOWN)
            return
        if query.data.startswith("history:"):
            page = int(query.data.split(":", 1)[1])
            text, markup = self.render_history_page(user.id, page)
            await query.edit_message_text(text=text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            return
        if query.data.startswith("favorites:"):
            page = int(query.data.split(":", 1)[1])
            text, markup = self.render_favorites_page(user.id, page)
            await query.edit_message_text(text=text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)
            return
        if query.data.startswith("fav:"):
            history_id = int(query.data.split(":", 1)[1])
            target = self.db.get_history_item(user.id, history_id)
            if target is None:
                await query.message.reply_text("◌ Запись истории не найдена.")
                return
            created = self.db.add_favorite(user.id, target.source_type, target.source_value, target.title)
            if created:
                self.db.increment_stat("favorites_added")
                await query.message.reply_text(f"◆ Добавлено в избранное NexDownSave\n└ {target.title}")
            else:
                await query.message.reply_text("◌ Этот элемент уже есть в избранном.")
            return
        if query.data.startswith("repeat:"):
            history_id = int(query.data.split(":", 1)[1])
            target = self.db.get_history_item(user.id, history_id)
            if target is None:
                await query.message.reply_text("◌ Запись истории не найдена.")
                return
            if target.source_type != "url":
                await query.message.reply_text("◌ Повтор доступен только для прямых ссылок.")
                return
            new_history_id = self.db.add_history(user.id, "url", target.source_value, target.title, 0, "queued")
            status = await query.message.reply_text(f"◌ Повторно добавлено в очередь NexDownSave\n└ {target.title}")
            await self.queue.put(
                QueueJob(
                    user_id=user.id,
                    chat_id=query.message.chat_id,
                    history_id=new_history_id,
                    source_type="url",
                    source_value=target.source_value,
                    status_message_id=status.message_id,
                )
            )

    async def error_handler(self, update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        logger.exception("Unhandled error", exc_info=ctx.error)


async def on_post_init(application: Application) -> None:
    bot_app: BotApp = application.bot_data["bot_app"]
    await bot_app.start_worker(application)


async def on_shutdown(application: Application) -> None:
    bot_app: BotApp = application.bot_data["bot_app"]
    await bot_app.stop_worker()



def main() -> None:
    settings = load_settings()
    setup_logging(settings)

    if not settings.bot_token:
        raise SystemExit("Укажи BOT_TOKEN перед запуском NexDownSave")

    bot_app = BotApp(settings)
    missing = bot_app.pipeline.check_dependencies()
    if missing:
        raise SystemExit(f"Не найдены системные зависимости: {', '.join(missing)}")

    application = (
        Application.builder()
        .token(settings.bot_token)
        .post_init(on_post_init)
        .post_shutdown(on_shutdown)
        .build()
    )
    application.bot_data["bot_app"] = bot_app
    application.add_handler(CommandHandler("start", bot_app.cmd_start))
    application.add_handler(CommandHandler("help", bot_app.cmd_help))
    application.add_handler(CommandHandler("stats", bot_app.cmd_stats))
    application.add_handler(CommandHandler("history", bot_app.cmd_history))
    application.add_handler(CommandHandler("favorites", bot_app.cmd_favorites))
    application.add_handler(CommandHandler("status", bot_app.cmd_status))
    application.add_handler(CommandHandler("search", bot_app.cmd_search))
    application.add_handler(CommandHandler("admin", bot_app.cmd_admin))
    application.add_handler(CallbackQueryHandler(bot_app.handle_callback))
    application.add_handler(MessageHandler(filters.AUDIO | filters.Document.ALL, bot_app.handle_media))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot_app.handle_text))
    application.add_error_handler(bot_app.error_handler)

    logger.info("NexDownSave started")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
