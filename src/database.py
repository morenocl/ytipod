import sqlite3
from datetime import date
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
                cutoff_date TEXT NOT NULL,
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
                synced_at DATETIME,
                download_failed INTEGER NOT NULL DEFAULT 0,
                download_error TEXT,
                no_retry INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS epub_downloads(
                id INTEGER PRIMARY KEY,
                source_url TEXT NOT NULL,
                title TEXT,
                filename TEXT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
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
                cutoff_date TEXT NOT NULL,
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
                synced_at DATETIME,
                download_failed INTEGER NOT NULL DEFAULT 0,
                download_error TEXT,
                no_retry INTEGER NOT NULL DEFAULT 0
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
        "download_failed": "ALTER TABLE downloads ADD COLUMN download_failed INTEGER NOT NULL DEFAULT 0",
        "download_error": "ALTER TABLE downloads ADD COLUMN download_error TEXT",
        "no_retry": "ALTER TABLE downloads ADD COLUMN no_retry INTEGER NOT NULL DEFAULT 0",
    }
    for column, sql in migrations.items():
        if column not in columns:
            conn.execute(sql)


def _migrate_podcasts(conn):
    columns = _table_columns(conn, "podcast_subscriptions")
    migrations = {
        "feed_url": "ALTER TABLE podcast_subscriptions ADD COLUMN feed_url TEXT",
        "cutoff_date": "ALTER TABLE podcast_subscriptions ADD COLUMN cutoff_date TEXT NOT NULL DEFAULT CURRENT_DATE",
        "created_at": "ALTER TABLE podcast_subscriptions ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    }
    for column, sql in migrations.items():
        if column not in columns:
            conn.execute(sql)

    columns = _table_columns(conn, "podcast_downloads")
    migrations = {
        "download_failed": "ALTER TABLE podcast_downloads ADD COLUMN download_failed INTEGER NOT NULL DEFAULT 0",
        "download_error": "ALTER TABLE podcast_downloads ADD COLUMN download_error TEXT",
        "no_retry": "ALTER TABLE podcast_downloads ADD COLUMN no_retry INTEGER NOT NULL DEFAULT 0",
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
              AND COALESCE(filename, '') != ''
              AND download_failed = 0
            """,
            (video_id,),
        ).fetchone()
    return row is not None


def register(video_id, title, channel, filename):
    initialize()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO downloads(
                youtube_id,
                channel,
                title,
                filename,
                download_failed,
                download_error
            )
            VALUES(?, ?, ?, ?, 0, NULL)
            ON CONFLICT(youtube_id) DO UPDATE SET
                channel = excluded.channel,
                title = excluded.title,
                filename = excluded.filename,
                download_failed = 0,
                download_error = NULL,
                synced_to_ipod = 0,
                synced_at = NULL,
                no_retry = downloads.no_retry
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
              AND download_failed = 0
              AND COALESCE(filename, '') != ''
            ORDER BY downloaded_at
            """
        ).fetchall()


def find_download_by_filename(filename):
    initialize()
    source = Path(filename)
    exact = str(source)
    resolved = str(source.resolve()) if source.exists() else exact
    basename = source.name
    with connect() as conn:
        row = conn.execute(
            """
            SELECT id, youtube_id, channel, title, filename, downloaded_at
            FROM downloads
            WHERE filename IN (?, ?, ?)
               OR filename LIKE ?
            ORDER BY downloaded_at DESC, id DESC
            LIMIT 1
            """,
            (exact, resolved, basename, f"%/{basename}"),
        ).fetchone()
    return row


def today_date():
    return date.today().isoformat()


def normalize_date(value):
    if value is None:
        return today_date()
    value = str(value).strip()
    return value or today_date()


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


def add_podcast_subscription(spotify_url, author, podcast_title, feed_url=None, cutoff_date=None):
    initialize()
    cutoff_date = normalize_date(cutoff_date)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO podcast_subscriptions(spotify_url, author, podcast_title, feed_url, cutoff_date)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(spotify_url) DO UPDATE SET
                author = excluded.author,
                podcast_title = excluded.podcast_title,
                feed_url = excluded.feed_url,
                cutoff_date = excluded.cutoff_date
            """,
            (spotify_url.strip(), author.strip(), podcast_title.strip(), (feed_url or "").strip() or None, cutoff_date),
        )
        conn.commit()


def get_podcast_subscriptions():
    initialize()
    with connect() as conn:
        return conn.execute(
            """
            SELECT id, spotify_url, author, podcast_title, feed_url, cutoff_date
            FROM podcast_subscriptions
            ORDER BY author, podcast_title
            """
        ).fetchall()


def podcast_episode_downloaded(episode_id):
    initialize()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM podcast_downloads
            WHERE episode_id = ?
              AND COALESCE(filename, '') != ''
              AND download_failed = 0
            """,
            (episode_id,),
        ).fetchone()
    return row is not None


