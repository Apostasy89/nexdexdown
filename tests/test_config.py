from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.config import load_settings


class ConfigTests(unittest.TestCase):
    def test_load_settings_reads_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            (base_dir / '.env').write_text(
                '\n'.join(
                    [
                        'BOT_TOKEN=test-token',
                        'ADMIN_USER_IDS=1, 2,3',
                        'MAX_FILE_MB=64',
                        'QUEUE_MAXSIZE=42',
                    ]
                ),
                encoding='utf-8',
            )
            with mock.patch.dict(os.environ, {}, clear=True):
                settings = load_settings(base_dir)

            self.assertEqual(settings.bot_token, 'test-token')
            self.assertEqual(settings.admin_user_ids, (1, 2, 3))
            self.assertEqual(settings.max_file_mb, 64)
            self.assertEqual(settings.queue_maxsize, 42)
            self.assertEqual(settings.db_path, base_dir / 'data' / 'music_bot.sqlite3')
            self.assertTrue(settings.data_dir.exists())
            self.assertTrue(settings.temp_dir.exists())

    def test_load_settings_validates_numeric_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            with mock.patch.dict(os.environ, {'QUEUE_MAXSIZE': '0'}, clear=True):
                with self.assertRaises(ValueError):
                    load_settings(base_dir)

    def test_load_settings_validates_admin_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            with mock.patch.dict(os.environ, {'ADMIN_USER_IDS': '1,abc'}, clear=True):
                with self.assertRaises(ValueError):
                    load_settings(base_dir)


if __name__ == '__main__':
    unittest.main()
