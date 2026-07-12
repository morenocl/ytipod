import logging
import shutil
from pathlib import Path

import config
import database
from logging_config import setup_logging

logger = logging.getLogger(__name__)


def sync_pending(ipod_video_dir=None):
    database.initialize()
    destination = Path(ipod_video_dir or config.IPOD_VIDEO_DIR)

    if not destination.exists():
        raise FileNotFoundError(
            f"No existe el directorio del iPod: {destination}. Ajusta YTIPOD_IPOD_VIDEO_DIR."
        )

    copied = 0
    for row in database.pending_sync_downloads():
        source = Path(row["filename"])
        if not source.exists():
            logger.warning("Archivo no encontrado, queda pendiente: %s", source)
            continue

        target = destination / source.name
        shutil.copy2(source, target)
        database.mark_synced(row["id"])
        copied += 1
        logger.info("Copiado al iPod: %s", target)

    return copied


def main(configure_logging=True):
    if configure_logging:
        setup_logging("sync_ipod")
    copied = sync_pending()
    logger.info("Videos sincronizados: %s", copied)


if __name__ == "__main__":
    main()
