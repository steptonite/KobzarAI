"""kb.py — самодостатня «База знань» (RAG) для KobzarAI.

ПРИНЦИП ПОРТАТИВНОСТІ: жодних нативних розширень (sqlite-vec/numpy) і жодної
залежності від особистих тулів (~/.claude/tools/librarian). Вектори лежать
float32-блобами у звичайному sqlite, косинус рахується на чистому Python. Тому
апка не ламається у того, хто просто її завантажив: треба лише Ollama з моделлю
bge-m3 (її KobzarAI і так вміє тягнути). Ембед-модель — та сама, що в librarian,
але індекс окремий, свій, по обраній юзером теці.

Публічний інтерфейс (усе синхронне, кидає KBError на проблемах):
    kb = KB(db_path, host="127.0.0.1:11434")
    kb.index(folder, progress=cb)   -> stats-dict; cb(done, total, phase)
    kb.search(query, k=6)           -> [{"path","text","score","idx"}]
    kb.stats()                      -> {"folder","files","chunks","updated","model"}
    kb.clear()
Помилка доступності моделі → KBEmbedUnavailable (окремо, щоб UI підказав «завантаж bge-m3»).
"""
import os, json, time, sqlite3, struct, urllib.request, urllib.error

EMBED_MODEL = "bge-m3"
DIM = 1024
EXTS = (".md", ".markdown", ".txt", ".text")
CHUNK_CHARS = 900
CHUNK_OVERLAP = 150
BATCH = 16
MAX_FILE_BYTES = 2_000_000        # не тягнемо гігантські файли (лог/дамп) у контекст


class KBError(Exception):
    pass


class KBEmbedUnavailable(KBError):
    """Ollama недоступна або модель bge-m3 не завантажена."""
    pass


def _pack(vec):
    return struct.pack("<%df" % len(vec), *vec)


