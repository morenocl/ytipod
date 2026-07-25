import argparse
import logging

import database
import downloader
import scanner
import sync_ipod
import web_admin
from logging_config import setup_logging

logger = logging.getLogger(__name__)


def cmd_init_db(_args):
    database.initialize()
    logger.info("Base inicializada: %s", database.DB)


def cmd_add_channel(args):
    database.add_channel(args.channel, args.substring)
    logger.info("Filtro agregado: @%s -> %s", args.channel.lstrip("@"), args.substring)


def cmd_list_channels(_args):
    database.initialize()
    channels = database.get_channels()
    if not channels:
        logger.info("No hay filtros configurados")
        return
    for channel, substring in channels:
        logger.info("@%s: %s", channel, substring)


def cmd_scan(_args):
    scanner.main(configure_logging=False)


def cmd_download_url(args):
    database.initialize()
    info = downloader.get_video_info(args.url)
    youtube_id = info.get("id") or downloader.youtube_id_from_url(args.url)
    title = info.get("title", youtube_id or "video")
    channel = info.get("uploader") or info.get("channel") or "manual"

    if youtube_id and database.already_downloaded(youtube_id):
        logger.info("Ya estaba descargado: %s", title)
        return

    filename = downloader.download_video("manual", args.url)
    database.register(youtube_id or filename.stem, title, channel, filename)
    logger.info("Descargado: %s", filename)


def cmd_sync_ipod(_args):
    copied = sync_ipod.sync_pending()
    logger.info("Videos sincronizados: %s", copied)


def cmd_web_admin(args):
    web_admin.run(host=args.host, port=args.port)


def build_parser():
    parser = argparse.ArgumentParser(description="Descarga videos de YouTube y los deja listos para iPod.")
    sub = parser.add_subparsers(required=True)

    init_db = sub.add_parser("init-db")
    init_db.set_defaults(func=cmd_init_db)

    add = sub.add_parser("add-channel")
    add.add_argument("channel", help="Nombre del canal sin @, por ejemplo galiamoldavsky")
    add.add_argument("substring", help="Texto que debe aparecer en el titulo")
    add.set_defaults(func=cmd_add_channel)

    list_channels = sub.add_parser("list-channels")
    list_channels.set_defaults(func=cmd_list_channels)

    scan = sub.add_parser("scan")
    scan.set_defaults(func=cmd_scan)

    download = sub.add_parser("download-url")
    download.add_argument("url")
    download.set_defaults(func=cmd_download_url)

    sync = sub.add_parser("sync-ipod")
    sync.set_defaults(func=cmd_sync_ipod)

    web = sub.add_parser("web-admin")
    web.add_argument("--host", default=None, help="Host de escucha, por defecto YTIPOD_WEB_HOST o 127.0.0.1")
    web.add_argument("--port", type=int, default=None, help="Puerto, por defecto YTIPOD_WEB_PORT o 8080")
    web.set_defaults(func=cmd_web_admin)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    setup_logging(args.__dict__.get("func", "ytipod").__name__.replace("cmd_", ""))
    args.func(args)


if __name__ == "__main__":
    main()
