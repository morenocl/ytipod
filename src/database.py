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
            CREATE TABLE IF NOT EXISTS youtube_playlists(
                id INTEGER PRIMARY KEY,
                playlist_url TEXT NOT NULL UNIQUE,
                playlist_title TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS podcast_subscriptions(
                id INTEGER PRIMARY KEY,
                spotify_url TEXT NOT NULL UNIQUE,
                author TEXT NOT NULL,
                podcast_title TEXT NOT NULL,
                feed_url TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS podcast_downloads(
                id INTEGER PRIMARY KEY,
                episode_id TEXT UNIQUE,
                spotify_url TEXT NOT NULL,
                author TEXT NOT NULL,
                podcast_title TEXT NOT NULL,
                episode_title TEXT NOT NULL,
                filename TEXT NOT NULL,
                published_at TEXT,
                downloaded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                synced_to_ipod INTEGER NOT NULL DEFAULT 0,
                synced_at DATETIME
            )
            """
        )
        _migrate_downloads(conn)
        _migrate_podcasts(conn)
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


def _migrate_podcasts(conn):
    columns = _table_columns(conn, "podcast_subscriptions")
    migrations = {
        "feed_url": "ALTER TABLE podcast_subscriptions ADD COLUMN feed_url TEXT",
        "created_at": "ALTER TABLE podcast_subscriptions ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    }
    for column, sql in migrations.items():
        if column not in columns:
            conn.execute(sql)


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


def add_podcast_subscription(spotify_url, author, podcast_title, feed_url=None):
    initialize()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO podcast_subscriptions(spotify_url, author, podcast_title, feed_url)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(spotify_url) DO UPDATE SET
                author = excluded.author,
                podcast_title = excluded.podcast_title,
                feed_url = excluded.feed_url
            """,
            (spotify_url.strip(), author.strip(), podcast_title.strip(), (feed_url or "").strip() or None),
        )
        conn.commit()


def get_podcast_subscriptions():
    initialize()
    with connect() as conn:
        return conn.execute(
            """
            SELECT id, spotify_url, author, podcast_title, feed_url
            FROM podcast_subscriptions
            ORDER BY author, podcast_title
            """
        ).fetchall()


def podcast_episode_downloaded(episode_id):
    initialize()
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM podcast_downloads WHERE episode_id = ?",
            (episode_id,),
        ).fetchone()
    return row is not None


def register_podcast_download(episode_id, spotify_url, author, podcast_title, episode_title, filename, published_at=None):
    initialize()
    with connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO podcast_downloads(
                episode_id, spotify_url, author, podcast_title, episode_title, filename, published_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (episode_id, spotify_url, author, podcast_title, episode_title, str(filename), published_at),
        )
        conn.commit()


def pending_sync_podcast_downloads():
    initialize()
    with connect() as conn:
        return conn.execute(
            """
            SELECT id, episode_title AS title, filename
            FROM podcast_downloads
            WHERE synced_to_ipod = 0
            ORDER BY published_at, downloaded_at
            """
        ).fetchall()


def mark_podcast_synced(download_id):
    initialize()
    with connect() as conn:
        conn.execute(
            """
            UPDATE podcast_downloads
            SET synced_to_ipod = 1,
                synced_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (download_id,),
        )
        conn.commit()


def add_youtube_playlist(playlist_url, playlist_title=None):
    initialize()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO youtube_playlists(playlist_url, playlist_title)
            VALUES(?, ?)
            ON CONFLICT(playlist_url) DO UPDATE SET
                playlist_title = excluded.playlist_title
            """,
            (playlist_url.strip(), (playlist_title or "").strip() or None),
        )
        conn.commit()


def get_youtube_playlists():
    initialize()
    with connect() as conn:
        return conn.execute(
            """
            SELECT id, playlist_url, playlist_title
            FROM youtube_playlists
            ORDER BY playlist_title, playlist_url
            """
        ).fetchall()


def update_youtube_playlist_title(playlist_id, playlist_title):
    initialize()
    with connect() as conn:
        conn.execute(
            "UPDATE youtube_playlists SET playlist_title = ? WHERE id = ?",
            ((playlist_title or "").strip() or None, playlist_id),
        )
        conn.commit()
