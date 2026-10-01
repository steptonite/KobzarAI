"""Спільне для регресійних харнесів чату Кобзаря. Без персональних шляхів: панель береться з теки
репозиторію (або з KOBZAR_PANEL_DIR), тестові файли генеруються у тимчасовій теці."""
import os, sys, json, time, wave, struct, zipfile, subprocess, tempfile, shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PANEL = Path(os.environ.get("KOBZAR_PANEL_DIR") or (REPO / "panel"))
sys.path.insert(0, str(PANEL))
FAILS = [0]
_H = None


def chk(name, cond, extra=""):
    print(("OK   " if cond else "FAIL "), name, (str(extra)[:160] if extra != "" else ""))
    FAILS[0] += (not cond)
    return bool(cond)


def finish():
    print("FAILS:", FAILS[0])
    sys.exit(1 if FAILS[0] else 0)


def make_fixtures(root=None):
    """Набір файлів усіх типів. Повертає {імʼя: шлях}."""
    root = Path(root or tempfile.mkdtemp(prefix="kobzar-fx-"))
    root.mkdir(parents=True, exist_ok=True)
    f = {}

    def w(name, text, enc="utf-8"):
        p = root / name; p.write_bytes(text.encode(enc)); f[name] = str(p); return p
    w("нотатки.md", "# Заголовок\n\nЦе **жирний** текст і `код`.\n\n- один\n- два\n" + "\n".join("рядок %d" % i for i in range(1, 80)))
    w("plain.txt", "\n".join("рядок %d" % i for i in range(1, 120)))
    w("data.csv", "a,b,c\n1,2,3\n4,5,6\n")
    w("cfg.json", json.dumps({"ключ": "значення", "n": [1, 2, 3]}, ensure_ascii=False, indent=2))
    w("script.py", "print('привіт')\n")
    w("win.txt", "Кирилиця в cp1251", "cp1251")
    src = root / "_src.txt"; src.write_text("Вміст документа для моделі: код-42.", encoding="utf-8")
    for ext in ("docx", "rtf"):
        out = root / ("doc." + ext)
        subprocess.run(["/usr/bin/textutil", "-convert", ext, str(src), "-output", str(out)], check=True)
        f["doc." + ext] = str(out)
    pdf = root / "text.pdf"
    r = subprocess.run(["/usr/sbin/cupsfilter", "-m", "application/pdf", str(src)], capture_output=True)
    if r.returncode == 0 and r.stdout[:4] == b"%PDF":
        pdf.write_bytes(r.stdout); f["text.pdf"] = str(pdf)
    try:
        from PIL import Image
        im = Image.new("RGB", (320, 200), (200, 60, 60)); p = root / "pic.png"; im.save(p); f["pic.png"] = str(p)
        big = Image.frombytes("RGB", (900, 700), os.urandom(900 * 700 * 3)); p = root / "big.png"; big.save(p); f["big.png"] = str(p)
        scan = root / "scan.pdf"; Image.new("RGB", (200, 200), (255, 255, 255)).save(scan, "PDF"); f["scan.pdf"] = str(scan)
    except ImportError:
        pass
    p = root / "pres.pptx"; p.write_bytes(b"PK\x03\x04fake-pptx"); f["pres.pptx"] = str(p)
    p = root / "arch.zip"
    with zipfile.ZipFile(p, "w") as z: z.writestr("a.txt", "hello")
    f["arch.zip"] = str(p)
    p = root / "tone.wav"
    with wave.open(str(p), "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(8000)
        wf.writeframes(b"".join(struct.pack("<h", int(8000 * ((i // 20) % 2 - .5))) for i in range(16000)))
    f["tone.wav"] = str(p)
    if shutil.which("ffmpeg"):
        p = root / "clip.mp4"
        r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=2",
                            "-pix_fmt", "yuv420p", str(p)], capture_output=True)
        if r.returncode == 0: f["clip.mp4"] = str(p)
    f["_root"] = str(root)
    return f


# ── headless WKWebView з нашою схемою й записом повідомлень сторінки ──
def make_web(dark=False, size=(900, 700), handler=True, klass=None):
    from AppKit import NSApplication, NSRunLoop
    from Foundation import NSObject, NSDate
    from WebKit import WKWebView, WKWebViewConfiguration, WKUserScript
    import chatui, chatfiles
    NSApplication.sharedApplication()
    cfg = WKWebViewConfiguration.alloc().init()
    uc = cfg.userContentController()
    uc.addUserScript_(WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
        "window.__errs=[];window.addEventListener('error',function(e){__errs.push(String(e.message))});", 0, True))
    msgs = []

    global _H
    if _H is None:
        class H(NSObject):
            def userContentController_didReceiveScriptMessage_(self, ucc, msg):
                self.sink.append((str(msg.name()), str(msg.body())))
        _H = H
    h = _H.alloc().init(); h.sink = msgs
    for nm in ("copy", "speak", "regen", "open", "chat"):
        uc.addScriptMessageHandler_name_(h, nm)
    fh = None
    if handler and chatfiles.FileSchemeHandler is not None:
        fh = chatfiles.FileSchemeHandler.alloc().init()
        cfg.setURLSchemeHandler_forURLScheme_(fh, chatfiles.SCHEME)
    web = (klass or WKWebView).alloc().initWithFrame_configuration_(((0, 0), size), cfg)
    # без вікна WebKit не вантажить медіа (networkState=NO_SOURCE) — ставимо за межі екрана
    from AppKit import NSWindow
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(((-12000, -12000), size), 0, 2, False)
    win.setContentView_(web); win.orderBack_(None)
    web.loadHTMLString_baseURL_(chatui.page(dark, "#2563eb"), None)
    R, n = {}, [0]

    def spin(s):
        e = time.time() + s
        while time.time() < e:
            NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))

    def ev(js, t=20):
        n[0] += 1; k = n[0]
        web.evaluateJavaScript_completionHandler_(js, lambda r, e: R.__setitem__(k, (r, e)))
        t0 = time.time()
        while k not in R and time.time() - t0 < t: spin(0.05)
        return R.get(k, (None, "timeout"))
    # чекаємо, поки сторінка справді готова (холодний старт повільний)
    t0 = time.time()
    while time.time() - t0 < 25:
        spin(0.3)
        if ev("typeof addAI=='function'&&document.readyState=='complete'", 5)[0]: break
    spin(0.5)
    return web, ev, spin, msgs, (h, fh, win)
