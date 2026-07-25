import base64
import html
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import config
import database

logger = logging.getLogger(__name__)

TABLES = {
    "youtube_playlists": {
        "label": "Playlists de YouTube",
        "columns": ["id", "playlist_url", "playlist_title", "created_at"],
        "editable": ["playlist_url", "playlist_title"],
        "required": ["playlist_url"],
        "order": "playlist_title, playlist_url",
    },
    "downloads": {
        "label": "Videos descargados",
        "columns": ["id", "youtube_id", "channel", "title", "filename", "downloaded_at", "synced_to_ipod", "synced_at"],
        "editable": ["youtube_id", "channel", "title", "filename", "synced_to_ipod", "synced_at"],
        "required": ["youtube_id", "channel", "title", "filename"],
        "order": "downloaded_at DESC, id DESC",
    },
    "podcast_subscriptions": {
        "label": "Podcasts",
        "columns": ["id", "spotify_url", "author", "podcast_title", "feed_url", "created_at"],
        "editable": ["spotify_url", "author", "podcast_title", "feed_url"],
        "required": ["spotify_url", "author", "podcast_title"],
        "order": "author, podcast_title",
    },
    "podcast_downloads": {
        "label": "Episodios descargados",
        "columns": ["id", "episode_id", "spotify_url", "author", "podcast_title", "episode_title", "filename", "published_at", "downloaded_at", "synced_to_ipod", "synced_at"],
        "editable": ["episode_id", "spotify_url", "author", "podcast_title", "episode_title", "filename", "published_at", "synced_to_ipod", "synced_at"],
        "required": ["episode_id", "spotify_url", "author", "podcast_title", "episode_title", "filename"],
        "order": "downloaded_at DESC, id DESC",
    },
}


def _esc(value):
    return html.escape("" if value is None else str(value), quote=True)


def _redirect(handler, location):
    handler.send_response(HTTPStatus.SEE_OTHER)
    handler.send_header("Location", location)
    handler.end_headers()


def _get_rows(table):
    meta = TABLES[table]
    columns = ", ".join(meta["columns"])
    with database.connect() as conn:
        return conn.execute(f"SELECT {columns} FROM {table} ORDER BY {meta['order']}").fetchall()


def _get_row(table, row_id):
    meta = TABLES[table]
    columns = ", ".join(meta["columns"])
    with database.connect() as conn:
        return conn.execute(f"SELECT {columns} FROM {table} WHERE id = ?", (row_id,)).fetchone()


def _normalize_value(column, values):
    value = values.get(column, [""])[0].strip()
    if column == "synced_to_ipod":
        return 1 if value in {"1", "true", "on", "yes"} else 0
    if value == "" and column in {"synced_at", "published_at", "feed_url", "playlist_title"}:
        return None
    return value


def _insert_row(table, values):
    meta = TABLES[table]
    columns = meta["editable"]
    required = meta["required"]
    data = [_normalize_value(column, values) for column in columns]
    for column in required:
        if not _normalize_value(column, values):
            raise ValueError(f"El campo {column} es obligatorio")
    placeholders = ", ".join("?" for _ in columns)
    column_sql = ", ".join(columns)
    with database.connect() as conn:
        conn.execute(f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})", data)
        conn.commit()


def _update_row(table, row_id, values):
    meta = TABLES[table]
    columns = meta["editable"]
    required = meta["required"]
    data = [_normalize_value(column, values) for column in columns]
    for column in required:
        if not _normalize_value(column, values):
            raise ValueError(f"El campo {column} es obligatorio")
    assignments = ", ".join(f"{column} = ?" for column in columns)
    with database.connect() as conn:
        conn.execute(f"UPDATE {table} SET {assignments} WHERE id = ?", [*data, row_id])
        conn.commit()


def _delete_row(table, row_id):
    with database.connect() as conn:
        conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
        conn.commit()


