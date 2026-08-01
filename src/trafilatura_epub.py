import logging
import mimetypes
import re
import shutil
import subprocess
import tempfile
import unicodedata
from html import escape
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
    for key in ("url", "src", "href", "target", "data-src", "data-original", "data-lazy-src"):
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


def _tei_ns(root):
    if isinstance(root.tag, str) and root.tag.startswith("{"):
        return root.tag.split("}", 1)[0][1:]
    return None


def _tei_xpath(root, path):
    ns = _tei_ns(root)
    if ns:
        return root.xpath(path, namespaces={"tei": ns})
    return root.xpath(path)


def _tei_text(node):
    if node is None:
        return ""
    return " ".join(" ".join(node.itertext()).split()).strip()


def _extract_tei_title(xml_text):
    parser = etree.XMLParser(recover=True, remove_blank_text=False)
    root = etree.fromstring(xml_text.encode("utf-8"), parser=parser)
    for path in (
        ".//tei:titleStmt/tei:title",
        ".//titleStmt/title",
        ".//tei:head",
        ".//head",
    ):
        try:
            nodes = _tei_xpath(root, path)
        except Exception:
            nodes = []
        for node in nodes:
            text = _tei_text(node)
            if text:
                return text
    return ""


def _download_and_remap_tei_images(xml_text, base_url, assets_dir):
    assets_dir.mkdir(parents=True, exist_ok=True)
    parser = etree.XMLParser(recover=True, remove_blank_text=False)
    root = etree.fromstring(xml_text.encode("utf-8"), parser=parser)
    image_map = {}
    image_index = 0

    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        local_name = etree.QName(element).localname
        if local_name not in {"graphic", "img"}:
            continue

        image_url = _resolve_image_url(element.items(), base_url)
        if not image_url:
            continue

        if image_url in image_map:
            filename = image_map[image_url]
        else:
            try:
                data, content_type = _fetch_binary(image_url)
                image_index += 1
                ext = _image_extension(image_url, content_type)
                filename = f"image-{image_index:02d}{ext}"
                (assets_dir / filename).write_bytes(data)
                image_map[image_url] = filename
            except Exception:
                logger.exception("No se pudo descargar una imagen para el EPUB: %s", image_url)
                continue

        if local_name == "graphic":
            element.attrib.clear()
            element.set("url", f"assets/{filename}")
        else:
            element.set("src", f"assets/{filename}")
            for attr in ("srcset", "data-src", "data-original", "data-lazy-src"):
                element.attrib.pop(attr, None)

    return root


def _render_inline(node):
    if not isinstance(node.tag, str):
        return ""

    tag = etree.QName(node).localname
    text = escape(node.text or "")
    children = "".join(_render_inline(child) for child in node)
    tail = escape(node.tail or "")

    if tag in {"hi", "emph"}:
        content = f"{text}{children}"
        return f"<em>{content}</em>{tail}"
    if tag == "ref":
        href = escape(node.get("target") or node.get("url") or "", quote=True)
        content = f"{text}{children}"
        if href:
            return f'<a href="{href}">{content}</a>{tail}'
        return f"{content}{tail}"
    if tag == "graphic":
        src = escape(node.get("url") or node.get("src") or "", quote=True)
        if src:
            return f'<img src="{src}" alt="" />{tail}'
        return tail
    if tag == "lb":
        return f"<br />{tail}"
    if tag in {"seg", "span"}:
        return f"{text}{children}{tail}"
    if tag == "note":
        content = f"{text}{children}"
        return f'<span class="note">{content}</span>{tail}'
    return f"{text}{children}{tail}"


def _render_block(node):
    if not isinstance(node.tag, str):
        return ""

    tag = etree.QName(node).localname
    text = escape(node.text or "")
    children = "".join(_render_block(child) for child in node)
    tail = escape(node.tail or "")

    if tag == "p":
        return f"<p>{text}{children}</p>{tail}"
    if tag == "head":
        return f"<h2>{text}{children}</h2>{tail}"
    if tag == "quote":
        return f"<blockquote>{text}{children}</blockquote>{tail}"
    if tag == "list":
        items = "".join(_render_block(child) for child in node if isinstance(child.tag, str) and etree.QName(child).localname == "item")
        return f"<ul>{items}</ul>{tail}"
    if tag == "item":
        return f"<li>{text}{children}</li>{tail}"
    if tag == "figure":
        inner = f"{text}{children}"
        return f"<figure>{inner}</figure>{tail}"
    if tag == "graphic":
        src = escape(node.get("url") or node.get("src") or "", quote=True)
        if src:
            return f'<figure><img src="{src}" alt="" /></figure>{tail}'
        return tail
    if tag in {"div", "body", "text", "front", "back", "article"}:
        return f"{text}{children}{tail}"
    if tag in {"hi", "emph", "ref", "seg", "span", "note", "lb"}:
        return _render_inline(node)
    return f"{text}{children}{tail}"


def _tei_to_html(xml_text, title, source_url):
    parser = etree.XMLParser(recover=True, remove_blank_text=False)
    root = etree.fromstring(xml_text.encode("utf-8"), parser=parser)
    body_nodes = _tei_xpath(root, ".//tei:text/tei:body") or _tei_xpath(root, ".//text/body")
    body = body_nodes[0] if body_nodes else root
    body_html = "".join(_render_block(child) for child in body)
    html_template = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="es">
<head>
  <title>{title}</title>
</head>
<body>
  <h1>{title}</h1>
  <p><a href="{source_url}">Fuente original</a></p>
  {body_html}
</body>
</html>
"""
    return html_template.format(
        title=escape(title),
        source_url=escape(source_url, quote=True),
        body_html=body_html,
    )


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

        title = _extract_tei_title(extracted_xml)
        if not title:
            parsed = urlparse(url)
            title = parsed.path.strip("/").split("/")[-1] or parsed.hostname or "articulo"

        tei_root = _download_and_remap_tei_images(extracted_xml, url, assets_dir)
        tei_with_assets = etree.tostring(tei_root, encoding="unicode")
        html_path.write_text(_tei_to_html(tei_with_assets, title, url), encoding="utf-8")

        filename = target_dir / f"{_slugify(title)}.epub"
        if filename.exists():
            filename.unlink()

        subprocess.run(
            ["pandoc", str(html_path), "-o", str(epub_temp_path)],
            check=True,
        )
        epub_temp_path.replace(filename)

    logger.info("EPUB generado: %s", filename)
    return filename, title
