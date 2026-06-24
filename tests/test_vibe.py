from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.config import Settings
from app.db import Database
from app.vibe import VibeInterpreter


def make_settings(base_dir: Path, **overrides) -> Settings:
    data_dir = base_dir / 'data'
    defaults = dict(
        bot_token='test-token',
        admin_user_ids=(),
        base_dir=base_dir,
        data_dir=data_dir,
        temp_dir=data_dir / 'tmp',
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
    defaults.update(overrides)
    return Settings(**defaults)


class VibeLexiconTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.settings = make_settings(Path(self.temp_dir.name))
        self.vibe = VibeInterpreter(self.settings)

    def test_ai_unavailable_without_key(self) -> None:
        self.assertFalse(self.vibe.ai_available())

    def test_lexicon_matches_mood_keywords(self) -> None:
        out = asyncio.run(self.vibe.interpret('грустная дождливая ночь', []))
        self.assertEqual(out.source, 'lexicon')
        self.assertTrue(out.queries)
        # Raw request is preserved as the first query.
        self.assertEqual(out.queries[0], 'грустная дождливая ночь')
        # Capped at vibe_queries.
        self.assertLessEqual(len(out.queries), self.settings.vibe_queries)

    def test_lexicon_uses_taste_when_query_empty(self) -> None:
        out = asyncio.run(self.vibe.interpret('', ['Imagine Dragons']))
        self.assertEqual(out.source, 'lexicon')
        self.assertIn('Imagine Dragons', out.queries)

    def test_lexicon_never_empty(self) -> None:
        out = asyncio.run(self.vibe.interpret('', []))
        self.assertTrue(out.queries)

    def test_clean_queries_dedupes_and_caps(self) -> None:
        raw = ['a', 'A', 'b', 'c', 'd', 'e', 'f', 'g']
        cleaned = self.vibe._clean_queries(raw)
        self.assertEqual(cleaned[:2], ['a', 'b'])  # 'A' deduped against 'a'
        self.assertLessEqual(len(cleaned), self.settings.vibe_queries)


class TasteProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db = Database(Path(self.temp_dir.name) / 'music_bot.sqlite3')

    def test_taste_profile_favorites_first_then_done_history(self) -> None:
        self.db.add_favorite(1, 'url', 'u-fav', 'Favorite Track')
        done_id = self.db.add_history(1, 'url', 'u-done', 'Done Track', 0, 'queued')
        self.db.update_history_status(done_id, 'done')
        self.db.add_history(1, 'url', 'u-queued', 'Queued Track', 0, 'queued')

        taste = self.db.get_taste_profile(1, 8)
        self.assertEqual(taste[0], 'Favorite Track')
        self.assertIn('Done Track', taste)
        # Queued (not yet downloaded) tracks are not part of taste.
        self.assertNotIn('Queued Track', taste)

    def test_taste_profile_empty_for_new_user(self) -> None:
        self.assertEqual(self.db.get_taste_profile(999, 8), [])


if __name__ == '__main__':
    unittest.main()