class AdminHandler(BaseHTTPRequestHandler):
    server_version = "ytipod-admin/1.0"

    def log_message(self, fmt, *args):
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _authorized(self):
        username = config.WEB_USERNAME
        password = config.WEB_PASSWORD
        if not username and not password:
            return True

        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header.removeprefix("Basic ")).decode("utf-8")
        except ValueError:
            return False
        provided_username, _, provided_password = decoded.partition(":")
        return provided_username == username and provided_password == password

    def _require_auth(self):
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="ytipod"')
        self.end_headers()

    def _send_html(self, body, status=HTTPStatus.OK):
        if not self._authorized():
            self._require_auth()
            return
        content = self._layout(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _layout(self, body):
        nav = "".join(
            f'<a href="/?table={name}">{_esc(meta["label"])}</a>'
            for name, meta in TABLES.items()
        )
        return f'''<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ytipod admin</title>
  <style>
    :root {{ color-scheme: light dark; --border: #c8ced8; --muted: #667085; --bg: #f6f7f9; --panel: #ffffff; --text: #111827; --danger: #b42318; }}
    @media (prefers-color-scheme: dark) {{ :root {{ --border: #344054; --muted: #98a2b3; --bg: #0f172a; --panel: #111827; --text: #e5e7eb; --danger: #f97066; }} }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }}
    header {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 16px 24px; border-bottom: 1px solid var(--border); background: var(--panel); }}
    h1 {{ margin: 0; font-size: 20px; }}
    nav {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    nav a, .button {{ display: inline-flex; align-items: center; min-height: 36px; padding: 8px 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--panel); color: var(--text); text-decoration: none; font-size: 14px; cursor: pointer; }}
    main {{ padding: 24px; max-width: 1400px; margin: 0 auto; }}
    .toolbar {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 16px; }}
    .muted {{ color: var(--muted); }}
    .error {{ border: 1px solid var(--danger); color: var(--danger); padding: 10px 12px; border-radius: 6px; margin-bottom: 16px; }}
    table {{ width: 100%; border-collapse: collapse; background: var(--panel); border: 1px solid var(--border); }}
    th, td {{ border-bottom: 1px solid var(--border); padding: 9px 10px; text-align: left; vertical-align: top; font-size: 14px; }}
    th {{ white-space: nowrap; color: var(--muted); font-weight: 600; }}
    td {{ max-width: 360px; overflow-wrap: anywhere; }}
    form.inline {{ display: inline; }}
    button {{ font: inherit; }}
    .danger {{ color: var(--danger); }}
    .form {{ display: grid; gap: 14px; max-width: 760px; background: var(--panel); border: 1px solid var(--border); padding: 16px; border-radius: 8px; }}
    label {{ display: grid; gap: 6px; font-size: 14px; }}
    input, textarea, select {{ width: 100%; min-height: 38px; padding: 8px 10px; border: 1px solid var(--border); border-radius: 6px; background: var(--panel); color: var(--text); font: inherit; }}
    textarea {{ min-height: 92px; resize: vertical; }}
    .actions {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
  </style>
</head>
<body>
  <header><h1>ytipod admin</h1><nav>{nav}</nav></header>
  <main>{body}</main>
</body>
</html>'''

    def do_GET(self):
        if not self._authorized():
            self._require_auth()
            return
        database.initialize()
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        table = params.get("table", ["youtube_playlists"])[0]
        if table not in TABLES:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        action = params.get("action", ["list"])[0]
        if action == "edit":
            self._send_html(self._render_form(table, params.get("id", [""])[0]))
        elif action == "new":
            self._send_html(self._render_form(table))
        else:
            self._send_html(self._render_table(table, params.get("error", [""])[0]))

    def do_POST(self):
        if not self._authorized():
            self._require_auth()
            return
        database.initialize()
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        table = params.get("table", [""])[0]
        action = params.get("action", [""])[0]
        if table not in TABLES:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        length = int(self.headers.get("Content-Length", "0"))
        values = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)

        try:
            if action == "create":
                _insert_row(table, values)
            elif action == "update":
                _update_row(table, int(values["id"][0]), values)
            elif action == "delete":
                _delete_row(table, int(values["id"][0]))
            else:
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
        except Exception as exc:
            logger.exception("Error modificando %s", table)
            _redirect(self, f"/?{urlencode({'table': table, 'error': str(exc)})}")
            return

        _redirect(self, f"/?table={table}")

    def _render_table(self, table, error=""):
        meta = TABLES[table]
        rows = _get_rows(table)
        error_html = f'<div class="error">{_esc(error)}</div>' if error else ""
        header = "".join(f"<th>{_esc(column)}</th>" for column in meta["columns"])
        body = []
        for row in rows:
            cells = "".join(f"<td>{_esc(row[column])}</td>" for column in meta["columns"])
            row_id = row["id"]
            edit_url = f"/?{urlencode({'table': table, 'action': 'edit', 'id': row_id})}"
            actions = f'''<td class="actions">
                <a class="button" href="{edit_url}">Editar</a>
                <form class="inline" method="post" action="/?table={_esc(table)}&action=delete" onsubmit="return confirm('Borrar fila #{row_id}?')">
                  <input type="hidden" name="id" value="{_esc(row_id)}">
                  <button class="button danger" type="submit">Borrar</button>
                </form>
              </td>'''
            body.append(f"<tr>{cells}{actions}</tr>")
        rows_html = "".join(body) or f'<tr><td colspan="{len(meta["columns"]) + 1}" class="muted">No hay filas.</td></tr>'
        new_url = f"/?{urlencode({'table': table, 'action': 'new'})}"
        return f'''{error_html}
<section class="toolbar">
  <div><h2>{_esc(meta["label"])}</h2><p class="muted">Base: {_esc(database.DB)}</p></div>
  <a class="button" href="{new_url}">Nueva fila</a>
</section>
<table>
  <thead><tr>{header}<th>Acciones</th></tr></thead>
  <tbody>{rows_html}</tbody>
</table>'''

    def _render_form(self, table, row_id=None):
        meta = TABLES[table]
        row = _get_row(table, int(row_id)) if row_id else None
        if row_id and not row:
            return f'<div class="error">No existe la fila #{_esc(row_id)}</div>' + self._render_table(table)

        action = "update" if row else "create"
        title = "Editar fila" if row else "Nueva fila"
        fields = []
        if row:
            fields.append(f'<input type="hidden" name="id" value="{_esc(row["id"])}">')
        for column in meta["editable"]:
            value = row[column] if row else ""
            required = " required" if column in meta["required"] else ""
            if column in {"title", "filename", "spotify_url", "feed_url", "episode_title", "playlist_url"}:
                control = f'<textarea name="{_esc(column)}"{required}>{_esc(value)}</textarea>'
            elif column == "synced_to_ipod":
                selected_0 = " selected" if str(value or "0") == "0" else ""
                selected_1 = " selected" if str(value) == "1" else ""
                control = f'<select name="synced_to_ipod"><option value="0"{selected_0}>No</option><option value="1"{selected_1}>Si</option></select>'
            else:
                control = f'<input name="{_esc(column)}" value="{_esc(value)}"{required}>'
            fields.append(f'<label><span>{_esc(column)}</span>{control}</label>')
        cancel_url = f"/?table={table}"
        return f'''<h2>{title}: {_esc(meta["label"])}</h2>
<form class="form" method="post" action="/?table={_esc(table)}&action={action}">
  {''.join(fields)}
  <div class="actions">
    <button class="button" type="submit">Guardar</button>
    <a class="button" href="{cancel_url}">Cancelar</a>
  </div>
</form>'''


def run(host=None, port=None):
    database.initialize()
    host = host or config.WEB_HOST
    port = int(port or config.WEB_PORT)
    if host != "127.0.0.1" and not config.WEB_PASSWORD:
        logger.warning("Web admin expuesto fuera de localhost sin YTIPOD_WEB_PASSWORD")
    server = ThreadingHTTPServer((host, port), AdminHandler)
    logger.info("Web admin escuchando en http://%s:%s", host, port)
    server.serve_forever()
