import logging
from datetime import datetime
from pathlib import Path

from yt_dlp import YoutubeDL

import database
import downloader
import podcast_downloader
from logging_config import setup_logging

logger = logging.getLogger(__name__)


def _safe_dirname(value):
    cleaned = "".join(char for char in value if char not in "<>:\\|?*").strip()
    return cleaned[:120] or "YouTube Playlist"


def list_playlist(playlist_url):
    options = {
        "extract_flat": True,
        "skip_download": True,
        "quiet": True,
        "ignoreerrors": True,
    }

    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(playlist_url, download=False)

    return info or {}


def _parse_date(value):
    if not value:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value), fmt).date()
        except ValueError:
            continue
    return None


def _video_date(video_url, flat_video=None):
    if flat_video:
        upload_date = flat_video.get("upload_date")
        if upload_date:
            parsed = _parse_date(upload_date)
            if parsed:
                return parsed
        timestamp = flat_video.get("timestamp") or flat_video.get("release_timestamp")
        if timestamp:
            return datetime.fromtimestamp(timestamp).date()
    info = downloader.get_video_info(video_url)
    upload_date = info.get("upload_date")
    if upload_date:
        parsed = _parse_date(upload_date)
        if parsed:
            return parsed
    timestamp = info.get("timestamp") or info.get("release_timestamp")
    if timestamp:
        return datetime.fromtimestamp(timestamp).date()
    return None


def scan_youtube_playlist(playlist):
    playlist_url = playlist["playlist_url"]
    cutoff_date = _parse_date(playlist["cutoff_date"]) or datetime.today().date()
    info = list_playlist(playlist_url)
    playlist_title = info.get("title") or playlist["playlist_title"] or "YouTube Playlist"
    if playlist["playlist_title"] != playlist_title:
        database.update_youtube_playlist_title(playlist["id"], playlist_title)

    matched = 0
    downloaded = 0
    owner = _safe_dirname(
        info.get("uploader")
        or info.get("uploader_id")
        or info.get("channel")
        or info.get("channel_id")
        or "YouTube"
    )
    playlist_dir = _safe_dirname(playlist_title)
    folder_path = f"{owner}/{playlist_dir}"
    prepared = []

    for video in info.get("entries", []) if info else []:
        if not video:
            continue

        youtube_id = video.get("id")
        title = video.get("title") or youtube_id or "video"
        if not youtube_id:
            logger.warning("Video sin id en playlist %s: %s", playlist_title, title)
            continue

        matched += 1
        video_url = f"https://www.youtube.com/watch?v={youtube_id}"
        try:
            video_date = _video_date(video_url, video)
        except Exception:
            logger.exception("No se pudo leer la fecha del video %s", youtube_id)
            continue
        if not video_date:
            logger.warning("Video sin fecha, omitido por el corte %s: %s", cutoff_date, title)
            continue
        if video_date < cutoff_date:
            logger.info('Omitido por fecha de corte %s: "%s"', cutoff_date, title)
            continue
        if database.already_downloaded(youtube_id):
            logger.info('Ya registrado: "%s"', title)
            continue
        if database.download_blocked(youtube_id):
            logger.info('Omitido por no_retry: "%s"', title)
            continue

        logger.info('Descargando desde playlist %s: "%s"', playlist_title, title)
        try:
            audio_only = bool(playlist["audio_only"])
            source, video_info = downloader.download_video_raw(
                folder_path,
                video_url,
                include_uploader_folder=False,
                audio_only=audio_only,
            )
            prepared.append((youtube_id, title, source, video_info, audio_only))
        except Exception as exc:
            logger.exception("Fallo la descarga de playlist %s: %s", playlist_title, title)
            database.register_download_failure(
                video_id=youtube_id,
                title=title,
                channel=playlist_title,
                error=str(exc),
                no_retry=False,
            )
            continue

    for youtube_id, title, source, video_info, audio_only in prepared:
        try:
            filename = Path(source) if audio_only else downloader.finalize_downloaded_video(source, video_info)
            database.register(
                video_id=youtube_id,
                channel=playlist_title,
                title=title,
                filename=filename,
            )
            logger.info("Registrado: %s", filename)
            downloaded += 1
        except Exception as exc:
            logger.exception("Fallo la conversion de playlist %s: %s", playlist_title, title)
            database.register_download_failure(
                video_id=youtube_id,
                title=title,
                channel=playlist_title,
                error=str(exc),
                no_retry=False,
                filename=source,
            )
            continue

    return {"playlist": playlist_title, "matched": matched, "downloaded": downloaded}


def scan_all():
    database.initialize()
    results = []
    for playlist in database.get_youtube_playlists():
        logger.info("Escaneando playlist YouTube: %s", playlist["playlist_title"] or playlist["playlist_url"])
        try:
            results.append(scan_youtube_playlist(playlist))
        except Exception:
            logger.exception("Fallo la playlist YouTube: %s", playlist["playlist_url"])

    podcast_results = podcast_downloader.scan_all()
    for result in podcast_results:
        logger.info(
            "Podcast %s | episodios: %s | descargados: %s",
            result["podcast"],
            result["matched"],
            result["downloaded"],
        )
    return results


def main(configure_logging=True):
    if configure_logging:
        setup_logging("scan")
    for result in scan_all():
        logger.info(
            "Playlist %s | videos: %s | descargados: %s",
            result["playlist"],
            result["matched"],
            result["downloaded"],
        )


if __name__ == "__main__":
    main()
