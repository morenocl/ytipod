import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def set_podcast_genre(filename):
    """Set the ID3 genre of an MP3 before it enters the sync queue."""
    path = Path(filename)
    if path.suffix.lower() != ".mp3":
        return path
    if not shutil.which("mid3v2"):
        raise RuntimeError("No se encontro mid3v2; instale Mutagen para etiquetar MP3")

    logger.info("Estableciendo genero podcast en MP3: %s", path)
    subprocess.run(["mid3v2", "-g", "podcast", str(path)], check=True)
    return path
