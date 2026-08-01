# ytipod

Servidor Python para descargar videos de playlists de YouTube, convertirlos a MPEG para Rockbox/iPod, registrar descargas en SQLite y copiarlas al iPod cuando este montado.

## Configuracion

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python src/main.py init-db
```

Variables utiles:

```bash
export YTIPOD_DATABASE=ytipod/ytipod.db
export YTIPOD_DOWNLOAD_DIR=ytipod/downloads
export YTIPOD_LOG_DIR=ytipod/logs
export YTIPOD_TEMP_DIR=ytipod/tmp
export YTIPOD_IPOD_VIDEO_DIR=/media/ipod/Videos
export YTIPOD_IPOD_VIDEO_WIDTH=320
export YTIPOD_IPOD_VIDEO_HEIGHT=240
export YTIPOD_IPOD_VIDEO_FPS=25
export YTIPOD_IPOD_VIDEO_BITRATE=450k
export YTIPOD_IPOD_AUDIO_BITRATE=128k
export YTIPOD_TELEGRAM_TOKEN=<TELEGRAM_BOT_TOKEN>
export YTIPOD_TELEGRAM_ALLOWED_CHAT_ID=<TELEGRAM_CHAT_ID>
```

Cada ejecucion crea un log nuevo en `logs/` con fecha y hora en el nombre, por ejemplo `scan_20260712_030000.log`.

Los videos se guardan bajo `YTIPOD_DOWNLOAD_DIR/Videos/` y los podcasts bajo `YTIPOD_DOWNLOAD_DIR/Podcast/`. Al sincronizar, se copia preservando la estructura relativa hacia `YTIPOD_IPOD_MOUNT/Videos` y `YTIPOD_IPOD_MOUNT/Podcast`. Los videos destinados al iPod se guardan como `.mpg` con prefijo `YYMMDD-` segun la fecha de subida a YouTube, por ejemplo `240102-Titulo [id].mpg`, para conservar el orden al copiar al dispositivo.

## Uso

Agregar playlists de YouTube:

```bash
venv/bin/python src/main.py add-youtube-playlist 'https://www.youtube.com/playlist?list=PLAYLIST_ID' --title 'Nombre opcional' --since '2026-08-01'
venv/bin/python src/main.py list-youtube-playlists
```

Escanear y descargar videos nuevos de playlists y podcasts:

```bash
venv/bin/python src/main.py scan
```

Descargar un link enviado manualmente:

```bash
venv/bin/python src/main.py download-url 'https://www.youtube.com/watch?v=VIDEO_ID'
```

Reconstruir manualmente un video local ya descargado a formato iPod y dejarlo pendiente de sincronizacion. Solo hace falta el path del archivo; el titulo, el ID y el canal se toman de la base de datos o se derivan del nombre/ruta del archivo:

```bash
venv/bin/python src/main.py convert-video /ruta/al/video.mp4
```

Copiar pendientes al iPod:

```bash
venv/bin/python src/main.py sync-ipod
```

Reorganizar una vez los archivos ya descargados al nuevo arbol `Videos/` y `Podcast/`:

```bash
venv/bin/python src/main.py reorganize-downloads
```

Bot de Telegram:

```bash
YTIPOD_TELEGRAM_TOKEN=... venv/bin/python src/telegram_bot.py
```

Comandos del bot:

```text
/yt <link de YouTube>       Descarga el video y lo deja listo para sincronizar con el iPod.
/tw <link con video>        Descarga el video y lo envia como archivo por Telegram.
/epub <link de articulo>    Extrae el texto, genera un EPUB y lo envia por Telegram.
```

Los EPUBs generados por `/epub` se conservan en `YTIPOD_DOWNLOAD_DIR/epubs/` y se registran en la tabla `epub_downloads` con fecha, URL original y path del archivo.

Los links de YouTube solo se procesan si llegan precedidos por `/yt`.

## Podcasts

Puedes programar podcasts guardando la URL de Spotify como referencia junto con autora, nombre del podcast y el RSS desde donde se descargan los episodios completos:

```bash
venv/bin/python src/main.py add-podcast \
  'https://open.spotify.com/show/SPOTIFY_SHOW_ID' \
  'Nombre Autora' \
  'Nombre del podcast' \
  --feed-url 'https://example.com/podcast/rss' \
  --since '2026-08-01'

venv/bin/python src/main.py list-podcasts
venv/bin/python src/main.py scan-podcasts
```

El scan nocturno (`venv/bin/python src/main.py scan`) tambien chequea podcasts. Los episodios quedan en:

```text
YTIPOD_DOWNLOAD_DIR/Podcast/Autora/Podcast/YYMMDD-Titulo.mp3
```

Spotify no expone una descarga completa de episodios desde la URL `open.spotify.com/show/...`; por eso `feed_url` es necesario para descargar contenido. Si una suscripcion no tiene RSS, queda registrada pero el scan la omite con un warning.

## Admin web

Levanta una interfaz visual para editar las tablas SQLite `channels` y `downloads`:

```bash
venv/bin/python src/main.py web-admin
```

Por defecto escucha en `http://127.0.0.1:8080`. Para exponerlo a otra maquina, configura usuario/password en `.env` y cambia el host:

```bash
YTIPOD_WEB_HOST=0.0.0.0
YTIPOD_WEB_PORT=8080
YTIPOD_WEB_USERNAME=admin
YTIPOD_WEB_PASSWORD=<CHANGE_ME>
```

## Automatizacion diaria a las 3am

Copia `deploy/systemd/ytipod-scan.service.example` y `deploy/systemd/ytipod-scan.timer.example` a `~/.config/systemd/user/`, ajusta las rutas si hace falta y ejecuta:

```bash
systemctl --user daemon-reload
systemctl --user enable --now ytipod-scan.timer
```

## Sincronizacion al conectar iPod

La forma mas robusta es montar el iPod siempre en el mismo path y disparar:

```bash
ytipod/venv/bin/python ytipod/src/main.py sync-ipod
```

Hay una plantilla en `deploy/udev/99-ytipod.rules.example`. Hay que ajustar `idVendor`, `idProduct`, usuario y ruta real del montaje del iPod en tu maquina.
