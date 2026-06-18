from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.config import Settings
from app.main import BotApp, QueueJob


class BotAppQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        base_dir = Path(self.temp_dir.name)
        data_dir = base_dir / 'data'
        temp_path = data_dir / 'tmp'
        self.settings = Settings(
            bot_token='test-token',
            admin_user_ids=(),
            base_dir=base_dir,
            data_dir=data_dir,
            temp_dir=temp_path,
            db_path=data_dir / 'music_bot.sqlite3',
            log_path=data_dir / 'bot.log',
            max_file_mb=50,
            max_file_bytes=50 * 1024 * 1024,
            download_timeout=30,
            ffmpeg_timeout=30,
            history_limit=100,
            retry_attempts=1,
            queue_poll_interval=0.1,
            queue_maxsize=10,
        )
        self.settings.ensure_runtime_dirs()
        self.bot_app = BotApp(self.settings)

    def test_cancel_pending_jobs_removes_only_current_user_entries(self) -> None:
        first_id = self.bot_app.db.add_history(10, 'url', 'https://example.com/1', 'one', 0, 'queued')
        second_id = self.bot_app.db.add_history(10, 'url', 'https://example.com/2', 'two', 0, 'queued')
        third_id = self.bot_app.db.add_history(11, 'url', 'https://example.com/3', 'three', 0, 'queued')

        self.bot_app.queue.put_nowait(QueueJob(10, 100, first_id, 'url', 'https://example.com/1'))
        self.bot_app.queue.put_nowait(QueueJob(11, 101, third_id, 'url', 'https://example.com/3'))
        self.bot_app.queue.put_nowait(QueueJob(10, 100, second_id, 'url', 'https://example.com/2'))

        removed = self.bot_app.cancel_pending_jobs(10)

        self.assertEqual(len(removed), 2)
        self.assertEqual({job.history_id for job in removed}, {first_id, second_id})
        self.assertEqual(self.bot_app.queue.qsize(), 1)

        remaining = self.bot_app.queue.get_nowait()
        self.assertEqual(remaining.user_id, 11)
        self.assertEqual(remaining.history_id, third_id)

        first = self.bot_app.db.get_history_item(10, first_id)
        second = self.bot_app.db.get_history_item(10, second_id)
        third = self.bot_app.db.get_history_item(11, third_id)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNotNone(third)
        assert first is not None
        assert second is not None
        assert third is not None
        self.assertEqual(first.status, 'cancelled')
        self.assertEqual(second.status, 'cancelled')
        self.assertEqual(third.status, 'queued')


if __name__ == '__main__':
    unittest.main()
