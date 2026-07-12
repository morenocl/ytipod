import sqlite3
from pathlib import Path

import config

DB = Path(config.DATABASE)


def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def initialize():
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS channels(
                id INTEGER PRIMARY KEY,
                channel TEXT NOT NULL,
                title_substring TEXT NOT NULL,
                UNIQUE(channel, title_substring)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS downloads(
                id INTEGER PRIMARY KEY,
                youtube_id TEXT UNIQUE,
                channel TEXT NOT NULL,
                title TEXT NOT NULL,
                filename TEXT NOT NULL,
                downloaded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                synced_to_ipod INTEGER NOT NULL DEFAULT 0,
                synced_at DATETIME
            )
            """
        )
        _migrate_downloads(conn)
        conn.commit()


def _table_columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _migrate_downloads(conn):
    columns = _table_columns(conn, "downloads")
    migrations = {
        "filename": "ALTER TABLE downloads ADD COLUMN filename TEXT NOT NULL DEFAULT ''",
        "synced_to_ipod": "ALTER TABLE downloads ADD COLUMN synced_to_ipod INTEGER NOT NULL DEFAULT 0",
        "synced_at": "ALTER TABLE downloads ADD COLUMN synced_at DATETIME",
    }
    for column, sql in migrations.items():
        if column not in columns:
            conn.execute(sql)


def add_channel(channel, title_substring):
    initialize()
    with connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO channels(channel, title_substring)
            VALUES(?, ?)
            """,
            (channel.strip().lstrip("@"), title_substring.strip()),
        )
        conn.commit()


def get_channels():
    initialize()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT channel, title_substring
            FROM channels
            ORDER BY channel, title_substring
            """
        ).fetchall()
    return [(row["channel"], row["title_substring"]) for row in rows]


def already_downloaded(video_id):
    initialize()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM downloads
            WHERE youtube_id = ?
            """,
            (video_id,),
        ).fetchone()
    return row is not None


def register(video_id, title, channel, filename):
    initialize()
    with connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO downloads(
                youtube_id,
                channel,
                title,
                filename
            )
            VALUES(?, ?, ?, ?)
            """,
            (video_id, channel, title, str(filename)),
        )
        conn.commit()


def pending_sync_downloads():
    initialize()
    with connect() as conn:
        return conn.execute(
            """
            SELECT id, title, filename
            FROM downloads
            WHERE synced_to_ipod = 0
            ORDER BY downloaded_at
            """
        ).fetchall()


def mark_synced(download_id):
    initialize()
    with connect() as conn:
        conn.execute(
            """
            UPDATE downloads
            SET synced_to_ipod = 1,
                synced_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (download_id,),
        )
        conn.commit()
