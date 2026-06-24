from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from app.config import Settings
from app.main import BotApp, QueueJob
from app.services import SearchHit


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
            search_timeout=30,
            search_results=6,
            anthropic_api_key='',
            ai_model='claude-haiku-4-5',
            vibe_queries=5,
            vibe_results=8,
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

    def test_lookup_search_hit_roundtrip(self) -> None:
        hits = [
            SearchHit(video_id='a', title='First', url='https://yt/a', uploader='Chan', duration_seconds=120.0),
            SearchHit(video_id='b', title='Second', url='https://yt/b'),
        ]
        token = self.bot_app.new_token()
        self.bot_app.db.save_search_cache(token, json.dumps([hit.__dict__ for hit in hits]))

        first = self.bot_app.lookup_search_hit(token, '0')
        self.assertIsNotNone(first)
        assert first is not None
        self.assertEqual(first.title, 'First')
        self.assertEqual(first.url, 'https://yt/a')

        second = self.bot_app.lookup_search_hit(token, '1')
        assert second is not None
        self.assertEqual(second.video_id, 'b')

    def test_lookup_search_hit_invalid_inputs(self) -> None:
        self.assertIsNone(self.bot_app.lookup_search_hit('missing', '0'))
        token = self.bot_app.new_token()
        self.bot_app.db.save_search_cache(token, json.dumps([{'video_id': 'a', 'title': 't', 'url': 'u'}]))
        self.assertIsNone(self.bot_app.lookup_search_hit(token, '9'))
        self.assertIsNone(self.bot_app.lookup_search_hit(token, 'not-int'))

    def test_aggregate_vibe_hits_interleaves_and_dedupes(self) -> None:
        results = {
            'q1': [
                SearchHit(video_id='a', title='A', url='ua'),
                SearchHit(video_id='b', title='B', url='ub'),
                SearchHit(video_id='shared', title='Shared', url='us'),
            ],
            'q2': [
                SearchHit(video_id='shared', title='Shared', url='us'),
                SearchHit(video_id='c', title='C', url='uc'),
                SearchHit(video_id='d', title='D', url='ud'),
            ],
        }

        async def fake_search(query: str, limit: int):
            return results.get(query, [])

        self.bot_app.pipeline.search_tracks = fake_search
        hits = asyncio.run(self.bot_app.aggregate_vibe_hits(['q1', 'q2']))

        ids = [hit.video_id for hit in hits]
        self.assertEqual(ids.count('shared'), 1)  # deduped across queries
        self.assertEqual(set(ids), {'a', 'b', 'c', 'd', 'shared'})
        self.assertEqual(ids[:2], ['a', 'shared'])  # round-robin interleave

    def test_render_search_results_lists_tracks(self) -> None:
        hits = [
            SearchHit(video_id='a', title='Alpha', url='u1', uploader='Band', duration_seconds=65.0),
            SearchHit(video_id='b', title='Beta', url='u2'),
        ]
        rendered = self.bot_app.render_search_results('query', hits)
        self.assertIn('Alpha', rendered)
        self.assertIn('Beta', rendered)
        self.assertIn('1:05', rendered)
        self.assertIn('Band', rendered)


if __name__ == '__main__':
    unittest.main()
