from pathlib import Path
import os

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DOWNLOAD_DIR = Path(os.getenv("YTIPOD_DOWNLOAD_DIR", PROJECT_ROOT / "downloads")).resolve()
DATABASE = Path(os.getenv("YTIPOD_DATABASE", PROJECT_ROOT / "ytipod.db")).resolve()
LOG_DIR = Path(os.getenv("YTIPOD_LOG_DIR", PROJECT_ROOT / "logs")).resolve()
IPOD_MOUNT = Path(os.getenv("YTIPOD_IPOD_MOUNT", "/media/ipod")).resolve()
IPOD_VIDEO_DIR = Path(os.getenv("YTIPOD_IPOD_VIDEO_DIR", IPOD_MOUNT / "Videos")).resolve()

TELEGRAM_TOKEN = os.getenv("YTIPOD_TELEGRAM_TOKEN", "")
TELEGRAM_ALLOWED_CHAT_ID = os.getenv("YTIPOD_TELEGRAM_ALLOWED_CHAT_ID", "")

DAILY_RUN_TIME = os.getenv("YTIPOD_DAILY_RUN_TIME", "03:00")