def _unpack(blob):
    return struct.unpack("<%df" % (len(blob) // 4), blob)


def _looks_like_junk(text):
    """Відсів нечитабельних чанків, що трапляються у великих чужих індексах
    (librarian): мініфікований JS / base64 source-map, ASCII-роздільники,
    дампи логів. Емпіричні пороги (перевірено на 40k librarian-чанків: відсів
    1.4%, нуль хибних на кириличному тексті)."""
    t = (text or "").strip()
    if len(t) < 60:
        return True                                  # обрізки «Я:», «ver», «Новини»
    n = len(t)
    upper_lat = sum(1 for ch in t if "A" <= ch <= "Z")
    if upper_lat / n > 0.35:
        return True                                  # мініфікований код / base64 VLQ
    alpha = sum(1 for ch in t if ch.isalpha())
    if alpha / n < 0.35:
        return True                                  # роздільники |===|, таблиці, дампи
    return False


def _normalize(vec):
    s = 0.0
    for x in vec:
        s += x * x
    n = s ** 0.5
    if n == 0:
        return list(vec)
    return [x / n for x in vec]


def _embed(texts, host, timeout=180):
    """POST /api/embed → список векторів. Порожній вхід → []."""
    if not texts:
        return []
    payload = json.dumps({"model": EMBED_MODEL, "input": texts}).encode()
    req = urllib.request.Request("http://%s/api/embed" % host, payload,
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try: body = e.read().decode("utf-8", "replace")[:200]
        except Exception: pass
        if e.code == 404 or "not found" in body.lower():
            raise KBEmbedUnavailable("модель bge-m3 не завантажена")
        raise KBError("embed HTTP %s: %s" % (e.code, body))
    except Exception as e:
        raise KBEmbedUnavailable("Ollama недоступна (%s)" % (str(e)[:80]))
    embs = data.get("embeddings")
    if not embs:
        raise KBError("порожня відповідь embed")
    return embs


def _chunk(text):
    """Розбиває на шматки ~CHUNK_CHARS, поважаючи межі абзаців, з невеликим
    перекриттям — щоб не різати думку навпіл між сусідніми шматками."""
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks, buf = [], ""
    for p in paras:
        if len(buf) + len(p) + 2 <= CHUNK_CHARS:
            buf = (buf + "\n\n" + p) if buf else p
            continue
        if buf:
            chunks.append(buf)
            tail = buf[-CHUNK_OVERLAP:] if len(buf) > CHUNK_OVERLAP else ""
            buf = (tail + "\n\n" + p) if tail else p
        else:
            buf = p
        # довгий одиничний абзац — ріжемо жорстко з перекриттям
        while len(buf) > CHUNK_CHARS:
            chunks.append(buf[:CHUNK_CHARS])
            buf = buf[CHUNK_CHARS - CHUNK_OVERLAP:]
    if buf.strip():
        chunks.append(buf)
    return chunks


class KB:
    def __init__(self, db_path, host="127.0.0.1:11434"):
        self.db_path = db_path
        self.host = host
        d = os.path.dirname(db_path)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
            CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, mtime REAL);
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT, idx INTEGER, text TEXT, vec BLOB);
            CREATE INDEX IF NOT EXISTS chunks_path ON chunks(path);
        """)
        self._db.commit()

    def _meta_set(self, k, v):
        self._db.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (k, str(v)))

    def _meta_get(self, k, default=None):
        row = self._db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return row[0] if row else default

    def index(self, folder, progress=None):
        """Інкрементно індексує теку. Незмінені файли (за mtime) пропускає,
        зниклі — прибирає. progress(done, total, phase)."""
        folder = os.path.abspath(os.path.expanduser(folder))
        if not os.path.isdir(folder):
            raise KBError("тека не існує: %s" % folder)
        found = []
        for root, _dirs, names in os.walk(folder):
            base = os.path.basename(root)
            if base.startswith(".") or base in ("node_modules", "__pycache__"):
                continue
            for nm in names:
                if nm.startswith("."):
                    continue
                if os.path.splitext(nm)[1].lower() in EXTS:
                    fp = os.path.join(root, nm)
                    try:
                        if os.path.getsize(fp) <= MAX_FILE_BYTES:
                            found.append(fp)
                    except OSError:
                        pass
        found_set = set(found)
        # прибрати зниклі файли
        for (path,) in self._db.execute("SELECT path FROM files").fetchall():
            if path not in found_set:
                self._db.execute("DELETE FROM chunks WHERE path=?", (path,))
                self._db.execute("DELETE FROM files WHERE path=?", (path,))
        self._db.commit()
        total = len(found)
        changed = 0
        for i, fp in enumerate(found):
            if progress:
                progress(i, total, "index")
            try:
                mtime = os.path.getmtime(fp)
            except OSError:
                continue
            row = self._db.execute("SELECT mtime FROM files WHERE path=?", (fp,)).fetchone()
            if row and abs(row[0] - mtime) < 1e-6:
                continue                                   # незмінений — пропускаємо
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                continue
            pieces = _chunk(text)
            self._db.execute("DELETE FROM chunks WHERE path=?", (fp,))
            for b in range(0, len(pieces), BATCH):
                batch = pieces[b:b + BATCH]
                vecs = _embed(batch, self.host)
                for j, (piece, vec) in enumerate(zip(batch, vecs)):
                    self._db.execute(
                        "INSERT INTO chunks(path,idx,text,vec) VALUES(?,?,?,?)",
                        (fp, b + j, piece, _pack(_normalize(vec))))
            self._db.execute("INSERT OR REPLACE INTO files(path,mtime) VALUES(?,?)",
                             (fp, mtime))
            self._db.commit()
            changed += 1
        self._meta_set("folder", folder)
        self._meta_set("model", EMBED_MODEL)
        self._meta_set("updated", int(time.time()))
        self._db.commit()
        if progress:
            progress(total, total, "done")
        return self.stats() | {"changed": changed}

    def search(self, query, k=6):
        q = (query or "").strip()
        if not q:
            return []
        qv = _normalize(_embed([q], self.host)[0])
        rows = self._db.execute("SELECT path, idx, text, vec FROM chunks").fetchall()
        scored = []
        for path, idx, text, blob in rows:
            vec = _unpack(blob)
            dot = 0.0
            for a, b in zip(qv, vec):
                dot += a * b
            scored.append((dot, path, idx, text))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for dot, path, idx, text in scored[:k]:
            out.append({"path": path, "idx": idx, "text": text, "score": round(dot, 4)})
        return out

    def stats(self):
        files = self._db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        chunks = self._db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        return {"folder": self._meta_get("folder", ""),
                "files": files, "chunks": chunks,
                "updated": int(self._meta_get("updated", 0) or 0),
                "model": self._meta_get("model", EMBED_MODEL)}

    def clear(self):
        self._db.execute("DELETE FROM chunks")
        self._db.execute("DELETE FROM files")
        self._db.execute("DELETE FROM meta")
        self._db.commit()


class AttachedIndex:
    """Read-only доступ до ВЖЕ проіндексованої бази (напр. librarian index.db) через
    sqlite-vec MATCH. Нічого не переембедить — ембедиться лише короткий запит, далі
    миттєвий KNN по готових векторах. Схема: chunks(id,text[,source,ref]) + vec0-табличка.
    Так «мільйони токенів» НЕ гріють мак повторно — беремо готове."""
    def __init__(self, db_path, host="127.0.0.1:11434"):
        try:
            import sqlite_vec
        except Exception:
            raise KBError("для готового індексу потрібен пакет sqlite-vec")
        self.db_path = db_path
        self.host = host
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.enable_load_extension(True)
        sqlite_vec.load(self._db)
        self._db.enable_load_extension(False)
        self._vtab = self._detect_vtable()
        self._has_source = self._col_exists("chunks", "source")
        self._has_ref = self._col_exists("chunks", "ref")
        if not self._vtab:
            raise KBError("не векторний індекс (нема vec0-таблиці)")

    def _detect_vtable(self):
        for (name, sql) in self._db.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table'").fetchall():
            if sql and "using vec0" in sql.lower():
                return name
        return None

    def _col_exists(self, table, col):
        try:
            cols = [r[1] for r in self._db.execute("PRAGMA table_info(%s)" % table)]
            return col in cols
        except Exception:
            return False

    def search(self, query, k=6):
        q = (query or "").strip()
        if not q:
            return []
        qv = _normalize(_embed([q], self.host)[0])
        qblob = _pack(qv)
        sel = "c.text" + (", c.source" if self._has_source else "") + \
              (", c.ref" if self._has_ref else "")
        # перебираємо СИЛЬНО ширше за k: у великих чужих індексах (librarian)
        # трапляються (а) деградовані мікро-чанки та мініфікований код/base64 →
        # _looks_like_junk; (б) кілька майже-однакових чанків з ОДНОГО файлу →
        # дедуп по ref, щоб видача була різноманітна, а не «той самий файл ×4»
        rows = self._db.execute(
            "SELECT %s, v.distance FROM "
            "(SELECT rowid, distance FROM %s WHERE embedding MATCH ? "
            " ORDER BY distance LIMIT ?) v JOIN chunks c ON c.id = v.rowid "
            "ORDER BY v.distance"
            % (sel, self._vtab), (qblob, max(k * 12, 60))).fetchall()
        out, seen = [], set()
        for r in rows:
            if len(out) >= k:
                break
            text = r[0]
            if _looks_like_junk(text):
                continue
            i = 1
            src = r[i] if self._has_source else ""
            if self._has_source: i += 1
            ref = r[i] if self._has_ref else ""
            path = ref or src or self.db_path
            # дедуп і по файлу, і по тексту: службові преамбули повторюються
            # ДОСЛІВНО в багатьох різних файлах (щоденники) — інакше слабкий
            # запит вертає той самий абзац з 4 різних дат
            tkey = "".join((text or "").split())[:120]
            if path in seen or tkey in seen:
                continue
            seen.add(path); seen.add(tkey)
            dist = r[-1]
            out.append({"path": path, "text": text,
                        "score": round(1.0 - float(dist), 4), "idx": 0})
        return out

    def stats(self):
        n = self._db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        srcs = {}
        if self._has_source:
            for s, c in self._db.execute("SELECT source, COUNT(*) FROM chunks GROUP BY source"):
                srcs[s] = c
        return {"folder": self.db_path, "files": len(srcs) or 1, "chunks": n,
                "updated": 0, "model": EMBED_MODEL, "readonly": True, "sources": srcs}


def _index_stats(db_path):
    """Швидко зазирнути в .db: (chunks, sources-dict) або None якщо це не наш індекс."""
    try:
        db = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
        tabs = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "chunks" not in tabs:
            db.close(); return None
        has_vec = any("vec0" in (s or "").lower() for (s,) in
                      db.execute("SELECT sql FROM sqlite_master WHERE type='table'"))
        n = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        srcs = {}
        cols = [r[1] for r in db.execute("PRAGMA table_info(chunks)")]
        if "source" in cols:
            for s, c in db.execute("SELECT source, COUNT(*) FROM chunks GROUP BY source"):
                srcs[s] = c
        db.close()
        return {"chunks": n, "sources": srcs, "vec0": has_vec}
    except Exception:
        return None


def discover_indexes(extra_dirs=None):
    """Знайти готові .db-індекси у типових місцях + переданих теках. Повертає
    [{path, chunks, sources, vec0}] відсортовані за к-стю фрагментів (більші зверху)."""
    home = os.path.expanduser("~")
    cands = [
        os.path.join(home, ".claude", "tools", "librarian", "index.db"),
        os.path.join(home, "Documents", "KobzarAI", "knowledge", "index.db"),
    ]
    # 🔴 Second Brain Kit кладе індекс у <вольт>/.index/index.db, а вольт у людей
    # лежить по-різному. Без цих кандидатів панель не бачила індекс кіта взагалі:
    # список «готових» лишався порожнім, і книжечка в чаті вела в налаштування,
    # де не було чого обрати. LIBRARIAN_DB_PATH — та сама змінна, якою кіт
    # перевизначає шлях, тому вона тут головна.
    env_db = os.environ.get("LIBRARIAN_DB_PATH", "").strip()
    if env_db:
        cands.append(os.path.expanduser(env_db))
    for vault in ("SecondBrain", os.path.join("Documents", "SecondBrain"),
                  os.path.join("Documents", "Second Brain")):
        cands.append(os.path.join(home, vault, ".index", "index.db"))
        cands.append(os.path.join(home, vault, "index.db"))
    dirs = list(extra_dirs or [])
    for d in dirs:
        try:
            for nm in os.listdir(d):
                if nm.endswith(".db"):
                    cands.append(os.path.join(d, nm))
        except Exception:
            pass
    seen, out = set(), []
    for p in cands:
        rp = os.path.realpath(p)
        if rp in seen or not os.path.isfile(p):
            continue
        seen.add(rp)
        st = _index_stats(p)
        if st and st["chunks"] > 0:
            out.append({"path": p, **st})
    out.sort(key=lambda x: x["chunks"], reverse=True)
    return out


def _has_vec0(path):
    try:
        db = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        hit = any("vec0" in (s or "").lower() for (s,) in
                  db.execute("SELECT sql FROM sqlite_master WHERE type='table'"))
        db.close(); return hit
    except Exception:
        return False


def open_index(path, host="127.0.0.1:11434"):
    """Фабрика: відкрити ГОТОВИЙ індекс для пошуку (read-only). Роутинг за схемою —
    щоб працювало не лише під librarian (vec0), а й під ВЛАСНИЙ індекс KobzarAI
    (native blob-вектори, чистий stdlib) у того, хто збудував свій:
      • vec0-таблиця → AttachedIndex (sqlite-vec MATCH)
      • інакше native → KB (пошук на чистому Python, sqlite-vec НЕ потрібен)."""
    if _has_vec0(path):
        return AttachedIndex(path, host=host)
    return KB(path, host=host)          # native: KB.search читає власні blob-вектори


def build_context(hits, max_chars=2400):
    """Зібрати retrieved-шматки у блок для системного промту. Обрізає до бюджету."""
    if not hits:
        return ""
    parts, used = [], 0
    for h in hits:
        tag = os.path.basename(h.get("path", "")) or "джерело"
        block = "[%s]\n%s" % (tag, h.get("text", "").strip())
        if used + len(block) > max_chars and parts:
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts)
