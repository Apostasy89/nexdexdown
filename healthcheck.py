#!/usr/bin/env python3
from pathlib import Path
import sqlite3

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "music_bot.sqlite3"


def main() -> int:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not DB_PATH.exists():
        print("healthcheck: database is not initialized yet")
        return 0
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("SELECT 1")
        conn.close()
    except Exception as exc:
        print(f"healthcheck: database check failed: {exc}")
        return 1
    print("healthcheck: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
