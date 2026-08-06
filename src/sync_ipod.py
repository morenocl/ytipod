import logging
import shutil
from pathlib import Path

import audio_metadata
import config
import database
from logging_config import setup_logging

logger = logging.getLogger(__name__)


def _copy_preserving_structure(source, source_root, destination_root):
    source = Path(source)
    source_root = Path(source_root)
    destination_root = Path(destination_root)
    try:
        relative = source.relative_to(source_root)
    except ValueError:
        relative = source.name
    target = destination_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def sync_pending(ipod_video_dir=None, ipod_podcast_dir=None):
    database.initialize()
    video_destination = Path(ipod_video_dir or config.IPOD_YOUTUBE_DIR)
    podcast_destination = Path(ipod_podcast_dir or config.IPOD_PODCAST_DIR)

    video_destination.mkdir(parents=True, exist_ok=True)
    podcast_destination.mkdir(parents=True, exist_ok=True)

    copied = 0
    for row in database.pending_sync_downloads():
        source = Path(row["filename"])
        if not source.exists():
            logger.warning("Archivo no encontrado, queda pendiente: %s", source)
            continue

        audio_metadata.set_podcast_genre(source)
        target = _copy_preserving_structure(source, config.YOUTUBE_DIR, video_destination)
        database.mark_synced(row["id"])
        if source.suffix.lower() == ".mpg":
            source.unlink(missing_ok=True)
        copied += 1
        logger.info("Copiado al iPod: %s", target)

    for row in database.pending_sync_podcast_downloads():
        source = Path(row["filename"])
        if not source.exists():
            logger.warning("Archivo de podcast no encontrado, queda pendiente: %s", source)
            continue

        audio_metadata.set_podcast_genre(source)
        target = _copy_preserving_structure(source, config.PODCAST_DIR, podcast_destination)
        database.mark_podcast_synced(row["id"])
        copied += 1
        logger.info("Podcast copiado al iPod: %s", target)

    return copied


def main(configure_logging=True):
    if configure_logging:
        setup_logging("sync_ipod")
    copied = sync_pending()
    logger.info("Videos sincronizados: %s", copied)


if __name__ == "__main__":
    main()
