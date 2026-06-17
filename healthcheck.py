#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3

from app.config import load_settings
from app.services import AudioPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='NexDownSave healthcheck')
    parser.add_argument(
        '--allow-missing-db',
        action='store_true',
        help='Do not fail when the SQLite database does not exist yet.',
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    settings = load_settings()
    pipeline = AudioPipeline(settings)

    missing_dependencies = pipeline.check_dependencies()
    if missing_dependencies:
        print(f"healthcheck: missing dependencies: {', '.join(missing_dependencies)}")
        return 1

    if not settings.db_path.exists():
        if args.allow_missing_db:
            print('healthcheck: ok (database will be created on first run)')
            return 0
        print(f'healthcheck: database is missing: {settings.db_path}')
        return 1

    try:
        conn = sqlite3.connect(settings.db_path)
        conn.execute('SELECT 1')
        conn.close()
    except Exception as exc:
        print(f'healthcheck: database check failed: {exc}')
        return 1

    print('healthcheck: ok')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
