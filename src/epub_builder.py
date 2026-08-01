import html
import json
import mimetypes
import re
import unicodedata
import uuid
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

_BLOCK_TAGS = {"p", "div", "section", "article", "br", "li", "h1", "h2", "h3", "h4", "blockquote", "hr"}
_SKIP_TAGS = {"style", "noscript", "svg", "nav", "footer", "header", "aside", "form"}
_INLINE_TAGS = {"a", "strong", "em", "b", "i", "u", "span"}
_IMAGE_ATTRS = ("src", "data-src", "data-original", "data-lazy-src")
_STOP_PHRASES = {
    "textos relacionados",
    "textos relaconados",
    "textos sugeridos",
    "related articles",
    "related posts",
    "more like this",
    "tambien te puede interesar",
    "también te puede interesar",
}
_AUTHOR_SCOPE_HINTS = ("author", "byline", "creator", "writer")


class ArticleParser(HTMLParser):
    def __init__(self, base_url):
        super().__init__()
        self.base_url = base_url
        self.title = ""
        self.author_name = ""
        self.author_image = ""
        self.author_bio = ""
        self._meta = {}
        self._in_title = False
        self._in_script = False
        self._capture_jsonld = False
        self._jsonld_buffer = []
        self._skip_depth = 0
        self._stop_collecting = False
        self._author_scope_depth = 0
        self._scope_stack = []
        self._chunks = []
        self._image_tokens = {}
        self.image_refs = []

    def _append(self, text):
        if text:
            self._chunks.append(text)

    def _newline(self):
        if not self._chunks or self._chunks[-1].endswith("\n"):
            return
        self._chunks.append("\n")

    def _attr_map(self, attrs):
        return {key.lower(): value for key, value in attrs}

    def _normalize(self, value):
        value = unicodedata.normalize("NFKD", value)
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        return re.sub(r"\s+", " ", value).strip().lower()

    def _should_stop(self, text):
        normalized = self._normalize(text)
        return any(phrase in normalized for phrase in _STOP_PHRASES)

    def _is_author_scope(self, attr_map):
        haystack = " ".join(str(attr_map.get(key, "")) for key in ("rel", "class", "itemprop", "aria-label", "data-testid"))
        haystack = self._normalize(haystack)
        return any(hint in haystack for hint in _AUTHOR_SCOPE_HINTS)

    def _meta_append(self, key, value):
        if not key or not value:
            return
        self._meta.setdefault(key.lower(), []).append(value.strip())

    def _resolve_image_url(self, attrs):
        attr_map = self._attr_map(attrs)
        candidate = None
        for key in _IMAGE_ATTRS:
            if attr_map.get(key):
                candidate = attr_map[key]
                break
        if not candidate:
            srcset = attr_map.get("srcset") or attr_map.get("data-srcset")
            if srcset:
                candidate = srcset.split(",", 1)[0].strip().split(" ", 1)[0]
        if not candidate:
            return None
        return urljoin(self.base_url, candidate)

    def _append_author_image_ref(self, image_url, alt=None):
        token = "__AUTHOR_IMAGE__"
        if any(ref.get("token") == token for ref in self.image_refs):
            return
        self.image_refs.append({"url": image_url, "token": token, "alt": alt or self.author_name or "Autor", "is_author": True})

    def _apply_jsonld(self, raw_json):
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError:
            return

        def iter_objects(obj):
            if isinstance(obj, list):
                for item in obj:
                    yield from iter_objects(item)
            elif isinstance(obj, dict):
                yield obj
                for key in ("@graph", "itemListElement"):
                    value = obj.get(key)
                    if value:
                        yield from iter_objects(value)

        for obj in iter_objects(payload):
            author = obj.get("author") or obj.get("creator")
            if isinstance(author, list):
                author = author[0] if author else None
            if isinstance(author, dict):
                if not self.author_name and author.get("name"):
                    self.author_name = str(author.get("name")).strip()
                if not self.author_bio and author.get("description"):
                    self.author_bio = str(author.get("description")).strip()
                image = author.get("image")
                if isinstance(image, dict):
                    image = image.get("url") or image.get("contentUrl")
                if isinstance(image, list):
                    image = image[0] if image else None
                if image and not self.author_image:
                    self.author_image = urljoin(self.base_url, str(image))
            elif isinstance(author, str) and not self.author_name:
                self.author_name = author.strip()

    def _extract_author_from_meta(self):
        for key in ("author", "article:author", "parsely-author", "byline"):
            values = self._meta.get(key)
            if values and not self.author_name:
                self.author_name = values[0]
        for key in ("author:image", "article:author_image", "parsely-author-image"):
            values = self._meta.get(key)
            if values and not self.author_image:
                self.author_image = urljoin(self.base_url, values[0])
        for key in ("author:description", "parsely-author-bio"):
            values = self._meta.get(key)
            if values and not self.author_bio:
                self.author_bio = values[0]

    def resolve_author(self):
        self._extract_author_from_meta()
        if self._jsonld_buffer:
            self._apply_jsonld("\n".join(self._jsonld_buffer))
        if self.author_image:
            self.author_image = urljoin(self.base_url, self.author_image)
        self.author_name = self.author_name.strip()
        self.author_bio = self.author_bio.strip()

    def handle_starttag(self, tag, attrs):
        attr_map = self._attr_map(attrs)
        is_author_scope = self._is_author_scope(attr_map)
        self._scope_stack.append(is_author_scope)
        if is_author_scope:
            self._author_scope_depth += 1

        if tag == "title":
            self._in_title = True
            return
        if tag == "meta":
            name = attr_map.get("name") or attr_map.get("property")
            content = attr_map.get("content")
            if name and content:
                self._meta_append(name, content)
            return
        if tag == "script":
            script_type = (attr_map.get("type") or "").lower()
            if "ld+json" in script_type:
                self._capture_jsonld = True
                self._jsonld_buffer = []
            else:
                self._in_script = True
            return
        if self._skip_depth or self._stop_collecting or self._in_script or self._capture_jsonld:
            return
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag in _BLOCK_TAGS:
            self._newline()
            return
        if tag == "img":
            image_url = self._resolve_image_url(attrs)
            if not image_url:
                return
            if self._author_scope_depth > 0 and not self.author_image:
                self.author_image = image_url
                self._append_author_image_ref(image_url, attr_map.get("alt", self.author_name))
            token = self._image_tokens.get(image_url)
            if token is None:
                token = f"__IMAGE_{len(self.image_refs)}__"
                self._image_tokens[image_url] = token
                self.image_refs.append({"url": image_url, "token": token, "alt": attr_map.get("alt", "")})
            alt = html.escape(attr_map.get("alt", ""), quote=True)
            self._append(f'<img src="{token}" alt="{alt}" />')
            return
        if tag == "a":
            href = attr_map.get("href")
            if href:
                href = html.escape(urljoin(self.base_url, href), quote=True)
                self._append(f'<a href="{href}">')
            else:
                self._append("<a>")
            return
        if tag in _INLINE_TAGS - {"a"}:
            self._append(f"<{tag}>")

    def handle_endtag(self, tag):
        if self._scope_stack:
            was_author_scope = self._scope_stack.pop()
            if was_author_scope:
                self._author_scope_depth = max(0, self._author_scope_depth - 1)

        if tag == "title":
            self._in_title = False
            return
        if tag == "script":
            if self._capture_jsonld:
                self._capture_jsonld = False
                self._apply_jsonld("".join(self._jsonld_buffer))
                self._jsonld_buffer = []
            self._in_script = False
            return
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth or self._stop_collecting or self._in_script or self._capture_jsonld:
            return
        if tag in _BLOCK_TAGS:
            self._newline()
            return
        if tag == "a":
            self._append("</a>")
            return
        if tag in _INLINE_TAGS - {"a"}:
            self._append(f"</{tag}>")

    def handle_data(self, data):
        text = " ".join(data.split())
        if not text:
            return
        if self._in_title:
            self.title += text + " "
            return
        if self._capture_jsonld:
            self._jsonld_buffer.append(data)
            return
        if self._skip_depth or self._stop_collecting or self._in_script:
            return
        if self._should_stop(text):
            self._stop_collecting = True
            return
        self._append(html.escape(text))

    def handle_entityref(self, name):
        if self._skip_depth or self._in_title or self._stop_collecting or self._in_script:
            return
        self._append(f"&{name};")

    def handle_charref(self, name):
        if self._skip_depth or self._in_title or self._stop_collecting or self._in_script:
            return
        self._append(f"&#{name};")

    def article_html(self):
        html_text = "".join(self._chunks)
        html_text = re.sub(r"\n{3,}", "\n\n", html_text)
        return html_text.strip()

    def article_text(self):
        text = self.article_html()
        text = re.sub(r"<img[^>]*>", "", text)
        text = re.sub(r"</?(?:a|strong|em|b|i|u|span)>", "", text)
        text = re.sub(r"<[^>]+>", "\n", text)
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
        return response.read().decode(charset, errors="replace"), response.geturl()


