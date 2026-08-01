import logging
import re
import shutil
import subprocess
import tempfile
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import config

try:
    import trafilatura
except ImportError:  # pragma: no cover - optional dependency at runtime
    trafilatura = None

logger = logging.getLogger(__name__)


class _TitleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self._in_title = False
        self._in_h1 = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        elif tag == "h1" and not self.title:
            self._in_h1 = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False

    def handle_data(self, data):
        text = " ".join(data.split())
        if not text:
            return
        if self._in_title or self._in_h1:
            if self.title:
                return
            self.title = text


def _extract_html_title(html_text):
    parser = _TitleParser()
    parser.feed(html_text)
    return parser.title.strip()


def _slugify(value):
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return value[:80] or "article"


def build_epub_from_url(url, output_dir):
    if trafilatura is None:
        raise RuntimeError("Falta la libreria Python trafilatura en el entorno")
    if not shutil.which("pandoc"):
        raise RuntimeError("No se encontro el comando pandoc en el sistema")

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=Path(config.TEMP_DIR)) as temp_dir:
        temp_dir = Path(temp_dir)
        html_path = temp_dir / "article.html"
        epub_temp_path = temp_dir / "article.epub"

        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            raise RuntimeError("Trafilatura no pudo descargar el articulo")

        extracted_html = trafilatura.extract(
            downloaded,
            url=url,
            output_format="html",
            include_images=True,
            include_links=True,
            include_formatting=True,
            with_metadata=False,
        )
        if not extracted_html:
            raise RuntimeError("Trafilatura no pudo extraer contenido legible")

        html_path.write_text(extracted_html, encoding="utf-8")
        title = _extract_html_title(extracted_html)
        if not title:
            parsed = urlparse(url)
            title = parsed.path.strip("/").split("/")[-1] or parsed.hostname or "articulo"

        filename = target_dir / f"{_slugify(title)}.epub"
        if filename.exists():
            filename.unlink()

        subprocess.run(["pandoc", str(html_path), "-o", str(epub_temp_path)], check=True)
        epub_temp_path.replace(filename)

    logger.info("EPUB generado: %s", filename)
    return filename, title
