import logging
import mimetypes
import re
import shutil
import subprocess
import tempfile
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from lxml import etree

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


def _resolve_image_url(attrs, base_url):
    attr_map = {key.lower(): value for key, value in attrs}
    candidate = None
    for key in ("src", "data-src", "data-original", "data-lazy-src", "url", "href", "target"):
        if attr_map.get(key):
            candidate = attr_map[key]
            break
    if not candidate:
        srcset = attr_map.get("srcset") or attr_map.get("data-srcset")
        if srcset:
            candidate = srcset.split(",", 1)[0].strip().split(" ", 1)[0]
    if not candidate:
        return None
    return urljoin(base_url, candidate)


def _image_extension(image_url, content_type):
    suffix = Path(urlparse(image_url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    guessed = mimetypes.guess_extension(content_type or "") or ".jpg"
    return ".jpg" if guessed == ".jpe" else guessed


def _fetch_binary(url):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 ytipod/1.0"})
    with urlopen(request, timeout=60) as response:
        return response.read(), response.headers.get_content_type()


def _rewrite_images_for_epub(xml_text, base_url, assets_dir):
    assets_dir.mkdir(parents=True, exist_ok=True)
    parser = etree.XMLParser(recover=True, remove_blank_text=False)
    root = etree.fromstring(xml_text.encode("utf-8"), parser=parser)
    image_map = {}
    image_index = 0

    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        local_name = etree.QName(element).localname
        if local_name not in {"img", "graphic"}:
            continue

        image_url = _resolve_image_url(element.items(), base_url)
        if not image_url:
            continue

        target_attr = "src" if local_name == "img" else "url"
        if image_url in image_map:
            element.set(target_attr, f"assets/{image_map[image_url]}")
            for attr in ("src", "srcset", "data-src", "data-original", "data-lazy-src", "url", "href", "target"):
                if attr != target_attr and attr in element.attrib:
                    element.attrib.pop(attr, None)
            continue

        try:
            data, content_type = _fetch_binary(image_url)
            image_index += 1
            ext = _image_extension(image_url, content_type)
            filename = f"image-{image_index:02d}{ext}"
            (assets_dir / filename).write_bytes(data)
            image_map[image_url] = filename
            element.set(target_attr, f"assets/{filename}")
            for attr in ("src", "srcset", "data-src", "data-original", "data-lazy-src", "url", "href", "target"):
                if attr != target_attr and attr in element.attrib:
                    element.attrib.pop(attr, None)
        except Exception:
            logger.exception("No se pudo descargar una imagen para el EPUB: %s", image_url)

    return etree.tostring(root, encoding="unicode")


def build_epub_from_url(url, output_dir):
    if trafilatura is None:
        raise RuntimeError("Falta la libreria Python trafilatura en el entorno")
    if not shutil.which("pandoc"):
        raise RuntimeError("No se encontro el comando pandoc en el sistema")

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=Path(config.TEMP_DIR)) as temp_dir:
        temp_dir = Path(temp_dir)
        xml_path = temp_dir / "article.tei.xml"
        epub_temp_path = temp_dir / "article.epub"
        assets_dir = temp_dir / "assets"

        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            raise RuntimeError("Trafilatura no pudo descargar el articulo")

        extracted_xml = trafilatura.extract(
            downloaded,
            url=url,
            output_format="xmltei",
            include_images=True,
            include_links=True,
            include_formatting=True,
            with_metadata=False,
        )
        if not extracted_xml:
            raise RuntimeError("Trafilatura no pudo extraer contenido legible")

        base_name = _slugify(urlparse(url).path.strip("/") or urlparse(url).hostname or "articulo")
        xml_filename = target_dir / f"{base_name}.tei.xml"
        xml_filename.write_text(extracted_xml, encoding="utf-8")

        rewritten_xml = _rewrite_images_for_epub(extracted_xml, url, assets_dir)
        xml_path.write_text(rewritten_xml, encoding="utf-8")
        title = _extract_html_title(rewritten_xml)
        if not title:
            parsed = urlparse(url)
            title = parsed.path.strip("/").split("/")[-1] or parsed.hostname or "articulo"

        filename = target_dir / f"{_slugify(title)}.epub"
        if filename.exists():
            filename.unlink()

        subprocess.run(
            ["pandoc", "-f", "tei", str(xml_path), "--resource-path", str(temp_dir), "-o", str(epub_temp_path)],
            check=True,
        )
        epub_temp_path.replace(filename)

    logger.info("EPUB generado: %s", filename)
    return filename, title
