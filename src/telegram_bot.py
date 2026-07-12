import json
import logging
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import config
import database
import downloader
from logging_config import setup_logging

logger = logging.getLogger(__name__)

YOUTUBE_MARKERS = ("youtube.com/watch", "youtu.be/", "youtube.com/shorts/")


def _api(method, params=None):
    if not config.TELEGRAM_TOKEN:
        raise RuntimeError("Falta YTIPOD_TELEGRAM_TOKEN")
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/{method}"
    if params:
        url += "?" + urlencode(params)
    with urlopen(url, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _send(chat_id, text):
    _api("sendMessage", {"chat_id": chat_id, "text": text})


def _allowed(chat_id):
    allowed = config.TELEGRAM_ALLOWED_CHAT_ID.strip()
    return not allowed or str(chat_id) == allowed


def _extract_url(text):
    for part in text.split():
        if any(marker in part for marker in YOUTUBE_MARKERS):
            return part.strip()
    return None


def handle_message(message):
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")

    if not _allowed(chat_id):
        logger.warning("Mensaje ignorado de chat no autorizado: %s", chat_id)
        return

    url = _extract_url(text)
    if not url:
        logger.info("Mensaje sin link de YouTube recibido de chat %s", chat_id)
        _send(chat_id, "Enviame un link de YouTube.")
        return

    try:
        info = downloader.get_video_info(url)
        youtube_id = info.get("id") or downloader.youtube_id_from_url(url)
        title = info.get("title", youtube_id or "video")
        channel = info.get("uploader") or info.get("channel") or "telegram"

        if youtube_id and database.already_downloaded(youtube_id):
            logger.info("Ya estaba descargado desde Telegram: %s", title)
            _send(chat_id, f"Ya estaba descargado: {title}")
            return

        logger.info("Descargando desde Telegram: %s", title)
        _send(chat_id, f"Descargando: {title}")
        filename = downloader.download_video("telegram", url)
        database.register(youtube_id or filename.stem, title, channel, filename)
        logger.info("Listo para sincronizar: %s", filename)
        _send(chat_id, f"Listo para sincronizar con el iPod: {title}")
    except Exception as exc:
        logger.exception("Error descargando video desde Telegram")
        _send(chat_id, f"Error descargando el video: {exc}")


def run_polling():
    setup_logging("telegram_bot")
    database.initialize()
    offset = None
    logger.info("Bot de Telegram iniciado")
    while True:
        try:
            params = {"timeout": 50}
            if offset is not None:
                params["offset"] = offset
            result = _api("getUpdates", params)
            for update in result.get("result", []):
                offset = update["update_id"] + 1
                message = update.get("message") or update.get("edited_message")
                if message:
                    handle_message(message)
        except (HTTPError, URLError, TimeoutError) as exc:
            logger.warning("Error Telegram, reintentando: %s", exc)
            time.sleep(10)


if __name__ == "__main__":
    run_polling()
