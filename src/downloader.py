import logging
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yt_dlp

import config

logger = logging.getLogger(__name__)

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


def _add_ipod_sort_prefix(source_file, info):
    source = Path(source_file)
    prefix = _upload_date_prefix(info)
    if source.name.startswith(f"{prefix}-"):
        return source

    target = source.with_name(f"{prefix}-{source.name}")
    source.replace(target)
    return target


def _convert_to_ipod_mpeg(source_file):
    source = Path(source_file)
    target = source.with_suffix(".mpg")
    tmp_target = target.with_suffix(".tmp.mpg")

    width = config.IPOD_VIDEO_WIDTH
    height = config.IPOD_VIDEO_HEIGHT
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={config.IPOD_VIDEO_FPS}"
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

    if not config.KEEP_SOURCE_VIDEO and source != target:
        source.unlink(missing_ok=True)

    return target


def download_video(channel_dir, url):
    dirpath = DOWNLOAD_DIR / channel_dir
    dirpath.mkdir(parents=True, exist_ok=True)
    source, info = _download_with_template(url, dirpath / "%(uploader)s" / "%(title)s [%(id)s].%(ext)s")
    source = _add_ipod_sort_prefix(source, info)
    return _convert_to_ipod_mpeg(source)


def download_video_to_dir(url, target_dir):
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    filename, _info = _download_with_template(url, target / "%(title)s [%(id)s].%(ext)s")
    return filename


def get_video_info(url):
    with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True, "noplaylist": True}) as ydl:
        return ydl.extract_info(url, download=False)
