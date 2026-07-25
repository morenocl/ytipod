from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yt_dlp

import config

DOWNLOAD_DIR = Path(config.DOWNLOAD_DIR)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

YDL_OPTIONS = {
    "format": "bv*[ext=mp4][height<=480]+ba[ext=m4a]/b[ext=mp4][height<=480]/best[height<=480]/best",
    "merge_output_format": "mp4",
    "ignoreerrors": True,
    "noplaylist": True,
    "restrictfilenames": False,
    "windowsfilenames": True,
}


def youtube_id_from_url(url):
    parsed = urlparse(url)
    if parsed.hostname in {"youtu.be", "www.youtu.be"}:
        return parsed.path.strip("/") or None
    if parsed.hostname and "youtube.com" in parsed.hostname:
        return parse_qs(parsed.query).get("v", [None])[0]
    return None


def is_youtube_url(url):
    parsed = urlparse(url)
    return bool(parsed.hostname and ("youtube.com" in parsed.hostname or "youtu.be" in parsed.hostname))


def _download_with_template(url, outtmpl):
    options = {
        **YDL_OPTIONS,
        "outtmpl": str(outtmpl),
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        if not info:
            raise RuntimeError(f"yt-dlp no devolvio informacion para {url}")
        filename = Path(ydl.prepare_filename(info))
        if filename.suffix != ".mp4":
            filename = filename.with_suffix(".mp4")

    return filename


def download_video(channel_dir, url):
    dirpath = DOWNLOAD_DIR / channel_dir
    dirpath.mkdir(parents=True, exist_ok=True)
    return _download_with_template(url, dirpath / "%(uploader)s" / "%(title)s [%(id)s].%(ext)s")


def download_video_to_dir(url, target_dir):
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    return _download_with_template(url, target / "%(title)s [%(id)s].%(ext)s")


def get_video_info(url):
    with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True, "noplaylist": True}) as ydl:
        return ydl.extract_info(url, download=False)
