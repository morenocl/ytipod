# ytipod

Servidor Python para descargar videos de YouTube por filtros de canal/titulo, registrar descargas en SQLite y copiarlas al iPod cuando este montado.

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
export YTIPOD_TELEGRAM_TOKEN=<TELEGRAM_BOT_TOKEN>
export YTIPOD_TELEGRAM_ALLOWED_CHAT_ID=<TELEGRAM_CHAT_ID>
```

Cada ejecucion crea un log nuevo en `logs/` con fecha y hora en el nombre, por ejemplo `scan_20260712_030000.log`.

## Uso

Agregar filtros:

```bash
venv/bin/python src/main.py add-channel ytusername "Texto en el Titulo"
venv/bin/python src/main.py list-channels
```

Escanear y descargar coincidencias:

```bash
venv/bin/python src/main.py scan
```

Descargar un link enviado manualmente:

```bash
venv/bin/python src/main.py download-url 'https://www.youtube.com/watch?v=VIDEO_ID'
```

Copiar pendientes al iPod:

```bash
venv/bin/python src/main.py sync-ipod
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

Los links de YouTube solo se procesan si llegan precedidos por `/yt`.

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
