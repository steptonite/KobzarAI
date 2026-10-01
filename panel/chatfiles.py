"""Файли в чаті Кобзаря (30.09.2026): типи, картки, перегляд тексту, що бачить модель,
локальний «сервер» для відео/звуку й нативне перетягування файлів на вікно чату.

Чиста логіка (без Cocoa) лежить угорі — її перевіряють тести без застосунку.
Cocoa-частина (схема kobzar-file://, WKWebView з drop) — унизу, у блоці try.
"""
import os, re, json, shutil, subprocess, mimetypes, urllib.request, urllib.parse, base64, tempfile

# ── типи файлів ────────────────────────────────────────────────────────────
IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".tif", ".tiff"}
VID_EXT = {".mp4", ".mov", ".webm", ".m4v"}
AUD_EXT = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".opus", ".aif", ".aiff"}
MD_EXT = {".md", ".markdown"}
TXT_EXT = {".txt", ".log", ".text"}
CSV_EXT = {".csv", ".tsv"}
JSON_EXT = {".json", ".jsonl"}
CODE_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".htm", ".css", ".sh", ".zsh", ".swift", ".c", ".h",
            ".cpp", ".java", ".go", ".rs", ".rb", ".php", ".yaml", ".yml", ".toml", ".xml", ".ini", ".sql", ".cfg"}