def _fetch_binary(url):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 ytipod/1.0"})
    with urlopen(request, timeout=60) as response:
        content_type = response.headers.get_content_type()
        return response.read(), content_type


def _image_extension(image_url, content_type):
    suffix = Path(urlparse(image_url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    guessed = mimetypes.guess_extension(content_type or "") or ".jpg"
    return ".jpg" if guessed == ".jpe" else guessed


def _download_images(image_refs, images_dir):
    images_dir.mkdir(parents=True, exist_ok=True)
    for index, ref in enumerate(image_refs, start=1):
        try:
            data, content_type = _fetch_binary(ref["url"])
            ext = _image_extension(ref["url"], content_type)
            filename = f"image-{index:02d}{ext}"
            (images_dir / filename).write_bytes(data)
            ref["filename"] = filename
            ref["media_type"] = mimetypes.guess_type(filename)[0] or content_type or "image/jpeg"
        except Exception:
            ref["filename"] = None
            ref["media_type"] = None


def _render_author_block(author_name, author_image, author_bio, image_refs):
    if not author_name:
        return ""

    image_html = ""
    if author_image:
        token = "__AUTHOR_IMAGE__"
        if not any(ref.get("token") == token for ref in image_refs):
            image_refs.append({"url": author_image, "token": token, "alt": author_name, "is_author": True})
        image_html = f'<img class="author-photo" src="{token}" alt="{html.escape(author_name, quote=True)}" />'

    bio_html = f'<p class="author-bio">{html.escape(author_bio)}</p>' if author_bio else ""
    return f"""<section class="author-block">\n  {image_html}\n  <div class="author-copy">\n    <p class="author-label">Autor</p>\n    <p class="author-name">{html.escape(author_name)}</p>\n    {bio_html}\n  </div>\n</section>"""


def _render_chapter(title, url, content_html, author_block, image_refs):
    rendered = author_block
    if rendered and content_html:
        rendered += "\n"
    rendered += content_html
    for ref in image_refs:
        token = ref["token"]
        if ref.get("filename"):
            replacement = f'<img src="images/{ref["filename"]}" alt="{html.escape(ref.get("alt", ""), quote=True)}" />'
        else:
            alt = html.escape(ref.get("alt") or "imagen", quote=True)
            replacement = f'<p>[{alt}]</p>'
        rendered = rendered.replace(token, replacement)
    if rendered and not rendered.endswith("\n"):
        rendered += "\n"
    rendered += f'<p><a href="{html.escape(url, quote=True)}">Fuente original</a></p>'

    return f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="es">
<head>
<title>{html.escape(title)}</title>
<style>
body {{ font-family: serif; line-height: 1.5; }}
.author-block {{ display: flex; gap: 12px; align-items: flex-start; margin: 1em 0 1.2em; padding: 0.8em 0; border-top: 1px solid #ccc; border-bottom: 1px solid #ccc; }}
.author-photo {{ width: 72px; height: 72px; object-fit: cover; border-radius: 50%; flex: 0 0 auto; }}
.author-label {{ margin: 0; font-size: 0.8em; text-transform: uppercase; letter-spacing: 0.04em; color: #666; }}
.author-name {{ margin: 0.15em 0 0; font-weight: bold; }}
.author-bio {{ margin: 0.35em 0 0; }}
</style>
</head>
<body>
<h1>{html.escape(title)}</h1>
{rendered}
</body>
</html>
"""


def article_to_epub(url, output_dir):
    raw_html, final_url = _fetch_html(url)
    parser = ArticleParser(final_url)
    parser.feed(raw_html)
    parser.resolve_author()

    parsed = urlparse(final_url)
    title = html.unescape(parser.title.strip()) or parsed.path.strip("/").split("/")[-1] or parsed.hostname or "article"
    content_html = parser.article_html()
    text = parser.article_text()
    if not content_html and not text:
        raise RuntimeError("No pude extraer texto legible de la pagina")

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    filename = output / f"{_slugify(title)}.epub"
    book_id = f"urn:uuid:{uuid.uuid4()}"
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not content_html and text:
        content_html = "\n".join(f"<p>{html.escape(paragraph)}</p>" for paragraph in text.split("\n\n"))

    image_refs = parser.image_refs
    author_block = _render_author_block(parser.author_name, parser.author_image, parser.author_bio, image_refs)
    images_dir = output / "_epub_assets" / _slugify(title)
    _download_images(image_refs, images_dir)
    chapter = _render_chapter(title, final_url, content_html, author_block, image_refs)

    container = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

    manifest_items = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav" />',
        '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml" />',
    ]
    image_entries = []
    for index, ref in enumerate(image_refs, start=1):
        if not ref.get("filename"):
            continue
        media_type = ref.get("media_type") or mimetypes.guess_type(ref["filename"])[0] or "image/jpeg"
        manifest_items.append(f'<item id="img{index}" href="images/{ref["filename"]}" media-type="{media_type}" />')
        image_entries.append((ref["filename"], images_dir / ref["filename"]))

    creator_line = f"    <dc:creator>{html.escape(parser.author_name)}</dc:creator>\n" if parser.author_name else ""
    opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{book_id}</dc:identifier>
    <dc:title>{html.escape(title)}</dc:title>
{creator_line}    <dc:language>es</dc:language>
    <meta property="dcterms:modified">{modified}</meta>
  </metadata>
  <manifest>
    {'\n    '.join(manifest_items)}
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
        for image_filename, image_path in image_entries:
            epub.writestr(f"OEBPS/images/{image_filename}", image_path.read_bytes())

    return filename, title
