from __future__ import annotations

import math
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass
class HistoryItem:
    id: int
    user_id: int
    source_type: str
    source_value: str
    title: str
    file_size: int
    status: str
    created_at: str


@dataclass
class FavoriteItem:
    id: int
    source_type: str
    source_value: str
    title: str
    created_at: str


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=5000')
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;

                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    first_name TEXT,
                    username TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS stats (
                    key TEXT PRIMARY KEY,
                    value INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    source_type TEXT NOT NULL,
                    source_value TEXT NOT NULL,
                    title TEXT NOT NULL,
                    file_size INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS favorites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    source_type TEXT NOT NULL,
                    source_value TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_history_user_id ON history(user_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_history_user_status ON history(user_id, status, id DESC);
                CREATE INDEX IF NOT EXISTS idx_favorites_user_id ON favorites(user_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_favorites_user_source ON favorites(user_id, source_value);
                """
            )
            for key in (
                'requests',
                'direct_downloads',
                'uploaded_files',
                'errors',
                'favorites_added',
                'search_requests',
            ):
                conn.execute('INSERT OR IGNORE INTO stats(key, value) VALUES(?, 0)', (key,))

    def upsert_user(self, user_id: int, first_name: str | None, username: str | None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO users(user_id, first_name, username)
                VALUES(?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    first_name=excluded.first_name,
                    username=excluded.username,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (user_id, first_name, username),
            )

    def increment_stat(self, key: str, amount: int = 1) -> None:
        with self.connect() as conn:
            conn.execute('UPDATE stats SET value = value + ? WHERE key = ?', (amount, key))

    def get_stats(self) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute('SELECT key, value FROM stats').fetchall()
            result = {row['key']: row['value'] for row in rows}
            result['users'] = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
            result['history'] = conn.execute('SELECT COUNT(*) FROM history').fetchone()[0]
            result['favorites'] = conn.execute('SELECT COUNT(*) FROM favorites').fetchone()[0]
            return result

    def add_history(
        self,
        user_id: int,
        source_type: str,
        source_value: str,
        title: str,
        file_size: int,
        status: str,
    ) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO history(user_id, source_type, source_value, title, file_size, status)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (user_id, source_type, source_value, title, file_size, status),
            )
            return int(cursor.lastrowid)

    def update_history_status(
        self,
        history_id: int,
        status: str,
        file_size: int | None = None,
        title: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE history
                SET status = ?,
                    file_size = COALESCE(?, file_size),
                    title = COALESCE(?, title)
                WHERE id = ?
                """,
                (status, file_size, title, history_id),
            )

    def _rows_to_history(self, rows: list[sqlite3.Row]) -> list[HistoryItem]:
        return [HistoryItem(**dict(row)) for row in rows]

    def _rows_to_favorites(self, rows: list[sqlite3.Row]) -> list[FavoriteItem]:
        return [FavoriteItem(**dict(row)) for row in rows]

    def count_history(self, user_id: int) -> int:
        with self.connect() as conn:
            return conn.execute('SELECT COUNT(*) FROM history WHERE user_id = ?', (user_id,)).fetchone()[0]

    def count_history_by_status(self, user_id: int, status: str) -> int:
        with self.connect() as conn:
            return conn.execute(
                'SELECT COUNT(*) FROM history WHERE user_id = ? AND status = ?',
                (user_id, status),
            ).fetchone()[0]

    def count_favorites(self, user_id: int) -> int:
        with self.connect() as conn:
            return conn.execute('SELECT COUNT(*) FROM favorites WHERE user_id = ?', (user_id,)).fetchone()[0]

    def get_history_page(self, user_id: int, page: int, page_size: int) -> tuple[list[HistoryItem], int]:
        total = self.count_history(user_id)
        pages = max(1, math.ceil(total / page_size)) if total else 1
        page = max(1, min(page, pages))
        offset = (page - 1) * page_size
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, source_type, source_value, title, file_size, status, created_at
                FROM history
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (user_id, page_size, offset),
            ).fetchall()
            return self._rows_to_history(rows), pages

    def get_history_by_status(self, user_id: int, status: str, limit: int) -> list[HistoryItem]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, source_type, source_value, title, file_size, status, created_at
                FROM history
                WHERE user_id = ? AND status = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, status, limit),
            ).fetchall()
            return self._rows_to_history(rows)

    def get_history(self, user_id: int, limit: int) -> list[HistoryItem]:
        items, _ = self.get_history_page(user_id, 1, limit)
        return items

    def get_history_item(self, user_id: int, history_id: int) -> HistoryItem | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, user_id, source_type, source_value, title, file_size, status, created_at
                FROM history
                WHERE user_id = ? AND id = ?
                LIMIT 1
                """,
                (user_id, history_id),
            ).fetchone()
            return HistoryItem(**dict(row)) if row else None

    def search_history(self, user_id: int, query: str, limit: int) -> list[HistoryItem]:
        pattern = f"%{query.strip()}%"
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, source_type, source_value, title, file_size, status, created_at
                FROM history
                WHERE user_id = ? AND (title LIKE ? OR source_value LIKE ?)
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, pattern, pattern, limit),
            ).fetchall()
            return self._rows_to_history(rows)

    def add_favorite(self, user_id: int, source_type: str, source_value: str, title: str) -> bool:
        with self.connect() as conn:
            exists = conn.execute(
                'SELECT 1 FROM favorites WHERE user_id = ? AND source_value = ? LIMIT 1',
                (user_id, source_value),
            ).fetchone()
            if exists is not None:
                return False
            conn.execute(
                'INSERT INTO favorites(user_id, source_type, source_value, title) VALUES(?, ?, ?, ?)',
                (user_id, source_type, source_value, title),
            )
            return True

    def get_favorites_page(self, user_id: int, page: int, page_size: int) -> tuple[list[FavoriteItem], int]:
        total = self.count_favorites(user_id)
        pages = max(1, math.ceil(total / page_size)) if total else 1
        page = max(1, min(page, pages))
        offset = (page - 1) * page_size
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, source_type, source_value, title, created_at
                FROM favorites
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (user_id, page_size, offset),
            ).fetchall()
            return self._rows_to_favorites(rows), pages

    def get_favorites(self, user_id: int, limit: int) -> list[FavoriteItem]:
        items, _ = self.get_favorites_page(user_id, 1, limit)
        return items

    def search_favorites(self, user_id: int, query: str, limit: int) -> list[FavoriteItem]:
        pattern = f"%{query.strip()}%"
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, source_type, source_value, title, created_at
                FROM favorites
                WHERE user_id = ? AND (title LIKE ? OR source_value LIKE ?)
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, pattern, pattern, limit),
            ).fetchall()
            return self._rows_to_favorites(rows)

    def get_global_summary(self) -> dict[str, int]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM users) AS users,
                    (SELECT COUNT(*) FROM history) AS history_items,
                    (SELECT COUNT(*) FROM favorites) AS favorites,
                    (SELECT COUNT(*) FROM history WHERE status = 'queued') AS queued,
                    (SELECT COUNT(*) FROM history WHERE status = 'done') AS completed,
                    (SELECT COUNT(*) FROM history WHERE status = 'failed') AS failed
                """
            ).fetchone()
            return {key: row[key] for key in row.keys()} if row else {}
