"""Логіка файлів чату без UI: типи, розміри, перегляд тексту, що отримує локальна модель, зір моделі,
віддача відео з Range, збереження оригіналу, нативний drop-буфер."""
from _common import *
import chatfiles as cf
import urllib.parse

fx = make_fixtures()
F = lambda n: fx[n]

# типи й розміри
for n, k in (("нотатки.md", "md"), ("plain.txt", "txt"), ("data.csv", "csv"), ("cfg.json", "json"), ("script.py", "code"),
             ("doc.docx", "doc"), ("doc.rtf", "doc"), ("pres.pptx", "slides"), ("arch.zip", "zip"), ("tone.wav", "aud"),
             ("pic.png", "img")):
    chk("тип %s → %s" % (n, k), cf.kind_of(F(n)) == k, cf.kind_of(F(n)))
chk("тип key/pdf/mp4/xlsx", (cf.kind_of("x.KEY"), cf.kind_of("x.pdf"), cf.kind_of("x.mp4"), cf.kind_of("x.xlsx")) == ("slides", "pdf", "vid", "sheet"))
chk("розмір людською", (cf.human_size(500), cf.human_size(2500000), cf.human_size(12 * 1024)) == ("500 Б", "2,4 МБ", "12 КБ"), cf.human_size(2500000))
ci = cf.card_info(F("нотатки.md"))
chk("картка md: імʼя/розмір/перегляд", ci["name"] == "нотатки.md" and ci["prev"] and ci["size"] and not ci["gone"], ci)
chk("картка зниклого файлу", cf.card_info("/нема/такого.pdf")["gone"] is True)
chk("картка відео/звуку несе адресу програвача", cf.card_info(F("tone.wav"))["src"].startswith("kobzar-file://"))
chk("токен файлу: тип і розмір", cf.token_tail(F("pres.pptx")).startswith("file:slides,"), cf.token_tail(F("pres.pptx")))

# перегляд тексту
pv = cf.preview(F("plain.txt"))
chk("перегляд: 40 рядків у голові, є «ще»", pv["head"].count("\n") == 39 and pv["more"] and pv["total"] == 119, (pv["total"], pv["head"].count("\n")))
chk("перегляд: повний текст", pv["full"].count("\n") >= 118 and not pv["cut"])
chk("перегляд cp1251", "Кирилиця" in cf.preview(F("win.txt"))["head"])
big = Path(fx["_root"]) / "huge.txt"; big.write_text("x" * 100 + "\n" * 1 + ("y" * 99 + "\n") * 5000, encoding="utf-8")
pvb = cf.preview(str(big))
chk("перегляд великого: обрізано на 200 КБ", pvb["cut"] and len(pvb["full"].encode()) <= 200 * 1024 + 4, (pvb["cut"], len(pvb["full"])))

# текст для моделі
t, cut = cf.extract_text(F("doc.docx"), 5000); chk("docx → текст (textutil)", t and "код-42" in t and not cut, t)
t, cut = cf.extract_text(F("doc.rtf"), 5000); chk("rtf → текст", t and "код-42" in t, t)
if "text.pdf" in fx:
    t, cut = cf.extract_text(F("text.pdf"), 5000); chk("pdf з текстом → текст (PDFKit)", t and "код-42" in t, t)
else:
    print("SKIP pdf з текстом (нема cupsfilter)")
if "scan.pdf" in fx:
    chk("pdf-скан → None", cf.extract_text(F("scan.pdf"), 5000)[0] is None)
chk("pptx → None", cf.extract_text(F("pres.pptx"), 5000)[0] is None)
chk("zip → None", cf.extract_text(F("arch.zip"), 5000)[0] is None)
t, cut = cf.extract_text(F("plain.txt"), 100); chk("txt довший за бюджет → обрізано", cut and len(t) == 100, (cut, len(t)))

# що віддаємо локальній моделі
A = lambda n: {"name": n, "path": F(n), "kind": cf.kind_of(F(n))}
BLIND = "Ця модель не бачить картинок — отримала лише текст."
c = cf.local_context([A("pic.png")], 4000, vision=False)
chk("без зору: рядок про картинки дослівно", BLIND in c["notes"] and not c["images"], c["notes"])
c = cf.local_context([A("pic.png")], 4000, vision=True, image_b64=lambda p: "QUJD")
chk("із зором: картинка йде моделі, попередження нема", c["images"] == ["QUJD"] and not c["notes"], c)
c = cf.local_context([A("pic.png")], 4000, vision=True, image_b64=lambda p: None)
chk("із зором, але не вдалось перекодувати → чесний рядок", BLIND in c["notes"])
if "clip.mp4" in fx:
    c = cf.local_context([A("clip.mp4")], 4000, vision=True)
    chk("відео: модель не бачить — рядок", any("відео" in n for n in c["notes"]), c["notes"])
c = cf.local_context([A("tone.wav")], 4000)
chk("звук: рядок", any("звук" in n for n in c["notes"]), c["notes"])
c = cf.local_context([A("нотатки.md"), A("data.csv"), A("cfg.json")], 20000)
chk("md/csv/json: вміст іде в контекст, без попереджень", "Заголовок" in c["text"] and "4,5,6" in c["text"] and "ключ" in c["text"] and not c["notes"], c["notes"])
c = cf.local_context([A("plain.txt")], 300)
chk("обрізка з позначкою «файл обрізано»", any("обрізано" in n for n in c["notes"]) and "(обрізано)" in c["text"], c["notes"])
c = cf.local_context([A("pres.pptx"), A("arch.zip")], 4000)
chk("преза/zip: «не може прочитати — лише назва»", sum("не може прочитати" in n and "лише назву" in n for n in c["notes"]) == 2, c["notes"])
if "scan.pdf" in fx:
    c = cf.local_context([A("scan.pdf")], 4000); chk("скан: не може прочитати", any("не може прочитати" in n for n in c["notes"]))