def register_podcast_download(episode_id, spotify_url, author, podcast_title, episode_title, filename, published_at=None):
    initialize()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO podcast_downloads(
                episode_id,
                spotify_url,
                author,
                podcast_title,
                episode_title,
                filename,
                published_at,
                download_failed,
                download_error,
                no_retry
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, 0, NULL, 0)
            ON CONFLICT(episode_id) DO UPDATE SET
                spotify_url = excluded.spotify_url,
                author = excluded.author,
                podcast_title = excluded.podcast_title,
                episode_title = excluded.episode_title,
                filename = excluded.filename,
                published_at = excluded.published_at,
                download_failed = 0,
                download_error = NULL,
                synced_to_ipod = 0,
                synced_at = NULL,
                no_retry = podcast_downloads.no_retry
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
              AND download_failed = 0
              AND COALESCE(filename, '') != ''
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


def add_youtube_playlist(playlist_url, playlist_title=None, cutoff_date=None):
    initialize()
    cutoff_date = normalize_date(cutoff_date)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO youtube_playlists(playlist_url, playlist_title, cutoff_date)
            VALUES(?, ?, ?)
            ON CONFLICT(playlist_url) DO UPDATE SET
                playlist_title = excluded.playlist_title,
                cutoff_date = excluded.cutoff_date
            """,
            (playlist_url.strip(), (playlist_title or "").strip() or None, cutoff_date),
        )
        conn.commit()


def get_youtube_playlists():
    initialize()
    with connect() as conn:
        return conn.execute(
            """
            SELECT id, playlist_url, playlist_title, cutoff_date
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


def register_epub_download(source_url, filename, title=None):
    initialize()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO epub_downloads(source_url, title, filename)
            VALUES(?, ?, ?)
            """,
            (source_url.strip(), (title or "").strip() or None, str(filename)),
        )
        conn.commit()


def get_epub_downloads():
    initialize()
    with connect() as conn:
        return conn.execute(
            """
            SELECT id, source_url, title, filename, created_at
            FROM epub_downloads
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()


def download_blocked(video_id):
    initialize()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM downloads
            WHERE youtube_id = ?
              AND download_failed = 1
              AND no_retry = 1
            """,
            (video_id,),
        ).fetchone()
    return row is not None


def register_download_failure(video_id, title, channel, error, no_retry=False, filename=""):
    initialize()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO downloads(
                youtube_id,
                channel,
                title,
                filename,
                download_failed,
                download_error,
                no_retry
            )
            VALUES(?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(youtube_id) DO UPDATE SET
                channel = excluded.channel,
                title = excluded.title,
                filename = excluded.filename,
                download_failed = 1,
                download_error = excluded.download_error,
                no_retry = MAX(downloads.no_retry, excluded.no_retry)
            """,
            (video_id, channel, title, str(filename), str(error), 1 if no_retry else 0),
        )
        conn.commit()


def podcast_download_blocked(episode_id):
    initialize()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM podcast_downloads
            WHERE episode_id = ?
              AND download_failed = 1
              AND no_retry = 1
            """,
            (episode_id,),
        ).fetchone()
    return row is not None


def register_podcast_download_failure(episode_id, spotify_url, author, podcast_title, episode_title, error, no_retry=False, filename="", published_at=None):
    initialize()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO podcast_downloads(
                episode_id,
                spotify_url,
                author,
                podcast_title,
                episode_title,
                filename,
                published_at,
                download_failed,
                download_error,
                no_retry
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(episode_id) DO UPDATE SET
                spotify_url = excluded.spotify_url,
                author = excluded.author,
                podcast_title = excluded.podcast_title,
                episode_title = excluded.episode_title,
                filename = excluded.filename,
                published_at = excluded.published_at,
                download_failed = 1,
                download_error = excluded.download_error,
                no_retry = MAX(podcast_downloads.no_retry, excluded.no_retry)
            """,
            (episode_id, spotify_url, author, podcast_title, episode_title, str(filename), published_at, str(error), 1 if no_retry else 0),
        )
        conn.commit()
