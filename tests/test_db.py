from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.db import Database


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db = Database(Path(self.temp_dir.name) / 'music_bot.sqlite3')

    def test_history_and_stats_flow(self) -> None:
        self.db.upsert_user(1, 'Test', 'user')
        self.db.increment_stat('requests')
        history_id = self.db.add_history(1, 'url', 'https://example.com/test.mp3', 'test', 0, 'queued')
        self.db.update_history_status(history_id, 'done', file_size=123, title='updated')

        history = self.db.get_history_item(1, history_id)
        self.assertIsNotNone(history)
        assert history is not None
        self.assertEqual(history.status, 'done')
        self.assertEqual(history.file_size, 123)
        self.assertEqual(history.title, 'updated')

        stats = self.db.get_stats()
        self.assertEqual(stats['requests'], 1)
        self.assertEqual(stats['users'], 1)
        self.assertEqual(stats['history'], 1)
        self.assertEqual(self.db.count_history_by_status(1, 'queued'), 0)
        self.assertEqual(self.db.count_history_by_status(1, 'done'), 1)

    def test_pagination_search_queue_and_favorites(self) -> None:
        self.db.upsert_user(5, 'Alice', 'alice')
        for index in range(3):
            self.db.add_history(5, 'url', f'https://example.com/{index}.mp3', f'track {index}', 0, 'queued')

        items, pages = self.db.get_history_page(5, 1, 2)
        self.assertEqual(len(items), 2)
        self.assertEqual(pages, 2)
        self.assertEqual(items[0].title, 'track 2')

        search_results = self.db.search_history(5, 'track 1', 10)
        self.assertEqual(len(search_results), 1)
        self.assertEqual(search_results[0].title, 'track 1')

        queued_items = self.db.get_history_by_status(5, 'queued', 2)
        self.assertEqual(len(queued_items), 2)
        self.assertEqual(queued_items[0].title, 'track 2')
        self.assertEqual(self.db.count_history_by_status(5, 'queued'), 3)

        created = self.db.add_favorite(5, 'url', 'https://example.com/1.mp3', 'track 1')
        duplicate = self.db.add_favorite(5, 'url', 'https://example.com/1.mp3', 'track 1')
        favorites, favorite_pages = self.db.get_favorites_page(5, 1, 10)

        self.assertTrue(created)
        self.assertFalse(duplicate)
        self.assertEqual(len(favorites), 1)
        self.assertEqual(favorite_pages, 1)

        summary = self.db.get_global_summary()
        self.assertEqual(summary['users'], 1)
        self.assertEqual(summary['history_items'], 3)
        self.assertEqual(summary['favorites'], 1)
        self.assertEqual(summary['queued'], 3)


if __name__ == '__main__':
    unittest.main()
