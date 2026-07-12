import logging

from yt_dlp import YoutubeDL

import database
import downloader
from logging_config import setup_logging

logger = logging.getLogger(__name__)


def list_streams(channel):
    channel = channel.strip().lstrip("@")
    url = f"https://www.youtube.com/@{channel}/streams"
    options = {
        "extract_flat": True,
        "skip_download": True,
        "quiet": True,
        "ignoreerrors": True,
    }

    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)

    return info.get("entries", []) if info else []


def scan_channel(channel, substring):
    matched = 0
    downloaded = 0

    for video in list_streams(channel):
        if not video:
            continue

        title = video.get("title", "")
        if substring.lower() not in title.lower():
            continue

        matched += 1
        youtube_id = video.get("id")
        if not youtube_id:
            logger.warning("Video sin id en @%s: %s", channel, title)
            continue

        if database.already_downloaded(youtube_id):
            logger.info('Ya registrado: "%s"', title)
            continue

        logger.info('Descargando: "%s"', title)
        filename = downloader.download_video(channel, f"https://www.youtube.com/watch?v={youtube_id}")
        database.register(
            video_id=youtube_id,
            channel=channel,
            title=title,
            filename=filename,
        )
        logger.info("Registrado: %s", filename)
        downloaded += 1

    return {"channel": channel, "substring": substring, "matched": matched, "downloaded": downloaded}


def scan_all():
    database.initialize()
    results = []
    for channel, substring in database.get_channels():
        logger.info("Escaneando @%s: %s", channel, substring)
        results.append(scan_channel(channel, substring))
    return results


def main(configure_logging=True):
    if configure_logging:
        setup_logging("scan")
    for result in scan_all():
        logger.info(
            "@%s | coincidencias: %s | descargados: %s",
            result["channel"],
            result["matched"],
            result["downloaded"],
        )


if __name__ == "__main__":
    main()
