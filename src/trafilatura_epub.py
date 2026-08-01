import copy
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

from lxml import etree, html as lxml_html

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


def _source_image_records(downloaded_html, base_url):
    """Return article images with their source position and optional caption."""
    try:
        document = lxml_html.fromstring(downloaded_html)
    except (etree.ParserError, ValueError):
        logger.warning("No se pudo analizar el HTML original para recuperar imagenes")
        return []

    article_images = document.xpath(
        "//article//figure//img | //main//figure//img | "
        "//article//*[contains(@class, 'featured-post-image')]//img | "
        "//main//*[contains(@class, 'featured-post-image')]//img | "
        "//article//*[contains(@class, 'hero')]//img | "
        "//main//*[contains(@class, 'hero')]//img | "
        "//article//*[contains(@class, 'rich-text')]//img | "
        "//main//*[contains(@class, 'rich-text')]//img"
    )
    images = article_images or document.xpath("//article//img | //main//img") or document.xpath("//img")
    records = []
    seen = set()
    for image in images:
        source = _resolve_image_url(image.items(), base_url)
        if not source or source in seen:
            continue
        seen.add(source)
        container = image.getparent()
        while container is not None and container.tag != "figure":
            container = container.getparent()
        caption_node = container.find(".//figcaption") if container is not None else None
        caption = _tei_text(caption_node) if caption_node is not None else ""
        if not caption:
            caption = " ".join((image.get("alt") or "").split())
        previous = container.getprevious() if container is not None else None
        anchor = _tei_text(previous) if previous is not None else ""
        records.append({"url": source, "caption": caption, "anchor": anchor})
    return records


def _source_image_urls(downloaded_html, base_url):
    return [record["url"] for record in _source_image_records(downloaded_html, base_url)]


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


def _add_missing_tei_image_urls(xml_text, base_url, source_images):
    """Populate empty TEI graphic nodes from the original article HTML."""
    parser = etree.XMLParser(recover=True, remove_blank_text=False)
    root = etree.fromstring(xml_text.encode("utf-8"), parser=parser)
    source_images = iter(source_images)

    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        local_name = etree.QName(element).localname
        if local_name not in {"graphic", "img"}:
            continue

        fallback = next(source_images, None)
        fallback_url = fallback["url"] if isinstance(fallback, dict) else fallback
        image_url = _resolve_image_url(element.items(), base_url) or fallback_url
        if not image_url:
            logger.warning("No se encontro URL para una imagen extraida por Trafilatura")
            continue

        if local_name == "graphic":
            element.set("url", image_url)
        else:
            element.set("src", image_url)

        caption = fallback.get("caption", "") if isinstance(fallback, dict) else ""
        parent = element.getparent()
        has_caption = parent is not None and any(
            isinstance(child.tag, str) and etree.QName(child).localname == "figDesc"
            for child in parent
        )
        if caption and local_name == "graphic" and parent is not None and not has_caption:
            namespace = _tei_ns(root)
            caption_node = etree.SubElement(
                parent,
                f"{{{namespace}}}figDesc" if namespace else "figDesc",
            )
            caption_node.text = caption

    return root


def _append_unrepresented_tei_images(root, image_records, graphic_count):
    """Insert omitted article images after their preceding paragraph."""
    missing_records = image_records[graphic_count:]
    if not missing_records:
        return

    body_nodes = _tei_xpath(root, ".//tei:text/tei:body") or _tei_xpath(root, ".//text/body")
    if not body_nodes:
        logger.warning("No se encontro el cuerpo TEI para agregar imagenes omitidas")
        return

    body = body_nodes[0]
    namespace = _tei_ns(root)
    tag = lambda name: f"{{{namespace}}}{name}" if namespace else name
    content = next(
        (node for node in body if isinstance(node.tag, str) and etree.QName(node).localname == "div"),
        body,
    )
    blocks = [node for node in content.iter() if isinstance(node.tag, str) and etree.QName(node).localname in {"p", "ab", "head"}]

    for index, record in enumerate(missing_records):
        figure = etree.Element(tag("figure"))
        graphic = etree.SubElement(figure, tag("graphic"))
        graphic.set("url", record["url"])
        if record.get("caption"):
            description = etree.SubElement(figure, tag("figDesc"))
            description.text = record["caption"]

        anchor = " ".join(record.get("anchor", "").split())[:120]
        target = next((node for node in blocks if anchor and anchor in _tei_text(node)), None)
        if target is not None:
            parent = target.getparent()
            parent.insert(parent.index(target) + 1, figure)
            continue

        # The first image without a preceding paragraph is normally the cover.
        # Keep it at the beginning; unanchored subsequent images remain in order.
        if index == 0:
            content.insert(0, figure)
        else:
            content.append(figure)
    logger.info("Se agregaron %d imagenes que Trafilatura habia omitido", len(missing_records))


def _download_and_remap_tei_images(root, assets_dir):
    """Download TEI image URLs and replace them with paths local to Pandoc."""
    assets_dir.mkdir(parents=True, exist_ok=True)
    image_map = {}
    image_index = 0

    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        local_name = etree.QName(element).localname
        if local_name not in {"graphic", "img"}:
            continue

        image_url = _resolve_image_url(element.items(), "")
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
            return f'<img src="{src}" alt="" />{tail}'
        return tail
    if tag == "figDesc":
        return f"<figcaption>{text}{children}</figcaption>{tail}"
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
        title = _extract_tei_title(extracted_xml)
        if not title:
            parsed = urlparse(url)
            title = parsed.path.strip("/").split("/")[-1] or parsed.hostname or "articulo"

        source_images = _source_image_records(downloaded, url)
        if source_images:
            logger.info("Se encontraron %d imagenes en el HTML original", len(source_images))
        else:
            logger.warning("No se encontraron imagenes en el HTML original")

        tei_graphic_count = sum(
            1
            for element in etree.fromstring(extracted_xml.encode("utf-8"), parser=etree.XMLParser(recover=True)).iter()
            if isinstance(element.tag, str) and etree.QName(element).localname in {"graphic", "img"}
        )
        matching_images = source_images
        if tei_graphic_count and len(source_images) > tei_graphic_count:
            # The HTML usually contains a cover before the body figures, while
            # Trafilatura's graphic positions start at the first body figure.
            matching_images = source_images[1:]
        enriched_tei = _add_missing_tei_image_urls(extracted_xml, url, matching_images)
        _append_unrepresented_tei_images(enriched_tei, matching_images, tei_graphic_count)
        xml_filename = target_dir / f"{base_name}.tei.xml"
        xml_filename.write_text(etree.tostring(enriched_tei, encoding="unicode"), encoding="utf-8")

        tei_for_epub = _download_and_remap_tei_images(copy.deepcopy(enriched_tei), assets_dir)
        tei_with_assets = etree.tostring(tei_for_epub, encoding="unicode")
        html_path.write_text(_tei_to_html(tei_with_assets, title, url), encoding="utf-8")

        filename = target_dir / f"{_slugify(title)}.epub"
        if filename.exists():
            filename.unlink()

        subprocess.run(
            [
                "pandoc",
                str(html_path),
                "--resource-path",
                str(temp_dir),
                "-o",
                str(epub_temp_path),
            ],
            check=True,
        )
        epub_temp_path.replace(filename)

    logger.info("EPUB generado: %s", filename)
    return filename, title