c = cf.local_context([A("doc.docx")], 4000); chk("docx: без попереджень, текст у контексті", "код-42" in c["text"] and not c["notes"])
c = cf.local_context([A("plain.txt"), A("нотатки.md")], 200)
chk("бюджет ділиться: другому файлу не лишилось", any("не влазить" in n for n in c["notes"]), c["notes"])

# чи бачить модель картинки
calls = []
def fetch(m, h): calls.append(m); return {"g:vis": ["completion", "vision"], "g:txt": ["completion"]}[m]
cf._VISION_CACHE.clear()
chk("capabilities з vision → True", cf.model_has_vision("g:vis", fetch=fetch) is True)
chk("capabilities без vision → False", cf.model_has_vision("g:txt", fetch=fetch) is False)
cf.model_has_vision("g:vis", fetch=fetch); cf.model_has_vision("g:txt", fetch=fetch)
chk("кеш на модель: запитів 2, не 4", len(calls) == 2, calls)
def boom(m, h): raise OSError("ollama down")
cf._VISION_CACHE.clear()
chk("Ollama мовчить: llava → True за назвою, не кешується", cf.model_has_vision("llava:7b", fetch=boom) is True and "llava:7b" not in cf._VISION_CACHE)
chk("Ollama мовчить: gemma3:1b → False", cf.model_has_vision("gemma3:1b", fetch=boom) is False)
chk("Ollama мовчить: qwen2.5vl → True, qwen3:4b → False", cf.model_has_vision("qwen2.5vl:7b", fetch=boom) and not cf.model_has_vision("qwen3:4b", fetch=boom))
chk("порожня модель → False", cf.model_has_vision("", fetch=boom) is False)

# відео/звук: Range
chk("Range bytes=0- → 0..кінець", cf.parse_range("bytes=0-", 1000) == (0, 999))
chk("Range 10-19", cf.parse_range("bytes=10-19", 1000) == (10, 19))
chk("Range -500 → останні 500", cf.parse_range("bytes=-500", 1000) == (500, 999))
chk("Range поза файлом → bad", cf.parse_range("bytes=2000-", 1000) == "bad")
chk("Range мотлох → None", cf.parse_range("мотлох", 1000) is None and cf.parse_range(None, 1000) is None)
st, h, a, b = cf.plan_response(F("tone.wav"), "bytes=100-199")
chk("206 + Content-Range", st == 206 and h["Content-Range"].startswith("bytes 100-199/") and h["Content-Type"] == "audio/wav", (st, h))
st, h, a, b = cf.plan_response(F("tone.wav"), None)
chk("без Range: 200 цілком", st == 200 and b == os.path.getsize(F("tone.wav")) - 1)
chk("великий Range-запит ріжеться шматками ≤4 МБ", cf.parse_range("bytes=0-", 50 * 1024 * 1024) == (0, 4 * 1024 * 1024 - 1))
u = cf.serve_url(F("tone.wav"))
chk("адреса програвача без пробілів/дужок, кирилиця закодована", u.startswith("kobzar-file:///") and not any(ch in u for ch in " ()\"'"), u)
chk("віддача лише дозволеного", cf.serve_allowed(F("tone.wav")) and not cf.serve_allowed("/etc/hosts"))

# відкриття / збереження
chk("open: звичайний файл", cf.open_cmd(F("pic.png")) == ["open", F("pic.png")])
chk("open: json → редактор", cf.open_cmd(F("cfg.json"))[:2] == ["open", "-t"])
chk("open: .command/.app/.sh не запускаємо → у Finder", all(cf.open_cmd("/x/a" + e)[:2] == ["open", "-R"] for e in (".command", ".app", ".sh", ".pkg")))
d = Path(tempfile.mkdtemp(prefix="kobzar-dl-"))
o1 = cf.save_copy(F("big.png"), dst_dir=str(d)); o2 = cf.save_copy(F("big.png"), dst_dir=str(d))
chk("зберегти оригінал: побайтово, друга копія не затирає", open(o1, "rb").read() == open(F("big.png"), "rb").read() and o1 != o2 and Path(o2).exists(), (o1, o2))
o3 = cf.save_copy(F("big.png"), str(d / "нова" / "обрана.png"))
chk("зберегти в обране місце (NSSavePanel-шлях)", open(o3, "rb").read() == open(F("big.png"), "rb").read(), o3)

# перетягування: читання файлових URL із буфера перетягування (окремий буфер, НЕ системний)
from AppKit import NSPasteboard
from Foundation import NSURL
pb = NSPasteboard.pasteboardWithUniqueName()
pb.clearContents(); pb.writeObjects_([NSURL.fileURLWithPath_(F("pic.png")), NSURL.fileURLWithPath_(F("нотатки.md"))])
chk("drop: із буфера дістаємо справжні шляхи двох файлів", sorted(cf.drop_paths(pb)) == sorted([F("pic.png"), F("нотатки.md")]), cf.drop_paths(pb))
pb2 = NSPasteboard.pasteboardWithUniqueName(); pb2.clearContents(); pb2.setString_forType_("просто текст", "public.utf8-plain-text")
chk("drop: текст — не файл → порожньо", cf.drop_paths(pb2) == [])
shutil.rmtree(fx["_root"], ignore_errors=True)
finish()
