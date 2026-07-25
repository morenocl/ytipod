from pathlib import Path
import os

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


def _load_dotenv():
    if not ENV_FILE.exists():
        return

    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

DOWNLOAD_DIR = Path(os.getenv("YTIPOD_DOWNLOAD_DIR", PROJECT_ROOT / "downloads")).resolve()
DATABASE = Path(os.getenv("YTIPOD_DATABASE", PROJECT_ROOT / "ytipod.db")).resolve()
LOG_DIR = Path(os.getenv("YTIPOD_LOG_DIR", PROJECT_ROOT / "logs")).resolve()
TEMP_DIR = Path(os.getenv("YTIPOD_TEMP_DIR", PROJECT_ROOT / "tmp")).resolve()
EPUB_DIR = (DOWNLOAD_DIR / "epubs").resolve()
IPOD_MOUNT = Path(os.getenv("YTIPOD_IPOD_MOUNT", "/media/ipod")).resolve()
IPOD_VIDEO_DIR = Path(os.getenv("YTIPOD_IPOD_VIDEO_DIR", IPOD_MOUNT / "Videos")).resolve()

IPOD_VIDEO_WIDTH = int(os.getenv("YTIPOD_IPOD_VIDEO_WIDTH", "320"))
IPOD_VIDEO_HEIGHT = int(os.getenv("YTIPOD_IPOD_VIDEO_HEIGHT", "240"))
IPOD_VIDEO_FPS = int(os.getenv("YTIPOD_IPOD_VIDEO_FPS", "25"))
IPOD_VIDEO_BITRATE = os.getenv("YTIPOD_IPOD_VIDEO_BITRATE", "700k")
IPOD_AUDIO_BITRATE = os.getenv("YTIPOD_IPOD_AUDIO_BITRATE", "128k")
KEEP_SOURCE_VIDEO = os.getenv("YTIPOD_KEEP_SOURCE_VIDEO", "0").lower() in {"1", "true", "yes"}

TELEGRAM_TOKEN = os.getenv("YTIPOD_TELEGRAM_TOKEN", "")
TELEGRAM_ALLOWED_CHAT_ID = os.getenv("YTIPOD_TELEGRAM_ALLOWED_CHAT_ID", "")

DAILY_RUN_TIME = os.getenv("YTIPOD_DAILY_RUN_TIME", "03:00")

WEB_HOST = os.getenv("YTIPOD_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("YTIPOD_WEB_PORT", "8080"))
WEB_USERNAME = os.getenv("YTIPOD_WEB_USERNAME", "")
WEB_PASSWORD = os.getenv("YTIPOD_WEB_PASSWORD", "")
