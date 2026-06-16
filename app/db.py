import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass


@dataclass
class HistoryItem:
    id: int
    user_id: int
    source_type: str
    source_value: str
    title: str
    status: str
    created_at: str
    file_size: int = 0


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        """Инициализирует базу данных"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    first_name TEXT,
                    username TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    source_type TEXT,
                    source_value TEXT,
                    title TEXT,
                    status TEXT,
                    file_size INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS favorites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    source_type TEXT,
                    source_value TEXT,
                    title TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, source_value),
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stats (
                    key TEXT PRIMARY KEY,
                    value INTEGER DEFAULT 0
                )
            ''')
            
            conn.commit()
    
    def upsert_user(self, user_id: int, first_name: str, username: Optional[str]):
        """Добавляет или обновляет пользователя"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT OR REPLACE INTO users (user_id, first_name, username) VALUES (?, ?, ?)',
                (user_id, first_name, username)
            )
            conn.commit()
    
    def add_history(self, user_id: int, source_type: str, source_value: str, title: str, file_size: int, status: str) -> int:
        """Добавляет запись в историю"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO history (user_id, source_type, source_value, title, file_size, status) VALUES (?, ?, ?, ?, ?, ?)',
                (user_id, source_type, source_value, title, file_size, status)
            )
            conn.commit()
            return cursor.lastrowid
    
    def update_history_status(self, history_id: int, status: str, file_size: int = 0, title: str = ""):
        """Обновляет статус записи в истории"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if title:
                cursor.execute(
                    'UPDATE history SET status = ?, file_size = ?, title = ? WHERE id = ?',
                    (status, file_size, title, history_id)
                )
            else:
                cursor.execute(
                    'UPDATE history SET status = ?, file_size = ? WHERE id = ?',
                    (status, file_size, history_id)
                )
            conn.commit()
    
    def get_history(self, user_id: int, limit: int = 50) -> List[HistoryItem]:
        """Получает историю пользователя"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id, user_id, source_type, source_value, title, status, created_at, file_size FROM history WHERE user_id = ? ORDER BY created_at DESC LIMIT ?',
                (user_id, limit)
            )
            return [HistoryItem(*row) for row in cursor.fetchall()]
    
    def get_history_item(self, user_id: int, history_id: int) -> Optional[HistoryItem]:
        """Получает конкретную запись истории"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id, user_id, source_type, source_value, title, status, created_at, file_size FROM history WHERE id = ? AND user_id = ?',
                (history_id, user_id)
            )
            row = cursor.fetchone()
            return HistoryItem(*row) if row else None
    
    def add_favorite(self, user_id: int, source_type: str, source_value: str, title: str) -> bool:
        """Добавляет в избранное"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT INTO favorites (user_id, source_type, source_value, title) VALUES (?, ?, ?, ?)',
                    (user_id, source_type, source_value, title)
                )
                conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
    
    def get_favorites(self, user_id: int, limit: int = 50) -> List[dict]:
        """Получает избранное пользователя"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id, source_type, source_value, title, created_at FROM favorites WHERE user_id = ? ORDER BY created_at DESC LIMIT ?',
                (user_id, limit)
            )
            return [{'id': row[0], 'source_type': row[1], 'source_value': row[2], 'title': row[3], 'created_at': row[4]} for row in cursor.fetchall()]
    
    def increment_stat(self, key: str):
        """Увеличивает статистику"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT OR IGNORE INTO stats (key, value) VALUES (?, 0)', (key,))
            cursor.execute('UPDATE stats SET value = value + 1 WHERE key = ?', (key,))
            conn.commit()
    
    def get_stats(self) -> dict:
        """Получает статистику"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT key, value FROM stats')
            return {row[0]: row[1] for row in cursor.fetchall()}
    
    def get_global_summary(self) -> dict:
        """Получает глобальную сводку"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) FROM users')
            users = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM history')
            history_items = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM favorites')
            favorites = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM stats WHERE key = ? AND value > 0', ('errors',))
            failed = cursor.fetchone()[0]
            
            return {
                'users': users,
                'history_items': history_items,
                'favorites': favorites,
                'completed': history_items - failed,
                'failed': failed,
            }
