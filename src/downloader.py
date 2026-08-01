import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yt_dlp

import config

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = Path(config.DOWNLOAD_DIR)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_DOWNLOAD_DIR = Path(config.YOUTUBE_DIR)
VIDEO_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

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

    return filename, info


def _upload_date_prefix(info):
    upload_date = str(info.get("upload_date") or "")
    if len(upload_date) == 8 and upload_date.isdigit():
        return upload_date[2:]

    timestamp = info.get("timestamp") or info.get("release_timestamp")
    if timestamp:
        from datetime import datetime

        return datetime.fromtimestamp(timestamp).strftime("%y%m%d")

    video_id = str(info.get("id") or "video")
    return video_id[:6].rjust(6, "0")


def _source_prefix(source_file):
    source = Path(source_file)
    stem = source.stem
    if len(stem) >= 7 and stem[:6].isdigit() and stem[6] == "-":
        return stem[:6]
    return datetime.fromtimestamp(source.stat().st_mtime).strftime("%y%m%d")


def _ipod_video_target(source_file, info=None):
    source = Path(source_file)
    prefix = _upload_date_prefix(info) if info is not None else _source_prefix(source)
    stem = source.stem
    if not stem.startswith(f"{prefix}-"):
        stem = f"{prefix}-{stem}"
    return source.with_name(f"{stem}.mpg")


def _convert_to_ipod_mpeg(source_file, target_file):
    source = Path(source_file)
    target = Path(target_file)
    tmp_target = target.with_suffix(".tmp.mpg")

    width = config.IPOD_VIDEO_WIDTH
    height = config.IPOD_VIDEO_HEIGHT
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"setsar=1,fps={config.IPOD_VIDEO_FPS}"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        vf,
        "-c:v",
        "mpeg1video",
        "-b:v",
        config.IPOD_VIDEO_BITRATE,
        "-r",
        str(config.IPOD_VIDEO_FPS),
        "-c:a",
        "mp2",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-b:a",
        config.IPOD_AUDIO_BITRATE,
        "-f",
        "mpeg",
        str(tmp_target),
    ]

    logger.info("Convirtiendo para iPod/Rockbox: %s -> %s", source, target)
    subprocess.run(cmd, check=True)
    tmp_target.replace(target)

    return target


def download_video_raw(folder_path, url, include_uploader_folder=True):
    dirpath = VIDEO_DOWNLOAD_DIR / Path(folder_path)
    dirpath.mkdir(parents=True, exist_ok=True)
    if include_uploader_folder:
        outtmpl = dirpath / "%(uploader)s" / "%(title)s [%(id)s].%(ext)s"
    else:
        outtmpl = dirpath / "%(title)s [%(id)s].%(ext)s"
    return _download_with_template(url, outtmpl)


def finalize_downloaded_video(source_file, info):
    source = Path(source_file)
    target = _ipod_video_target(source, info)
    return _convert_to_ipod_mpeg(source, target)


def convert_video_for_sync(source_file, info=None):
    source = Path(source_file)
    if source.suffix.lower() != ".mp4":
        raise ValueError(f"Se esperaba un archivo .mp4: {source}")
    target = _ipod_video_target(source, info)
    return _convert_to_ipod_mpeg(source, target)


def youtube_id_from_filename(filename):
    stem = Path(filename).stem
    match = re.search(r"\[([^\[\]]+)\]$", stem)
    if match:
        return match.group(1)
    return None


def title_from_filename(filename):
    stem = Path(filename).stem
    stem = re.sub(r"^\d{6}-", "", stem)
    stem = re.sub(r"\s*\[[^\[\]]+\]$", "", stem)
    return stem or Path(filename).stem


def download_video(folder_path, url, include_uploader_folder=True):
    source, info = download_video_raw(folder_path, url, include_uploader_folder=include_uploader_folder)
    return finalize_downloaded_video(source, info)


def download_video_to_dir(url, target_dir):
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    filename, _info = _download_with_template(url, target / "%(title)s [%(id)s].%(ext)s")
    return filename


def get_video_info(url):
    with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True, "noplaylist": True}) as ydl:
        return ydl.extract_info(url, download=False)
