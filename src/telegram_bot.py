import json
import logging
import mimetypes
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

import config
import database
import downloader
import epub_builder
import trafilatura_epub
from logging_config import setup_logging

logger = logging.getLogger(__name__)

COMMANDS = {"/yt", "/tw", "/epub", "/ep-trafilatura"}


def _api(method, params=None):
    if not config.TELEGRAM_TOKEN:
        raise RuntimeError("Falta YTIPOD_TELEGRAM_TOKEN")
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/{method}"
    if params:
        url += "?" + urlencode(params)
    with urlopen(url, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _api_multipart(method, fields, file_field, file_path):
    if not config.TELEGRAM_TOKEN:
        raise RuntimeError("Falta YTIPOD_TELEGRAM_TOKEN")

    boundary = "----ytipodtelegramboundary"
    path = Path(file_path)
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    body = bytearray()

    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(str(value).encode())
        body.extend(b"\r\n")

    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{path.name}"\r\n'.encode()
    )
    body.extend(f"Content-Type: {mime_type}\r\n\r\n".encode())
    body.extend(path.read_bytes())
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())

    request = Request(
        f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/{method}",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urlopen(request, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def _send(chat_id, text):
    _api("sendMessage", {"chat_id": chat_id, "text": text})


def _safe_send(chat_id, text):
    try:
        _send(chat_id, text)
    except Exception:
        logger.exception("No se pudo enviar mensaje a Telegram")


def _send_document(chat_id, file_path, caption=None):
    fields = {"chat_id": chat_id}
    if caption:
        fields["caption"] = caption
    _api_multipart("sendDocument", fields, "document", file_path)


def _register_commands():
    _api(
        "setMyCommands",
        {
            "commands": json.dumps(
                [
                    {"command": "yt", "description": "Descargar video de YouTube"},
                    {"command": "tw", "description": "Descargar video desde un link"},
                    {"command": "epub", "description": "Generar EPUB con el extractor actual"},
                    {"command": "ep-trafilatura", "description": "Generar EPUB con Trafilatura y Pandoc"},
                ],
                ensure_ascii=False,
            )
        },
    )


def _allowed(chat_id):
    allowed = config.TELEGRAM_ALLOWED_CHAT_ID.strip()
    return not allowed or str(chat_id) == allowed


def _extract_url(text):
    for part in text.split():
        parsed = urlparse(part.strip())
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return part.strip()
    return None


def _parse_command(text):
    parts = text.strip().split(maxsplit=1)
    if not parts:
        return None, ""
    command = parts[0].split("@", 1)[0].lower()
    if command not in COMMANDS:
        return None, text
    return command, parts[1] if len(parts) > 1 else ""


def _handle_youtube(chat_id, text):
    url = _extract_url(text)
    if not url or not downloader.is_youtube_url(url):
        _send(chat_id, "Uso: /yt <link de YouTube>")
        return

    info = downloader.get_video_info(url)
    youtube_id = info.get("id") or downloader.youtube_id_from_url(url)
    title = info.get("title", youtube_id or "video")
    channel = info.get("uploader") or info.get("channel") or "telegram"

    if youtube_id and database.already_downloaded(youtube_id):
        logger.info("Ya estaba descargado desde Telegram: %s", title)
        _send(chat_id, f"Ya estaba descargado: {title}")
        return
    if youtube_id and database.download_blocked(youtube_id):
        logger.info("Descarga bloqueada por no_retry desde Telegram: %s", title)
        _send(chat_id, f"La descarga esta marcada como no reintentar: {title}")
        return

    logger.info("Descargando YouTube desde Telegram: %s", title)
    _send(chat_id, f"Descargando para el iPod: {title}")
    try:
        source, info = downloader.download_video_raw("telegram", url)
        filename = downloader.finalize_downloaded_video(source, info)
        database.register(youtube_id or filename.stem, title, channel, filename)
        logger.info("Listo para sincronizar: %s", filename)
        _send(chat_id, f"Listo para sincronizar con el iPod: {title}")
    except Exception as exc:
        logger.exception("Fallo la descarga desde Telegram: %s", title)
        if youtube_id:
            database.register_download_failure(
                video_id=youtube_id,
                title=title,
                channel=channel,
                error=str(exc),
                no_retry=False,
            )
        _send(chat_id, f"Error descargando el video: {exc}")


def _handle_twitter_video(chat_id, text):
    url = _extract_url(text)
    if not url:
        _send(chat_id, "Uso: /tw <link con video>")
        return

    target_dir = Path(config.TEMP_DIR) / "telegram_tw"
    logger.info("Descargando video para enviar por Telegram: %s", url)
    _send(chat_id, "Descargando video...")
    filename = downloader.download_video_to_dir(url, target_dir)
    logger.info("Enviando video por Telegram: %s", filename)
    _send_document(chat_id, filename, caption=filename.stem)


def _handle_epub(chat_id, text):
    url = _extract_url(text)
    if not url:
        _send(chat_id, "Uso: /epub <link de articulo>")
        return

    target_dir = Path(config.EPUB_DIR)
    logger.info("Generando EPUB desde URL: %s", url)
    _send(chat_id, "Generando EPUB...")
    filename, title = epub_builder.article_to_epub(url, target_dir)
    database.register_epub_download(url, filename, title)
    logger.info("EPUB registrado y guardado: %s", filename)
    _send_document(chat_id, filename, caption=title)


def _handle_ep_trafilatura(chat_id, text):
    url = _extract_url(text)
    if not url:
        _send(chat_id, "Uso: /ep-trafilatura <link de articulo>")
        return

    logger.info("Generando EPUB con trafilatura y pandoc: %s", url)
    _send(chat_id, "Generando EPUB...")
    filename, title = trafilatura_epub.build_epub_from_url(url, config.EPUB_DIR)
    database.register_epub_download(url, filename, title)
    logger.info("EPUB generado y guardado: %s", filename)
    _send_document(chat_id, filename, caption=title)


def handle_message(message):
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")

    try:
        if not _allowed(chat_id):
            logger.warning("Mensaje ignorado de chat no autorizado: %s", chat_id)
            return

        command, payload = _parse_command(text)
        if not command:
            if _extract_url(text):
                _safe_send(chat_id, "Usa /yt para YouTube, /tw para videos de Twitter/X, /epub para articulos o /ep-trafilatura para articulos.")
            else:
                _safe_send(chat_id, "Comandos disponibles: /yt, /tw, /epub, /ep-trafilatura")
            return

        if command == "/yt":
            _handle_youtube(chat_id, payload)
        elif command == "/tw":
            _handle_twitter_video(chat_id, payload)
        elif command == "/epub":
            _handle_epub(chat_id, payload)
        elif command == "/ep-trafilatura":
            _handle_ep_trafilatura(chat_id, payload)
    except Exception as exc:
        logger.exception("Error procesando mensaje o comando")
        try:
            if chat_id is not None:
                _safe_send(chat_id, f"Error procesando el mensaje: {exc}")
        except Exception:
            logger.exception("No se pudo notificar el error al chat")


def run_polling():
    setup_logging("telegram_bot")
    database.initialize()
    Path(config.TEMP_DIR).mkdir(parents=True, exist_ok=True)
    Path(config.EPUB_DIR).mkdir(parents=True, exist_ok=True)
    try:
        _register_commands()
    except Exception:
        logger.exception("No se pudieron registrar los comandos de Telegram")
    offset = None
    logger.info("Bot de Telegram iniciado")
    while True:
        try:
            params = {"timeout": 50}
            if offset is not None:
                params["offset"] = offset
            result = _api("getUpdates", params)
            for update in result.get("result", []):
                try:
                    offset = update["update_id"] + 1
                    message = update.get("message") or update.get("edited_message")
                    if message:
                        handle_message(message)
                except Exception:
                    logger.exception("Error procesando un update de Telegram")
        except (HTTPError, URLError, TimeoutError) as exc:
            logger.warning("Error Telegram, reintentando: %s", exc)
            time.sleep(10)
        except Exception:
            logger.exception("Error inesperado en el polling de Telegram")
            time.sleep(10)


if __name__ == "__main__":
    run_polling()
