import hashlib
import logging
import re
import shutil
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

import config
import database

logger = logging.getLogger(__name__)


def _slugify(value):
    value = re.sub(r"[^A-Za-z0-9._ -]+", "", value).strip().replace("/", "-")
    value = re.sub(r"\s+", " ", value)
    return value[:120] or "untitled"


def _episode_id(feed_url, guid, audio_url):
    source = guid or audio_url or feed_url
    return hashlib.sha1(source.encode("utf-8")).hexdigest()


def _date_prefix(value):
    if not value:
        return "000000"
    try:
        dt = parsedate_to_datetime(value)
        return dt.strftime("%y%m%d")
    except (TypeError, ValueError, IndexError):
        return hashlib.sha1(value.encode("utf-8")).hexdigest()[:6]


def _parse_iso_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None


def _extension_from_url(audio_url):
    suffix = Path(urlparse(audio_url).path).suffix.lower()
    return suffix if suffix in {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav"} else ".mp3"


def _download_file(url, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 ytipod/1.0"})
    tmp_target = target.with_suffix(target.suffix + ".part")
    with urlopen(request, timeout=120) as response, tmp_target.open("wb") as output:
        shutil.copyfileobj(response, output)
    tmp_target.replace(target)


def _parse_feed(feed_url):
    request = Request(feed_url, headers={"User-Agent": "Mozilla/5.0 ytipod/1.0"})
    with urlopen(request, timeout=60) as response:
        tree = ET.parse(response)

    channel = tree.find("channel")
    if channel is None:
        raise RuntimeError("El RSS no tiene channel")

    episodes = []
    for item in channel.findall("item"):
        title = item.findtext("title") or "episodio"
        guid = item.findtext("guid") or ""
        pub_date = item.findtext("pubDate") or ""
        enclosure = item.find("enclosure")
        audio_url = enclosure.attrib.get("url", "") if enclosure is not None else ""
        if not audio_url:
            continue
        episodes.append({"title": title, "guid": guid, "published_at": pub_date, "audio_url": audio_url})
    return episodes


def scan_subscription(subscription):
    spotify_url = subscription["spotify_url"]
    author = subscription["author"]
    podcast_title = subscription["podcast_title"]
    feed_url = subscription["feed_url"]
    cutoff_date = subscription["cutoff_date"]
    if not feed_url:
        logger.warning("Podcast sin feed_url, no se puede descargar: %s (%s)", podcast_title, spotify_url)
        return {"podcast": podcast_title, "matched": 0, "downloaded": 0}

    base_dir = Path(config.PODCAST_DIR) / _slugify(author) / _slugify(podcast_title)
    downloaded = 0
    episodes = _parse_feed(feed_url)
    cutoff_date_value = _parse_iso_date(cutoff_date)

    for episode in episodes:
        episode_id = _episode_id(feed_url, episode["guid"], episode["audio_url"])
        if database.podcast_episode_downloaded(episode_id):
            continue
        if database.podcast_download_blocked(episode_id):
            logger.info("Omitido por no_retry: %s", episode["title"])
            continue

        episode_date = None
        try:
            episode_date = parsedate_to_datetime(episode["published_at"]).date() if episode["published_at"] else None
        except (TypeError, ValueError, IndexError):
            episode_date = None
        if cutoff_date_value and episode_date and episode_date < cutoff_date_value:
            logger.info("Omitido por fecha de corte %s: %s", cutoff_date_value, episode["title"])
            continue
        if cutoff_date_value and not episode_date:
            logger.warning("Episodio sin fecha, omitido por el corte %s: %s", cutoff_date_value, episode["title"])
            continue

        prefix = _date_prefix(episode["published_at"])
        suffix = _extension_from_url(episode["audio_url"])
        filename = base_dir / f"{prefix}-{_slugify(episode['title'])}{suffix}"
        logger.info("Descargando podcast: %s -> %s", episode["title"], filename)
        try:
            _download_file(episode["audio_url"], filename)
            database.register_podcast_download(
                episode_id=episode_id,
                spotify_url=spotify_url,
                author=author,
                podcast_title=podcast_title,
                episode_title=episode["title"],
                filename=filename,
                published_at=episode["published_at"],
            )
            downloaded += 1
        except Exception as exc:
            logger.exception("Fallo la descarga del podcast: %s", episode["title"])
            database.register_podcast_download_failure(
                episode_id=episode_id,
                spotify_url=spotify_url,
                author=author,
                podcast_title=podcast_title,
                episode_title=episode["title"],
                error=str(exc),
                no_retry=False,
                published_at=episode["published_at"],
            )
            continue

    return {"podcast": podcast_title, "matched": len(episodes), "downloaded": downloaded}


def scan_all():
    database.initialize()
    results = []
    for subscription in database.get_podcast_subscriptions():
        logger.info("Escaneando podcast: %s - %s", subscription["author"], subscription["podcast_title"])
        try:
            results.append(scan_subscription(subscription))
        except Exception:
            logger.exception("Fallo el podcast: %s - %s", subscription["author"], subscription["podcast_title"])
    return results
