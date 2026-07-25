import argparse
import logging

import database
import downloader
import podcast_downloader
import scanner
import sync_ipod
import web_admin
from logging_config import setup_logging

logger = logging.getLogger(__name__)


def cmd_init_db(_args):
    database.initialize()
    logger.info("Base inicializada: %s", database.DB)


def cmd_add_youtube_playlist(args):
    database.add_youtube_playlist(args.playlist_url, args.title)
    logger.info("Playlist YouTube agregada: %s", args.title or args.playlist_url)


def cmd_list_youtube_playlists(_args):
    rows = database.get_youtube_playlists()
    if not rows:
        logger.info("No hay playlists de YouTube configuradas")
        return
    for row in rows:
        logger.info("%s | %s", row["playlist_title"] or "sin titulo", row["playlist_url"])


def cmd_add_podcast(args):
    database.add_podcast_subscription(args.spotify_url, args.author, args.title, args.feed_url)
    logger.info("Podcast agregado: %s - %s", args.author, args.title)


def cmd_list_podcasts(_args):
    rows = database.get_podcast_subscriptions()
    if not rows:
        logger.info("No hay podcasts configurados")
        return
    for row in rows:
        logger.info("%s - %s | Spotify: %s | RSS: %s", row["author"], row["podcast_title"], row["spotify_url"], row["feed_url"] or "sin RSS")


def cmd_scan_podcasts(_args):
    for result in podcast_downloader.scan_all():
        logger.info("Podcast %s | episodios: %s | descargados: %s", result["podcast"], result["matched"], result["downloaded"])


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

    add_playlist = sub.add_parser("add-youtube-playlist")
    add_playlist.add_argument("playlist_url", help="URL de la playlist de YouTube")
    add_playlist.add_argument("--title", default=None, help="Titulo opcional; si se omite se completa al escanear")
    add_playlist.set_defaults(func=cmd_add_youtube_playlist)

    list_playlists = sub.add_parser("list-youtube-playlists")
    list_playlists.set_defaults(func=cmd_list_youtube_playlists)

    add_podcast = sub.add_parser("add-podcast")
    add_podcast.add_argument("spotify_url", help="URL del show en Spotify")
    add_podcast.add_argument("author", help="Autora o autor del podcast")
    add_podcast.add_argument("title", help="Nombre del podcast")
    add_podcast.add_argument("--feed-url", default=None, help="RSS del podcast. Necesario para descargar episodios completos")
    add_podcast.set_defaults(func=cmd_add_podcast)

    list_podcasts = sub.add_parser("list-podcasts")
    list_podcasts.set_defaults(func=cmd_list_podcasts)

    scan_podcasts = sub.add_parser("scan-podcasts")
    scan_podcasts.set_defaults(func=cmd_scan_podcasts)

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
