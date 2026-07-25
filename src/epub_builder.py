import html
import re
import uuid
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

_BLOCK_TAGS = {"p", "div", "section", "article", "br", "li", "h1", "h2", "h3", "h4", "blockquote"}
_SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form"}


class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self._in_title = False
        self._skip_depth = 0
        self._chunks = []

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        if tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data):
        text = " ".join(data.split())
        if not text:
            return
        if self._in_title:
            self.title += text + " "
            return
        if self._skip_depth:
            return
        self._chunks.append(text + " ")

    def article_text(self):
        text = "".join(self._chunks)
        lines = [line.strip() for line in text.splitlines()]
        lines = [line for line in lines if len(line) > 20]
        return "\n\n".join(lines)


def _slugify(value):
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return value[:80] or "article"


def _fetch_html(url):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 ytipod/1.0"})
    with urlopen(request, timeout=60) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def article_to_epub(url, output_dir):
    raw_html = _fetch_html(url)
    parser = ArticleParser()
    parser.feed(raw_html)

    parsed = urlparse(url)
    title = html.unescape(parser.title.strip()) or parsed.path.strip("/").split("/")[-1] or parsed.hostname or "article"
    text = parser.article_text()
    if not text:
        raise RuntimeError("No pude extraer texto legible de la pagina")

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    filename = output / f"{_slugify(title)}.epub"
    book_id = f"urn:uuid:{uuid.uuid4()}"
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    paragraphs = "\n".join(f"<p>{html.escape(paragraph)}</p>" for paragraph in text.split("\n\n"))
    chapter = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="es">
<head><title>{html.escape(title)}</title></head>
<body>
<h1>{html.escape(title)}</h1>
{paragraphs}
<p><a href="{html.escape(url)}">Fuente original</a></p>
</body>
</html>
"""
    container = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""
    opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{book_id}</dc:identifier>
    <dc:title>{html.escape(title)}</dc:title>
    <dc:language>es</dc:language>
    <meta property="dcterms:modified">{modified}</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chapter"/>
  </spine>
</package>
"""
    nav = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="es">
<head><title>{html.escape(title)}</title></head>
<body><nav epub:type="toc" xmlns:epub="http://www.idpf.org/2007/ops"><ol><li><a href="chapter.xhtml">{html.escape(title)}</a></li></ol></nav></body>
</html>
"""

    with zipfile.ZipFile(filename, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        epub.writestr("META-INF/container.xml", container)
        epub.writestr("OEBPS/content.opf", opf)
        epub.writestr("OEBPS/nav.xhtml", nav)
        epub.writestr("OEBPS/chapter.xhtml", chapter)

    return filename, title
