from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.db import Database


class TrackCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db = Database(Path(self.temp_dir.name) / 'music_bot.sqlite3')

    def test_upsert_and_get_track(self) -> None:
        url = 'https://www.youtube.com/watch?v=abc'
        self.db.upsert_track(url, 'Song Title', 'Artist', 215, 'file-id-1')
        track = self.db.get_track(url)
        self.assertIsNotNone(track)
        assert track is not None
        self.assertEqual(track.title, 'Song Title')
        self.assertEqual(track.performer, 'Artist')
        self.assertEqual(track.duration, 215)
        self.assertEqual(track.tg_file_id, 'file-id-1')

    def test_upsert_track_updates_file_id(self) -> None:
        url = 'https://www.youtube.com/watch?v=abc'
        self.db.upsert_track(url, 'Song', None, None, 'file-id-1')
        self.db.upsert_track(url, 'Song', 'New Artist', 100, 'file-id-2')
        track = self.db.get_track(url)
        assert track is not None
        self.assertEqual(track.tg_file_id, 'file-id-2')
        self.assertEqual(track.performer, 'New Artist')

    def test_search_cached_tracks_matches_title_and_performer(self) -> None:
        self.db.upsert_track('u1', 'Bohemian Rhapsody', 'Queen', 354, 'f1')
        self.db.upsert_track('u2', 'Random', 'Imagine Dragons', 200, 'f2')
        by_title = self.db.search_cached_tracks('bohemian', 10)
        self.assertEqual(len(by_title), 1)
        self.assertEqual(by_title[0].tg_file_id, 'f1')
        by_artist = self.db.search_cached_tracks('dragons', 10)
        self.assertEqual(len(by_artist), 1)
        self.assertEqual(by_artist[0].tg_file_id, 'f2')

    def test_get_missing_track_returns_none(self) -> None:
        self.assertIsNone(self.db.get_track('does-not-exist'))


class SearchCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db = Database(Path(self.temp_dir.name) / 'music_bot.sqlite3')

    def test_save_and_get_search_cache(self) -> None:
        payload = json.dumps([{'video_id': 'x', 'title': 't', 'url': 'u'}])
        self.db.save_search_cache('token123', payload)
        self.assertEqual(self.db.get_search_cache('token123'), payload)

    def test_get_missing_token_returns_none(self) -> None:
        self.assertIsNone(self.db.get_search_cache('nope'))

    def test_prune_removes_old_entries(self) -> None:
        self.db.save_search_cache('keep', 'data')
        # Pruning with a huge max age keeps recent entries.
        self.db.prune_search_cache(86_400)
        self.assertIsNotNone(self.db.get_search_cache('keep'))
        # Pruning everything older than 0 seconds clears it.
        self.db.prune_search_cache(0)
        self.assertIsNone(self.db.get_search_cache('keep'))


if __name__ == '__main__':
    unittest.main()