DOC_EXT = {".docx", ".doc", ".odt", ".rtf", ".pages"}
SHEET_EXT = {".xlsx", ".xls", ".numbers", ".ods"}
SLIDES_EXT = {".pptx", ".ppt", ".key", ".odp"}
ZIP_EXT = {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz"}

LABEL = {"img": "Картинка", "vid": "Відео", "aud": "Звук", "md": "Markdown", "txt": "Текст",
         "csv": "Таблиця CSV", "json": "JSON", "code": "Код", "pdf": "PDF", "doc": "Документ",
         "sheet": "Таблиця", "slides": "Презентація", "zip": "Архів", "file": "Файл"}
TEXT_KINDS = ("md", "txt", "csv", "json", "code")           # читаються як звичайний текст
PREV_HEAD_LINES = 40
PREV_FULL_CAP = 200 * 1024                                   # «Показати все» — не більше 200 КБ тексту
# відкриття цих типів системою ЗАПУСКАЄ їх — замість «Відкрити» показуємо у Finder
RUNNABLE_EXT = {".app", ".command", ".sh", ".zsh", ".pkg", ".dmg", ".scpt", ".workflow", ".terminal",
                ".jar", ".exe", ".bat", ".msi", ".action", ".tool", ".url", ".webloc", ".pl", ".py", ".rb"}


def kind_of(path):
    ext = os.path.splitext(path or "")[1].lower()
    for k, s in (("img", IMG_EXT), ("vid", VID_EXT), ("aud", AUD_EXT), ("md", MD_EXT), ("txt", TXT_EXT),
                 ("csv", CSV_EXT), ("json", JSON_EXT), ("code", CODE_EXT), ("doc", DOC_EXT),
                 ("sheet", SHEET_EXT), ("slides", SLIDES_EXT), ("zip", ZIP_EXT)):
        if ext in s:
            return k
    return "pdf" if ext == ".pdf" else "file"


def human_size(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    if n < 1024:
        return "%d Б" % n
    for u in ("КБ", "МБ", "ГБ"):
        n /= 1024.0
        if n < 1024 or u == "ГБ":
            s = ("%.1f" % n) if n < 10 else ("%d" % round(n))
            return s.replace(".", ",") + " " + u


def card_info(path, name=None):
    """Те, що потрібно сторінці для картки файлу."""
    path = path or ""
    gone = not os.path.isfile(path)
    k = kind_of(path)
    size = 0
    if not gone:
        try: size = os.path.getsize(path)
        except OSError: gone = True
    d = {"name": name or os.path.basename(path), "path": path, "kind": k, "gone": gone,
         "size": human_size(size), "label": LABEL.get(k, "Файл"),
         "prev": k in TEXT_KINDS and not gone}
    if not gone and k in ("vid", "aud"):
        d["src"] = serve_url(path)
    return d


def token_tail(path):
    """Хвіст токена ![[file:NAME|PATH]](file:kind,size) для відповідей, що несуть файли."""
    try: size = human_size(os.path.getsize(path))
    except OSError: size = ""
    return "file:%s,%s" % (kind_of(path), size.replace(" ", "\u00a0"))


# ── перегляд тексту прямо в чаті ──────────────────────────────────────────
def read_text(path, max_bytes=PREV_FULL_CAP):
    """(текст, файл_більший_за_ліміт). Кодування: BOM utf-16 / utf-8 / cp1251 запасом."""
    with open(path, "rb") as fh:
        raw = fh.read(max_bytes + 1)
    cut = len(raw) > max_bytes
    raw = raw[:max_bytes]
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        txt = raw.decode("utf-16", "replace")
    else:
        try:
            txt = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            if cut:                                   # рвемо посередині символу — відкинути хвіст
                raw = raw[:-3]
            try: txt = raw.decode("utf-8")
            except UnicodeDecodeError: txt = raw.decode("cp1251", "replace")
    return txt.replace("\r\n", "\n").replace("\r", "\n"), cut


def preview(path, head_lines=PREV_HEAD_LINES, cap=PREV_FULL_CAP):
    """{head, full, total, more, cut}: перші head_lines рядків + (на «Показати все») до cap байтів."""
    txt, cut = read_text(path, cap)
    lines = txt.split("\n")
    total = len(lines) - (1 if lines and lines[-1] == "" else 0)
    head = "\n".join(lines[:head_lines])
    return {"head": head, "full": txt, "total": total, "more": total > head_lines or cut, "cut": cut,
            "kind": kind_of(path)}


# ── текст для локальної моделі ────────────────────────────────────────────
_TEXTUTIL_EXT = {".docx", ".doc", ".odt", ".rtf", ".html", ".htm"}


def _textutil(path, timeout=25):
    r = subprocess.run(["/usr/bin/textutil", "-convert", "txt", "-stdout", path],
                       capture_output=True, timeout=timeout)
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", "replace")


def _pdf_text(path):
    try:
        import Quartz as Q
        from Foundation import NSURL
        doc = Q.PDFDocument.alloc().initWithURL_(NSURL.fileURLWithPath_(path))
        if doc is None or doc.isLocked():
            return None
        return str(doc.string() or "")
    except Exception:
        return None


def extract_text(path, cap_chars):
    """(текст або None, обрізано?). None = достати текст не вдалось (преза, архів, скан, зіпсований)."""
    k = kind_of(path)
    ext = os.path.splitext(path)[1].lower()
    try:
        if k in TEXT_KINDS:
            txt, cut = read_text(path, max(cap_chars * 4, 4096))
        elif ext in _TEXTUTIL_EXT:
            txt, cut = _textutil(path), False
        elif k == "pdf":
            txt, cut = _pdf_text(path), False
        else:
            return None, False
    except Exception:
        return None, False
    if txt is None:
        return None, False
    if k not in TEXT_KINDS and not txt.strip():        # порожній витяг із pdf/docx = скан чи порожній файл
        return None, False
    txt = txt.strip("\n")
    if len(txt) > cap_chars:
        return txt[:max(cap_chars, 0)], True
    return txt, cut


ALT_HINT = ""   # необовʼязкова підказка «що робити далі»; ставиться ззовні (додатковим модулем)


def _hint():
    return (" " + ALT_HINT) if ALT_HINT else ""


def local_context(atts, budget_chars, vision=False, image_b64=None):
    """Що віддати ЛОКАЛЬНІЙ моделі з вкладень і що чесно сказати користувачу.
    atts: [{name, path, kind}]; budget_chars — спільна стеля на текст усіх файлів.
    Повертає {text, images, notes}: text дописується до повідомлення, images — для моделі з зором."""
    blocks, images, notes = [], [], []
    left = int(budget_chars)
    seen_blind = set()
    for a in atts or []:
        p = a.get("path", "")
        nm = a.get("name") or os.path.basename(p)
        k = a.get("kind") or kind_of(p)
        k = kind_of(p) if k == "file" else k
        if k == "img":
            if vision and image_b64:
                b = image_b64(p)
                if b:
                    images.append(b); continue
            if "img" not in seen_blind:
                seen_blind.add("img")
                notes.append("Ця модель не бачить картинок — отримала лише текст." + _hint())
            blocks.append("[Додано картинку «%s» — її вміст недоступний]" % nm)
            continue
        if k in ("vid", "aud"):
            word = "відео" if k == "vid" else "звук"
            if k not in seen_blind:
                seen_blind.add(k)
                notes.append("Ця модель не бачить і не чує %s — отримала лише назву файлу." % word + _hint())
            blocks.append("[Додано %s «%s» — його вміст недоступний]" % (word, nm))
            continue
        if not os.path.isfile(p):
            notes.append("Файл «%s» не знайдено на диску — модель його не отримала" % nm)
            continue
        if left <= 0:
            notes.append("Файл «%s» не влазить у памʼять моделі — отримала лише назву" % nm)
            blocks.append("[Додано файл «%s» — не влізло]" % nm)
            continue
        txt, cut = extract_text(p, left)
        if txt is None:
            notes.append("Модель не може прочитати файл «%s» — отримала лише назву" % nm)
            blocks.append("[Додано файл «%s» — його вміст недоступний]" % nm)
            continue
        left -= len(txt)
        if cut:
            notes.append("Файл «%s» обрізано — у памʼять моделі влізла лише його частина" % nm)
        blocks.append("[Файл «%s»%s]\n%s\n[кінець файлу]" % (nm, " (обрізано)" if cut else "", txt or "(порожній)"))
    return {"text": "\n\n".join(blocks), "images": images, "notes": notes}


# ── чи бачить локальна модель картинки ────────────────────────────────────
_VISION_CACHE = {}
_VISION_NAME = re.compile(r"llava|bakllava|vision|minicpm-v|moondream|qwen[\d.]*-?vl|(^|[/:_-])vl([:_-]|$)|"
                          r"gemma3(:(4b|12b|27b|latest)|$)|gemma-?3n|llama4|mistral-small3|pixtral|granite\d*(\.\d+)?-vision",
                          re.I)


def _fetch_caps(model, host, timeout=3):
    req = urllib.request.Request("http://%s/api/show" % host, json.dumps({"model": model}).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8")).get("capabilities")


def model_has_vision(model, host="127.0.0.1:11434", fetch=None):
    """True/False. Ollama /api/show → capabilities (є "vision"); кеш на модель. Якщо Ollama не
    відповіла або стара версія без capabilities — здогад за назвою (не кешується)."""
    if not model:
        return False
    if model in _VISION_CACHE:
        return _VISION_CACHE[model]
    try:
        caps = (fetch or _fetch_caps)(model, host)
    except Exception:
        caps = None
    if isinstance(caps, list):
        _VISION_CACHE[model] = "vision" in caps
        return _VISION_CACHE[model]
    return bool(_VISION_NAME.search(model))


def image_b64(path, px=1280):
    """Картинка для моделі з зором: JPEG ≤px (sips), base64. None якщо не вийшло."""
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix=".jpg", prefix="kobzar-vis-"); os.close(fd)
        r = subprocess.run(["/usr/bin/sips", "-Z", str(px), "-s", "format", "jpeg", "-s", "formatOptions", "80",
                            path, "--out", tmp], capture_output=True, timeout=30)
        if r.returncode != 0 or os.path.getsize(tmp) == 0:
            return None
        with open(tmp, "rb") as fh:
            return base64.b64encode(fh.read()).decode("ascii")
    except Exception:
        return None
    finally:
        if tmp:
            try: os.remove(tmp)
            except OSError: pass


# ── «Зберегти оригінал» / «Відкрити» / «Показати у Finder» ────────────────
def unique_dest(dst_dir, name):
    os.makedirs(dst_dir, exist_ok=True)
    name = re.sub(r"[/\\:\x00-\x1f]", "_", name or "файл").strip(". ") or "файл"
    base, ext = os.path.splitext(name)
    dst, n = os.path.join(dst_dir, name), 1
    while os.path.exists(dst):
        n += 1; dst = os.path.join(dst_dir, "%s %d%s" % (base, n, ext))
    return dst


def save_copy(src, dst=None, dst_dir=None):
    """Повна якість: побайтова копія (APFS-клон), не перекодування. dst — кінцевий шлях із NSSavePanel;
    без нього — у dst_dir (типово ~/Downloads) з унікальним імʼям. Повертає шлях копії."""
    if dst is None:
        dst = unique_dest(dst_dir or os.path.expanduser("~/Downloads"), os.path.basename(src))
    else:
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        if os.path.exists(dst):
            os.remove(dst)
    if subprocess.run(["cp", "-c", src, dst], capture_output=True).returncode != 0:
        shutil.copy2(src, dst)
    return dst


def open_cmd(path):
    """Команда для кнопки «Відкрити». Запускні типи (.app, .command, .sh…) не запускаємо — лише показуємо у Finder."""
    ext = os.path.splitext(path)[1].lower()
    if os.path.isdir(path) or ext in RUNNABLE_EXT:
        return ["open", "-R", path]
    if ext in (".json", ".jsonl", ".yaml", ".yml", ".log"):
        return ["open", "-t", path]                      # часто без програми за замовчуванням
    return ["open", path]


# ── локальна схема kobzar-file:// (відео/звук без base64) ─────────────────
SCHEME = "kobzar-file"
_SERVE_OK = set()
_MIME_FIX = {".m4a": "audio/mp4", ".mov": "video/quicktime", ".mp4": "video/mp4", ".m4v": "video/mp4",
             ".mp3": "audio/mpeg", ".wav": "audio/wav", ".aac": "audio/aac", ".flac": "audio/flac",
             ".ogg": "audio/ogg", ".opus": "audio/ogg", ".webm": "video/webm", ".aif": "audio/aiff",
             ".aiff": "audio/aiff"}
RANGE_CHUNK = 4 * 1024 * 1024


def serve_url(path):
    """Дозволяє віддачу файлу сторінці й повертає його kobzar-file://-адресу. Лише те, що дала панель."""
    _SERVE_OK.add(os.path.realpath(path))
    try: sz = human_size(os.path.getsize(path))
    except OSError: sz = ""
    return "%s://%s?s=%s" % (SCHEME, urllib.parse.quote(path), urllib.parse.quote(sz))


def serve_allowed(path):
    return os.path.realpath(path) in _SERVE_OK and os.path.isfile(path)


def mime_of(path):
    ext = os.path.splitext(path)[1].lower()
    return _MIME_FIX.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"


def parse_range(header, size):
    """'bytes=0-' → (0, size-1); 'bytes=10-19' → (10, 19); '-500' → останні 500. None = нема/негодяще.
    Довгі відповіді ріжемо на шматки RANGE_CHUNK — плеєр сам докине наступні запити."""
    if not header or size <= 0:
        return None
    m = re.match(r"\s*bytes\s*=\s*(\d*)\s*-\s*(\d*)\s*$", header)
    if not m or (m.group(1) == "" and m.group(2) == ""):
        return None
    if m.group(1) == "":
        n = int(m.group(2)); start, end = max(0, size - n), size - 1
    else:
        start = int(m.group(1)); end = int(m.group(2)) if m.group(2) else size - 1
    if start >= size or end < start:
        return "bad"
    end = min(end, size - 1, start + RANGE_CHUNK - 1)
    return (start, end)


def plan_response(path, header):
    """(status, headers, start, end) для запиту до локального файлу — чиста логіка обробника."""
    size = os.path.getsize(path)
    mime = mime_of(path)
    rg = parse_range(header, size)
    if rg == "bad":
        return 416, {"Content-Range": "bytes */%d" % size, "Content-Length": "0"}, 0, -1
    if rg is None:
        if size > 64 * 1024 * 1024:                       # без Range велике не віддаємо цілим — перший шматок як 206
            rg = (0, min(size - 1, RANGE_CHUNK - 1))
        else:
            return 200, {"Content-Type": mime, "Content-Length": str(size), "Accept-Ranges": "bytes"}, 0, size - 1
    start, end = rg
    return 206, {"Content-Type": mime, "Content-Length": str(end - start + 1), "Accept-Ranges": "bytes",
                 "Content-Range": "bytes %d-%d/%d" % (start, end, size)}, start, end


def drop_paths(pasteboard):
    """Шляхи справжніх файлів із буфера перетягування (не текст). Порожньо — там не файли."""
    out = []
    try:
        from AppKit import NSPasteboardURLReadingFileURLsOnlyKey
        from Foundation import NSURL
        urls = pasteboard.readObjectsForClasses_options_([NSURL], {NSPasteboardURLReadingFileURLsOnlyKey: True})
        for u in urls or []:
            p = str(u.path())
            if p and os.path.exists(p):
                out.append(p)
    except Exception:
        pass
    return out


# ── Cocoa-частина ─────────────────────────────────────────────────────────
try:
    import objc
    from Foundation import NSObject, NSData, NSHTTPURLResponse, NSError
    from WebKit import WKWebView

    class FileSchemeHandler(NSObject):
        """kobzar-file://<шлях> → байти файлу з підтримкою Range (без цього відео не гортається).
        Віддає лише те, що раніше дозволила панель (serve_url)."""

        def webView_startURLSchemeTask_(self, web, task):
            try:
                req = task.request()
                url = req.URL()
                path = urllib.parse.unquote(str(url.absoluteString())[len(SCHEME) + 3:].split("?", 1)[0])
                if not serve_allowed(path):
                    task.didFailWithError_(NSError.errorWithDomain_code_userInfo_("kobzar", 404, None)); return
                hdrs = req.allHTTPHeaderFields() or {}
                rh = hdrs.get("Range") or hdrs.get("range")
                status, h, a, b = plan_response(path, rh)
                resp = NSHTTPURLResponse.alloc().initWithURL_statusCode_HTTPVersion_headerFields_(url, status, "HTTP/1.1", h)
                task.didReceiveResponse_(resp)
                if b >= a and status != 416:
                    with open(path, "rb") as fh:
                        fh.seek(a)
                        task.didReceiveData_(NSData.dataWithBytes_length_(fh.read(b - a + 1), b - a + 1))
                task.didFinish()
            except Exception:
                try: task.didFailWithError_(NSError.errorWithDomain_code_userInfo_("kobzar", 500, None))
                except Exception: pass

        def webView_stopURLSchemeTask_(self, web, task):
            pass

    class KWebView(WKWebView):
        """WKWebView, що ловить файли з Finder НАТИВНО: справжній шлях, без ліміту розміру й без base64.
        Текст і все інше лишається стандартній обробці WebKit."""

        @objc.python_method
        def _kz_files(self, info):
            try: return drop_paths(info.draggingPasteboard())
            except Exception: return []

        def draggingEntered_(self, info):
            if self._kz_files(info):
                cb = getattr(self, "on_hover", None)
                if cb: cb(True)
                return 1                                         # NSDragOperationCopy
            return objc.super(KWebView, self).draggingEntered_(info)

        def draggingUpdated_(self, info):
            if self._kz_files(info):
                return 1
            return objc.super(KWebView, self).draggingUpdated_(info)

        def draggingExited_(self, info):
            cb = getattr(self, "on_hover", None)
            if cb: cb(False)
            return objc.super(KWebView, self).draggingExited_(info)

        def prepareForDragOperation_(self, info):
            if self._kz_files(info):
                return True
            return objc.super(KWebView, self).prepareForDragOperation_(info)

        def performDragOperation_(self, info):
            fs = self._kz_files(info)
            if fs:
                cb = getattr(self, "on_hover", None)
                if cb: cb(False)
                cb = getattr(self, "on_files", None)
                if cb: cb(fs)
                return True
            return objc.super(KWebView, self).performDragOperation_(info)
except Exception:                                                  # pragma: no cover — без PyObjC лишається чиста логіка
    FileSchemeHandler = KWebView = None
