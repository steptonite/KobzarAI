#!/usr/bin/env python3
# LocalAI Panel — menu-bar керування Ollama + TTS + RAM + глобальні хоткеї. Без автозапуску, ручний СТОП.
import os, subprocess, tempfile, threading, time, urllib.request, json, shlex, re
import rumps
import objc
from AppKit import (NSImage, NSSound, NSWindow, NSPanel, NSBackingStoreBuffered,
    NSWindowStyleMaskTitled, NSWindowStyleMaskClosable, NSWindowStyleMaskResizable,
    NSWindowStyleMaskFullSizeContentView, NSWindowStyleMaskUtilityWindow,
    NSMenu, NSMenuItem,
    NSTextField, NSPopUpButton, NSButton, NSView, NSApp, NSColor, NSSlider,
    NSImageSymbolConfiguration, NSApplication, NSWorkspace, NSPasteboard, NSScreen, NSClipView,
    NSTabView, NSTabViewItem, NSSegmentedControl, NSScrollView, NSTextView, NSFont, NSAttributedString,
    NSMutableAttributedString, NSTextTab, NSRightTextAlignment, NSBox,
    NSVisualEffectView, NSVisualEffectBlendingModeBehindWindow, NSVisualEffectStateActive,
    NSVisualEffectMaterialHUDWindow, NSVisualEffectMaterialPopover,
    NSVisualEffectMaterialWindowBackground, NSFloatingWindowLevel,
    NSOpenPanel, NSAppearance, NSMutableParagraphStyle, NSColorSpace,
    NSFontAttributeName, NSForegroundColorAttributeName, NSParagraphStyleAttributeName,
    NSBackgroundColorAttributeName, NSTrackingArea,
    NSTableView, NSTableColumn, NSProgressIndicator, NSSliderCell, NSBezierPath)
from Foundation import (NSObject, NSAutoreleasePool, NSMakeRect, NSMakeRange,
    NSMakeSize, NSProcessInfo)
from WebKit import WKWebView, WKWebViewConfiguration
from PyObjCTools import AppHelper

APA = os.environ.get("LOCALAI_DISK", "/Volumes/ExternalSSD")
OLLAMA = "/opt/homebrew/bin/ollama"
DEFAULT_MODELS_DIR = f"{APA}/ollama-models"


def models_dir():
    """Папка моделей: спершу config.json (UI), інакше дефолт."""
    try:
        return load_cfg().get("models_dir") or DEFAULT_MODELS_DIR
    except Exception:
        return DEFAULT_MODELS_DIR
START_OLLAMA = os.path.expanduser("~/.ollama/start-ollama.sh")
TTS_DIR = os.path.expanduser("~/.local/styletts2-ua-server")
TTS_PORT = 5050
OLLAMA_HOST = "127.0.0.1:11434"
VOICES = ["Артем Окороков", "Анастасія Павленко", "Денис Денисенко", "filatov"]
CONFIG = os.path.expanduser("~/.local/localai-panel/config.json")

# дефолтні хоткеї: лише ⌃⌥ (виділене) і ⌃⌥⇧ (пауза); буфер/стоп — порожні
DEFAULT_HOTKEYS = {
    "speak_sel": {"mods": ["ctrl", "alt"], "keycode": None},
    "tts_pause": {"mods": ["ctrl", "alt", "shift"], "keycode": None},
    "speak_clip": None,
    "tts_stop": None,
}
HK_LABELS = [("speak_sel", "Озвучити виділене"), ("speak_clip", "Озвучити буфер"),
             ("tts_pause", "Пауза / продовжити"), ("tts_stop", "Стоп")]
_MOD_SYM = {"ctrl": "⌃", "alt": "⌥", "shift": "⇧", "cmd": "⌘"}
_MOD_ORDER = ["ctrl", "alt", "shift", "cmd"]
_KC2CHAR = {0:"A",1:"S",2:"D",3:"F",4:"H",5:"G",6:"Z",7:"X",8:"C",9:"V",11:"B",12:"Q",
    13:"W",14:"E",15:"R",16:"Y",17:"T",18:"1",19:"2",20:"3",21:"4",22:"6",23:"5",24:"=",
    25:"9",26:"7",27:"-",28:"8",29:"0",30:"]",31:"O",32:"U",33:"[",34:"I",35:"P",37:"L",
    38:"J",39:"'",40:"K",41:";",42:"\\",43:",",44:"/",45:"N",46:"M",47:".",49:"Space",
    50:"`",36:"Return",48:"Tab",122:"F1",120:"F2",99:"F3",118:"F4",96:"F5",97:"F6"}


def fmt_hotkey(v):
    if not v:
        return "—"
    s = "".join(_MOD_SYM[m] for m in _MOD_ORDER if m in v.get("mods", []))
    kc = v.get("keycode")
    if kc is not None:
        s += _KC2CHAR.get(kc, f"·{kc}")
    return s or "—"


def set_menu_title(item, label, chord=""):
    """Заголовок пункту меню: label зліва, chord — сірим, фіксовано біля правого краю."""
    mi = item._menuitem
    if not chord:
        mi.setAttributedTitle_(None)
        item.title = label
        return
    full = label + "\t" + chord
    ps = NSMutableParagraphStyle.alloc().init()
    tab = NSTextTab.alloc().initWithTextAlignment_location_options_(NSRightTextAlignment, 250.0, {})
    ps.setTabStops_([tab])
    try: fnt = NSFont.menuFontOfSize_(0.0)
    except Exception: fnt = NSFont.systemFontOfSize_(14.0)
    s = NSMutableAttributedString.alloc().initWithString_(full)
    n = len(full)
    s.addAttribute_value_range_(NSParagraphStyleAttributeName, ps, (0, n))
    s.addAttribute_value_range_(NSFontAttributeName, fnt, (0, n))
    ci = len(label) + 1
    s.addAttribute_value_range_(NSForegroundColorAttributeName,
                                NSColor.secondaryLabelColor(), (ci, len(chord)))
    mi.setAttributedTitle_(s)


def load_cfg():
    try:
        with open(CONFIG) as f:
            return json.load(f)
    except Exception:
        return {}


def save_cfg(d):
    try:
        with open(CONFIG, "w") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def tts_mode():
    """Режим озвучення: 'base' | 'stream' | 'realtime'.
    Міграція зі старого булевого tts_stream (True→stream, інакше base)."""
    c = load_cfg()
    m = c.get("tts_mode")
    if m in ("base", "stream", "realtime"):
        return m
    return "stream" if c.get("tts_stream") else "base"


def ax_selection():
    """Виділений текст ПЕРЕДНЬОЇ апки через Accessibility API — БЕЗ буфера."""
    try:
        from ApplicationServices import (
            AXUIElementCreateApplication, AXUIElementCopyAttributeValue,
            kAXFocusedUIElementAttribute, kAXSelectedTextAttribute)
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return None
        el = AXUIElementCreateApplication(app.processIdentifier())
        err, focused = AXUIElementCopyAttributeValue(el, kAXFocusedUIElementAttribute, None)
        if err or focused is None:
            return None
        err, val = AXUIElementCopyAttributeValue(focused, kAXSelectedTextAttribute, None)
        if err or not val:
            return None
        return str(val).strip() or None
    except Exception:
        return None


def _send_cmd_c():
    from Quartz import (CGEventCreateKeyboardEvent, CGEventPost, CGEventSetFlags,
                        kCGHIDEventTap, kCGEventFlagMaskCommand)
    for down in (True, False):
        ev = CGEventCreateKeyboardEvent(None, 8, down)  # 8 = 'c'
        CGEventSetFlags(ev, kCGEventFlagMaskCommand)
        CGEventPost(kCGHIDEventTap, ev)


def selection_via_clipboard():
    """Фолбек: Cmd+C (CGEvent) з контролем changeCount і відновленням буфера."""
    UTF8 = "public.utf8-plain-text"
    pb = NSPasteboard.generalPasteboard()
    old = pb.stringForType_(UTF8)
    cc = pb.changeCount()
    try:
        _send_cmd_c()
    except Exception:
        return None
    changed = False
    for _ in range(25):
        time.sleep(0.03)
        if pb.changeCount() != cc:
            changed = True
            break
    new = pb.stringForType_(UTF8) if changed else None
    pb.clearContents()
    if old is not None:
        pb.setString_forType_(old, UTF8)
    return (str(new).strip() or None) if new else None


def sh(cmd, env=None):
    e = dict(os.environ); e["OLLAMA_MODELS"] = models_dir()
    if env: e.update(env)
    try: return subprocess.run(cmd, shell=True, capture_output=True, text=True, env=e, timeout=20).stdout.strip()
    except Exception as ex: return f"ERR {ex}"


def ollama_up():
    try: urllib.request.urlopen(f"http://{OLLAMA_HOST}/api/version", timeout=2); return True
    except Exception: return False


def tts_up():
    try: urllib.request.urlopen(f"http://127.0.0.1:{TTS_PORT}/health", timeout=2); return True
    except Exception: return False


def split_sentences(text, maxlen=240):
    parts = re.split(r'(?<=[.!?…:;])\s+|\n+', text or "")
    out = []
    for p in parts:
        p = p.strip()
        if not p: continue
        while len(p) > maxlen:
            cut = p.rfind(' ', 0, maxlen)
            cut = cut if cut > 40 else maxlen
            out.append(p[:cut].strip()); p = p[cut:].strip()
        out.append(p)
    return out


def split_blocks(text, maxlen=700):
    """Великі блоки для TTS: НЕ ріжемо по кожному реченню (це давало рвані
    паузи й глюки на коротких фрагментах). Ділимо лише по абзацах; завеликий
    абзац добиваємо по реченнях до maxlen. Сервер сам згладжує склейку всередині."""
    out = []
    for para in re.split(r'\n\s*\n', (text or "").strip()):
        para = " ".join(para.split())
        if not para: continue
        if len(para) <= maxlen:
            out.append(para); continue
        buf = ""
        for s in split_sentences(para, maxlen):
            if buf and len(buf) + 1 + len(s) > maxlen:
                out.append(buf); buf = s
            else:
                buf = (buf + " " + s).strip()
        if buf: out.append(buf)
    return out


def split_stream(text, first=90, maxlen=320):
    """Стрім-розбивка: дрібні шматки для конвеєра «грай N / синтезуй N+1».
    Перший шматок короткий (швидкий time-to-first-audio), далі склеюємо
    речення до maxlen, щоб не плодити рвані мікро-фрагменти."""
    sents = split_sentences(" ".join((text or "").split()), maxlen)
    out, buf = [], ""
    for s in sents:
        cap = first if not out else maxlen           # перший шматок тримаємо коротким
        if buf and len(buf) + 1 + len(s) > cap:
            out.append(buf); buf = s
        else:
            buf = (buf + " " + s).strip()
        # перший шматок віддаємо одразу, щойно набрав мінімум
        if not out and len(buf) >= first:
            out.append(buf); buf = ""
    if buf: out.append(buf)
    return out


_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"   # символи/піктограми/емодзі (вкл. 🙂🚀 тощо)
    "\U00002600-\U000027BF"   # misc symbols + dingbats (☀✂✅)
    "\U0001F000-\U0001F0FF"   # маджонг/доміно/карти
    "\U00002B00-\U00002BFF"   # стрілки-зірки (⭐⬛)
    "\U0001F1E6-\U0001F1FF"   # прапори (regional indicators)
    "\U0000FE00-\U0000FE0F"   # variation selectors
    "\U0001F3FB-\U0001F3FF"   # модифікатори тону шкіри
    "\U00002190-\U000021FF"   # стрілки
    "\U00002300-\U000023FF"   # тех. символи (⌚⏰)
    "\U000020D0-\U000020FF"   # огортаючі знаки (keycap ⃣)
    "\U0000200D"              # zero-width joiner
    "\U0000FE0F"
    "]+", flags=re.UNICODE)


def strip_emoji(text):
    """Прибрати емоджі/піктограми — StyleTTS2 їх не озвучує (g2p спотикається).
    Чистимо ДО синтезу. Залишки подвійних пробілів стискаємо."""
    t = _EMOJI_RE.sub(" ", text or "")
    return re.sub(r"[ \t]{2,}", " ", t).strip()


def pop_sentences(text, start):
    """Дістати завершені речення з потоку від позиції start. Межа = .!?…: перед
    пробілом, або порожній рядок. Хвіст без межі лишається (дочитаємо на кінці).
    Повертає (список_речень, нова_позиція)."""
    seg = text[start:]
    out, last = [], 0
    for m in re.finditer(r'[.!?…:](?=\s)|\n{2,}', seg):
        end = m.end()
        s = seg[last:end].strip()
        if s:
            out.append(s)
        last = end
    return out, start + last


def mem():
    free = sh("memory_pressure 2>/dev/null | sed -n 's/.*free percentage: \\([0-9]*\\)%.*/\\1/p'")
    swap = sh("sysctl -n vm.swapusage 2>/dev/null | sed -n 's/.*used = \\([0-9.]*\\)M.*/\\1/p'")
    return free or "?", swap or "?"


def ps_loaded():
    out = sh(f"{OLLAMA} ps 2>/dev/null")
    return [l for l in out.splitlines()[1:] if l.strip()]


def ram_size(line):
    """Розмір моделі в RAM з рядка `ollama ps` (напр. '3.3 GB')."""
    m = re.search(r"(\d+(?:[.,]\d+)?\s?[GM]B)", line or "")
    return m.group(1) if m else ""


def list_models():
    out = sh(f"{OLLAMA} list 2>/dev/null")
    return [l.split()[0] for l in out.splitlines()[1:] if l.strip()]


# Куратований fallback під 8ГБ RAM — коли офіційний ендпоінт недоступний.
OLLAMA_FALLBACK = [
    "gemma3:1b", "gemma3:4b", "qwen3:1.7b", "qwen3:4b",
    "qwen2.5:3b", "qwen2.5-coder:3b", "llama3.2:1b", "llama3.2:3b",
    "phi4-mini", "smollm2:1.7b", "deepseek-r1:1.5b", "nomic-embed-text",
]


def fetch_ollama_library():
    """Список моделей з бібліотеки Ollama для огляду перед завантаженням.
    Бере той самий офіційний ендпоінт, що й `ollama search` (ollama.com/v1/models).
    Падіння/офлайн → куратований пресет під 8ГБ."""
    try:
        req = urllib.request.Request(
            "https://ollama.com/v1/models",
            headers={"User-Agent": "LocalAI-panel"})
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode("utf-8"))
        ids = sorted({d.get("id") for d in data.get("data", []) if d.get("id")})
        return (ids or list(OLLAMA_FALLBACK)), bool(ids)
    except Exception:
        return list(OLLAMA_FALLBACK), False


def human_size(nbytes):
    if not nbytes:
        return "?"
    g = nbytes / 1e9
    return f"{g:.2f} GB" if g >= 1 else f"{nbytes / 1e6:.0f} MB"


def short_num(n):
    n = n or 0
    if n >= 1e6:
        return f"{n / 1e6:.1f}M"
    if n >= 1e3:
        return f"{n / 1e3:.1f}K"
    return str(int(n))


def fetch_model_size(model_id):
    """Сумарний розмір моделі (вага шарів) з офіційного реєстру Ollama.
    `name[:tag]`; без тегу → latest. Анонімний manifest (без токена). None при збої."""
    try:
        name, _, tag = model_id.partition(":")
        tag = tag or "latest"
        url = f"https://registry.ollama.ai/v2/library/{name}/manifests/{tag}"
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.docker.distribution.manifest.v2+json",
            "User-Agent": "LocalAI-panel"})
        with urllib.request.urlopen(req, timeout=12) as r:
            m = json.loads(r.read().decode("utf-8"))
        tot = sum(l.get("size", 0) for l in m.get("layers", []))
        tot += (m.get("config") or {}).get("size", 0)
        return tot or None
    except Exception:
        return None


# бажані кванти під 8ГБ (порядок переваги для pull-тегу й оцінки розміру)
QUANT_PREF = ("Q4_K_M", "Q4_K_S", "Q4_0", "Q5_K_M", "Q3_K_M", "Q6_K", "Q8_0", "Q2_K")


def fetch_hf_gguf(query="", limit=60):
    """GGUF-репозиторії з HuggingFace, відсортовані за завантаженнями.
    Повертає (rows, online). rows: [{id, dl, kind:'hf'}]. Збій/офлайн → ([], False)."""
    import urllib.parse
    try:
        params = {"filter": "gguf", "limit": str(limit),
                  "sort": "downloads", "direction": "-1"}
        q = (query or "").strip()
        if q:
            params["search"] = q
        url = "https://huggingface.co/api/models?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "LocalAI-panel"})
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode("utf-8"))
        rows = [{"id": m.get("id"), "dl": m.get("downloads"), "kind": "hf"}
                for m in data if m.get("id")]
        return rows, True
    except Exception:
        return [], False


def fetch_hf_repo_size(repo):
    """(розмір_байт, квант) для GGUF-репо HF. Обирає Q4_K_M (інакше найменший).
    Сумує split-частини того кванта. None при збої."""
    try:
        url = f"https://huggingface.co/api/models/{repo}/tree/main"
        req = urllib.request.Request(url, headers={"User-Agent": "LocalAI-panel"})
        with urllib.request.urlopen(req, timeout=12) as r:
            files = json.loads(r.read().decode("utf-8"))
        ggufs = {}
        for f in files:
            p = f.get("path", "")
            if p.lower().endswith(".gguf"):
                ggufs[p] = (f.get("lfs") or {}).get("size") or f.get("size") or 0
        if not ggufs:
            return None, None
        for q in QUANT_PREF:
            parts = [sz for nm, sz in ggufs.items() if q.lower() in nm.lower() and sz]
            if parts:
                return sum(parts), q
        nm = min(ggufs, key=lambda k: ggufs[k] or 1e18)
        return ggufs[nm], None
    except Exception:
        return None, None


# бажаний дефолт для міні-чату (qwen3-vl/embed — пропускати: німі/не-чат)
CHAT_PREF = ("qwen3:4b-instruct-2507-q4_K_M", "gemma3:4b",
             "hf.co/INSAIT-Institute/MamayLM-Gemma-3-4B-IT-v1.0-GGUF:Q4_K_M", "gemma3:1b")


def pick_chat_model(models):
    for p in CHAT_PREF:
        if p in models:
            return p
    for m in models:
        low = m.lower()
        if "embed" in low or "vl" in low:
            continue
        return m
    return models[0] if models else None


# --- глобальні хоткеї через CGEventTap (модифікаторні «тапи» + комбо mod+клавіша) ---
class Hotkeys(threading.Thread):
    def __init__(self, panel):
        super().__init__(daemon=True)
        self.panel = panel
        self.binds = {}                  # action -> (frozenset(mods), keycode|None)
        self.recording = None            # action під час запису комбо у Settings
        self._episode = set()            # модифікатори, накопичені за натискання
        self._active = False
        self._dirty = False              # чи натиснулась клавіша під час епізоду
        self.reload()

    def reload(self):
        hk = load_cfg().get("hotkeys", DEFAULT_HOTKEYS)
        b = {}
        for act, v in hk.items():
            if v:
                b[act] = (frozenset(v.get("mods", [])), v.get("keycode"))
        self.binds = b

    def _fire(self, action):
        p = self.panel
        fn = {"speak_sel": lambda: p.speak_selection(None),
              "speak_clip": lambda: p.speak_clipboard(None),
              "tts_pause": lambda: p.pause_speech(None),
              "tts_stop": lambda: p.stop_speech(None)}.get(action)
        if fn:
            AppHelper.callAfter(fn)       # на головний потік

    def _record(self, mods, keycode):
        act = self.recording; self.recording = None
        cfg = load_cfg(); hk = cfg.get("hotkeys", dict(DEFAULT_HOTKEYS))
        hk[act] = {"mods": [m for m in _MOD_ORDER if m in mods], "keycode": keycode}
        cfg["hotkeys"] = hk; save_cfg(cfg); self.reload()

    def run(self):
        from Quartz import (CGEventTapCreate, kCGSessionEventTap, kCGHeadInsertEventTap,
            kCGEventTapOptionListenOnly, CGEventMaskBit, kCGEventFlagsChanged, kCGEventKeyDown,
            CFMachPortCreateRunLoopSource, CFRunLoopAddSource, CFRunLoopGetCurrent,
            kCFRunLoopCommonModes, CGEventTapEnable, CGEventGetIntegerValueField,
            kCGKeyboardEventKeycode, CGEventGetFlags, CFRunLoopRun,
            kCGEventFlagMaskControl, kCGEventFlagMaskAlternate, kCGEventFlagMaskShift,
            kCGEventFlagMaskCommand)
        MB = {"ctrl": kCGEventFlagMaskControl, "alt": kCGEventFlagMaskAlternate,
              "shift": kCGEventFlagMaskShift, "cmd": kCGEventFlagMaskCommand}

        def mods_of(flags):
            return frozenset(n for n, b in MB.items() if flags & b)

        def cb(proxy, etype, event, refcon):
            try:
                flags = CGEventGetFlags(event)
                m = mods_of(flags)
                if etype == kCGEventKeyDown:
                    kc = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
                    if kc in (54, 55, 56, 57, 58, 59, 60, 61, 62, 63):  # самі модифікатори — ігнор
                        return event
                    if self.recording is not None:
                        if kc == 53:                      # Esc -> скасувати запис
                            self.recording = None
                        elif m:                            # комбо mod+клавіша
                            self._record(m, kc)
                        return event
                    self._dirty = True
                    for act, (bm, bkc) in self.binds.items():
                        if bkc is not None and bkc == kc and bm == m:
                            self._fire(act); break
                elif etype == kCGEventFlagsChanged:
                    if m:
                        if not self._active:
                            self._active = True; self._dirty = False; self._episode = set()
                        self._episode |= set(m)
                    else:                                  # всі модифікатори відпущені
                        if self._active:
                            peak = frozenset(self._episode); self._active = False
                            if peak and not self._dirty:
                                if self.recording is not None:
                                    self._record(peak, None)
                                else:
                                    for act, (bm, bkc) in self.binds.items():
                                        if bkc is None and bm == peak:
                                            self._fire(act); break
            except Exception:
                pass
            return event

        mask = CGEventMaskBit(kCGEventFlagsChanged) | CGEventMaskBit(kCGEventKeyDown)
        tap = None
        while not tap:                       # tap створиться лише з дозволом Accessibility
            tap = CGEventTapCreate(kCGSessionEventTap, kCGHeadInsertEventTap,
                                   kCGEventTapOptionListenOnly, mask, cb, None)
            if not tap:
                time.sleep(3)                # чекаємо, поки нададуть дозвіл (без рестарту)
        src = CFMachPortCreateRunLoopSource(None, tap, 0)
        CFRunLoopAddSource(CFRunLoopGetCurrent(), src, kCFRunLoopCommonModes)
        CGEventTapEnable(tap, True)
        CFRunLoopRun()


def make_glass(frame, material):
    """Liquid-Glass підкладка (NSVisualEffectView, blur за вікном)."""
    fx = NSVisualEffectView.alloc().initWithFrame_(frame)
    fx.setMaterial_(material)
    fx.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
    fx.setState_(NSVisualEffectStateActive)
    fx.setAutoresizingMask_(18)  # ширина|висота тягнуться
    return fx


THEMES = ["Авто", "Світла", "Темна"]
TOKEN_OPTS = ["512", "1024", "2048", "4096"]

# акценти = системна палітра Apple (як мітки у Finder): збалансовані, самі адаптуються до теми
ACCENT_SEL = {
    "Синій":     "systemBlueColor",
    "Червоний":  "systemRedColor",
    "Помаранч":  "systemOrangeColor",
    "Жовтий":    "systemYellowColor",
    "Зелений":   "systemGreenColor",
    "Бірюзовий": "systemTealColor",
    "Бузковий":  "systemPurpleColor",
    "Сірий":     "systemGrayColor",
}
ACCENT_ORDER = ["Синій", "Червоний", "Помаранч", "Жовтий", "Зелений", "Бірюзовий", "Бузковий", "Сірий"]

# --- сітка (єдиний дизайн-код для всіх вкладок) ---
LP_M   = 18    # зовнішнє поле вкладки
LP_PAD = 14    # внутрішнє поле картки
LP_ROW = 34    # висота рядка
LP_SEC = 16    # відстань між секціями
LP_LBL = 140   # колонка лейблів (вирівняна праворуч)
LP_HDR = 20    # висота group-заголовка над карткою
LP_GAP = 10    # проміжок між контролями


def accent_color():
    sel = ACCENT_SEL.get(load_cfg().get("accent", "Синій"), "systemBlueColor")
    return getattr(NSColor, sel)()


def accent_hex():
    try:
        c = accent_color().colorUsingColorSpace_(NSColorSpace.sRGBColorSpace())
        return "#%02x%02x%02x" % (int(c.redComponent() * 255),
                                  int(c.greenComponent() * 255),
                                  int(c.blueComponent() * 255))
    except Exception:
        return "#0a84ff"


def is_dark():
    try:
        n = NSApp.effectiveAppearance().bestMatchFromAppearancesWithNames_(
            ["NSAppearanceNameAqua", "NSAppearanceNameDarkAqua"])
        return "Dark" in str(n)
    except Exception:
        return False


# Готовий веб-патерн чату (як ChatGPT/Claude): справжні CSS-бульбашки + markdown.
# Стрім токенів і керування — через JS (web/_js), не нативним малюванням.
_CHAT_HTML = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{ --accent: __ACCENT__; }
*{box-sizing:border-box;-webkit-user-select:text;}
html,body{margin:0;padding:0;min-height:100%;}
body{font:14px/1.55 -apple-system,"SF Pro Text",system-ui,sans-serif;
  background:__BG__;color:__FG__;-webkit-font-smoothing:antialiased;}
#log{padding:18px 16px 24px;display:flex;flex-direction:column;gap:14px;}
.row{display:flex;}
.row.user{justify-content:flex-end;}
.row.ai{justify-content:flex-start;}
.bubble{max-width:80%;padding:11px 15px;border-radius:18px;overflow-wrap:anywhere;}
.user .bubble{background:var(--accent);color:#fff;border-bottom-right-radius:6px;}
.ai .bubble{background:__AIBG__;color:__FG__;border-bottom-left-radius:6px;}
.bubble p{margin:0 0 9px;} .bubble p:last-child{margin:0;}
.bubble pre{background:__PREBG__;padding:11px 13px;border-radius:11px;
  overflow-x:auto;margin:9px 0;}
.bubble code{font:12.5px/1.45 "SF Mono",ui-monospace,monospace;}
.bubble pre code{display:block;white-space:pre;}
.bubble :not(pre)>code{background:__CODEBG__;padding:1px 5px;border-radius:5px;}
.bubble h2,.bubble h3{margin:8px 0 4px;font-size:1.05em;font-weight:600;}
.bubble ul,.bubble ol{margin:7px 0;padding-left:20px;} .bubble li{margin:3px 0;}
.bubble a{color:var(--accent);}
.empty{color:__MUTED__;text-align:center;margin-top:48px;font-size:13px;}
.typing{display:inline-block;width:7px;height:15px;background:__MUTED__;
  border-radius:2px;vertical-align:-2px;animation:bl 1s steps(2,end) infinite;}
@keyframes bl{50%{opacity:0;}}
</style></head><body><div id="log"></div><script>
var log=document.getElementById('log'),aiB=null,aiRaw='';
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function md(t){var bl=[];
 t=t.replace(/```(\w*)\n?([\s\S]*?)```/g,function(m,l,c){
   bl.push('<pre><code>'+esc(c.replace(/\n$/,''))+'</code></pre>');return '¦'+(bl.length-1)+'¦';});
 t=esc(t);
 t=t.replace(/`([^`\n]+)`/g,'<code>$1</code>');
 t=t.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
 t=t.replace(/(^|[^*])\*([^*\n]+)\*/g,'$1<em>$2</em>');
 t=t.replace(/^### (.+)$/gm,'<h3>$1</h3>').replace(/^##? (.+)$/gm,'<h2>$1</h2>');
 t=t.replace(/(?:^|\n)((?:[-*] .+(?:\n|$))+)/g,function(m,b){
   return '\n<ul>'+b.trim().split('\n').map(function(l){return '<li>'+l.replace(/^[-*] /,'')+'</li>';}).join('')+'</ul>';});
 t=t.replace(/(?:^|\n)((?:\d+\. .+(?:\n|$))+)/g,function(m,b){
   return '\n<ol>'+b.trim().split('\n').map(function(l){return '<li>'+l.replace(/^\d+\. /,'')+'</li>';}).join('')+'</ol>';});
 t=t.split(/\n{2,}/).map(function(p){p=p.trim();if(!p)return '';
   if(/^<(ul|ol|pre|h[23])/.test(p))return p;return '<p>'+p.replace(/\n/g,'<br>')+'</p>';}).join('');
 t=t.replace(/¦(\d+)¦/g,function(m,i){return bl[i];});
 return t;}
function scr(){window.scrollTo(0,document.body.scrollHeight);}
function clearAll(){log.innerHTML='';aiB=null;aiRaw='';}
function rmE(){var e=log.querySelector('.empty');if(e)e.remove();}
function empty(){clearAll();var d=document.createElement('div');d.className='empty';
  d.textContent='Порожній чат. Напиши запит нижче.';log.appendChild(d);}
function row(cls){rmE();var r=document.createElement('div');r.className='row '+cls;
  r.innerHTML='<div class="bubble"></div>';log.appendChild(r);return r.firstChild;}
function addUser(t){row('user').textContent=t;scr();}
function addAI(t){row('ai').innerHTML=md(t);scr();}
function aiStart(){var b=row('ai');b.innerHTML='<span class="typing"></span>';aiB=b;aiRaw='';scr();}
function aiAppend(c){if(!aiB)aiStart();aiRaw+=c;aiB.innerHTML=md(aiRaw);scr();}
function aiEnd(){if(aiB&&!aiRaw)aiB.innerHTML='<em style="opacity:.55">порожньо</em>';aiB=null;aiRaw='';}
function note(t){rmE();var d=document.createElement('div');d.className='empty';
  d.textContent=t;log.appendChild(d);scr();}
</script></body></html>"""


def chat_html():
    dark = is_dark()
    pal = dict(BG="#1c1c1e", FG="#e9e9ec", AIBG="#2c2c2e", PREBG="#00000059",
               CODEBG="#ffffff1f", MUTED="#98989d") if dark else \
          dict(BG="#ffffff", FG="#1d1d20", AIBG="#f2f2f5", PREBG="#0000000d",
               CODEBG="#00000012", MUTED="#8a8a8e")
    pal["ACCENT"] = accent_hex()
    html = _CHAT_HTML
    for k, val in pal.items():
        html = html.replace("__%s__" % k, val)
    return html


def set_login_item(enable):
    """Автозапуск разом із входом у систему. SMAppService (macOS 13+) реєструє ЦЕЙ .app.
    Лише за явним opt-in (галочка). Реверсивно: зняв галочку → unregister. True = успіх."""
    try:
        from ServiceManagement import SMAppService
        svc = SMAppService.mainAppService()
        err = None
        if enable:
            ok, err = svc.registerAndReturnError_(None)
        else:
            ok, err = svc.unregisterAndReturnError_(None)
        return bool(ok) and err is None
    except Exception:
        return False


def apply_theme(name):
    m = {"Світла": "NSAppearanceNameAqua", "Темна": "NSAppearanceNameDarkAqua"}
    try:
        NSApp.setAppearance_(NSAppearance.appearanceNamed_(m[name]) if name in m else None)
    except Exception:
        pass


class _AccentSliderCell(NSSliderCell):
    """Лінійний слайдер у колір акценту (заповнення доріжки), а не системний синій."""
    def drawBarInside_flipped_(self, aRect, flipped):
        h = 4.0
        x = aRect.origin.x; w = aRect.size.width
        y = aRect.origin.y + (aRect.size.height - h) / 2.0
        base = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(x, y, w, h), h / 2.0, h / 2.0)
        NSColor.tertiaryLabelColor().setFill(); base.fill()
        try:
            span = self.maxValue() - self.minValue()
            frac = (self.doubleValue() - self.minValue()) / span if span else 0.0
        except Exception:
            frac = 0.0
        frac = max(0.0, min(1.0, frac))
        if frac > 0:
            fp = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(x, y, w * frac, h), h / 2.0, h / 2.0)
            accent_color().setFill(); fp.fill()


class _AccentSlider(NSSlider):
    """NSSlider, що використовує акцентний cell."""
    @classmethod
    def cellClass(cls):
        return _AccentSliderCell


class _TopClipView(NSClipView):
    """Перевернутий clip-view: документ пришпилений до ВЕРХУ, скрол стартує згори."""
    def isFlipped(self):
        return True


class _HoverButton(NSButton):
    """Іконка-кнопка: нейтральна в спокої, акцент-tint на hover, alpha-flash на натиск."""
    def initWithFrame_(self, fr):
        self = objc.super(_HoverButton, self).initWithFrame_(fr)
        if self is None: return None
        self._hovcolor = None
        self._area = None
        return self

    def setHoverColor_(self, c):
        self._hovcolor = c

    def updateTrackingAreas(self):
        if self._area is not None:
            self.removeTrackingArea_(self._area)
        # MouseEnteredAndExited(0x01)|ActiveAlways(0x80)|InVisibleRect(0x200)
        self._area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(), 0x01 | 0x80 | 0x200, self, None)
        self.addTrackingArea_(self._area)
        objc.super(_HoverButton, self).updateTrackingAreas()

    def mouseEntered_(self, e):
        if self._hovcolor is not None:
            try: self.setContentTintColor_(self._hovcolor)
            except Exception: pass

    def mouseExited_(self, e):
        try: self.setContentTintColor_(None)
        except Exception: pass
        self.setAlphaValue_(1.0)

    def mouseDown_(self, e):
        self.setAlphaValue_(0.45)          # тактильний фідбек натиску
        objc.super(_HoverButton, self).mouseDown_(e)
        self.setAlphaValue_(1.0)


# --- вікно налаштувань: голос/хоткеї + моделі (скляне) ---
class SettingsWindow(NSObject):
    def initWithPanel_(self, panel):
        self = objc.super(SettingsWindow, self).init()
        if self is None:
            return None
        self.panel = panel
        self.win = None
        self.tabs = None
        self.seg = None
        self.is_open = False
        self.hk_btns = {}
        self.token_pop = None
        self.auto_oll = None
        self.auto_tts = None
        self.tts_mode = None
        self.opt_flash = None
        self.opt_kv = None
        self.auto_login = None
        self.transp = None
        self.gen_cancel = None
        self.model_pop = None
        self.loaded_lbl = None
        self.pull_field = None
        self.pull_status = None
        self.pull_bar = None
        self.load_btn = None
        self.models_field = None
        self.lib_table = None
        self.lib_search = None
        self.lib_detail = None
        self.lib_empty = None
        self.lib_seg = None
        self.lib_sortpop = None
        self.lib_refresh_btn = None
        self.lib_all = []
        self.lib_filtered = []
        self.lib_size_cache = {}
        self.lib_size_pending = set()
        self.lib_source = "hf"
        self.lib_sort = "dl"
        self.lib_online = True
        self.sel_model = None
        self._last_up = None   # відстеження стану Ollama для авто-підхоплення в refresh
        # чат (WKWebView)
        self.web = None
        self._web_ready = False
        self._js_queue = []
        self.chat_view = None
        self.chat_input = None
        self.chat_model_lbl = None
        self.hist_pop = None
        self.autospeak = None
        self.autospeak_on = False
        self.accent_swatch = None
        self.send_btn = None
        self.sessions = [{"title": "Чат 1", "history": []}]
        self.cur = 0
        return self

    @objc.python_method
    def show(self):
        if self.win is None:
            self._build()
        self.is_open = True
        self.panel._update_activation()
        self._install_edit_menu()
        NSApp.activateIgnoringOtherApps_(True)
        self.win.makeKeyAndOrderFront_(None)
        self.reload_models()
        self._refresh_chat_header()
        self.refresh()

    def windowWillClose_(self, note):
        self.is_open = False
        self.panel._update_activation()


    @objc.python_method
    def _install_edit_menu(self):
        # rumps-апка не має Edit-меню → Cmd+A/C/V/X/Z у текстових полях мертві
        # (AppKit роздає ці дії через key-equivalents меню). Ставимо мінімальне Edit раз.
        if getattr(self, "_edit_menu_done", False):
            return
        try:
            main = NSApp.mainMenu()
            if main is None:
                main = NSMenu.alloc().init(); NSApp.setMainMenu_(main)
            it = NSMenuItem.alloc().init()
            sub = NSMenu.alloc().initWithTitle_("Редагувати")
            for title, sel, key in (
                ("Скасувати", "undo:", "z"), ("Повторити", "redo:", "Z"),
                ("Вирізати", "cut:", "x"), ("Копіювати", "copy:", "c"),
                ("Вставити", "paste:", "v"), ("Виділити все", "selectAll:", "a")):
                m = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, sel, key.lower())
                if key.isupper(): m.setKeyEquivalentModifierMask_(1 << 20 | 1 << 17)  # Cmd+Shift
                sub.addItem_(m)
            it.setSubmenu_(sub); main.addItem_(it)
            self._edit_menu_done = True
        except Exception:
            pass

    @objc.python_method
    def select_tab(self, i):
        if self.tabs is not None:
            try: self.tabs.selectTabViewItemAtIndex_(i)
            except Exception: pass
        if self.seg is not None:
            try: self.seg.setSelectedSegment_(i)
            except Exception: pass

    def segChanged_(self, sender):
        try: self.tabs.selectTabViewItemAtIndex_(sender.selectedSegment())
        except Exception: pass

    # ---------- дрібні фабрики контролів ----------
    # mask: 8=липне до верху, 32=до низу, +2=тягнеться по ширині
    @objc.python_method
    def _lbl(self, view, text, x, y, w, gray=False, h=18, mask=8, align=None):
        # mask=8 (фіксована позиція, НЕ тягнеться) — інакше right-aligned лейбли
        # колонки дрейфували вправо й налазили на контроли при ширшанні вікна.
        f = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        f.setStringValue_(text); f.setBezeled_(False); f.setDrawsBackground_(False)
        f.setEditable_(False); f.setSelectable_(False)
        if gray: f.setTextColor_(NSColor.secondaryLabelColor())
        if align is not None: f.setAlignment_(align)  # 0=ліво 1=право 2=центр
        f.setAutoresizingMask_(mask)
        view.addSubview_(f)
        return f

    @objc.python_method
    def _head(self, view, text, x, y, w):
        f = self._lbl(view, text, x, y, w)
        f.setFont_(NSFont.boldSystemFontOfSize_(13.5))
        return f

    @objc.python_method
    def _btn(self, view, title, x, y, w, action, h=28, mask=8, symbol=None, primary=False):
        b = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        b.setTitle_(title); b.setBezelStyle_(1)
        b.setTarget_(self); b.setAction_(action)
        if symbol:
            img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, title)
            if img:
                b.setImage_(img); b.setImagePosition_(2)  # NSImageLeft
        if primary:
            b.setKeyEquivalent_("\r")
            try: b.setBezelColor_(accent_color())
            except Exception: pass
        b.setAutoresizingMask_(mask)
        view.addSubview_(b)
        return b

    @objc.python_method
    def _ibtn(self, view, symbol, x, y, action, w=30, h=26, mask=8, tip="", color=None):
        """Компактна іконка-кнопка (SF Symbol). color → мінімальний акцент іконки."""
        b = _HoverButton.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        b.setBezelStyle_(1); b.setTitle_("")
        b.setTarget_(self); b.setAction_(action)
        img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, tip)
        if img:
            b.setImage_(img); b.setImagePosition_(1)  # NSImageOnly (template → нейтральний)
        if color is not None:
            b.setHoverColor_(color)        # колір лише на hover, не в спокої
        if tip: b.setToolTip_(tip)
        b.setAutoresizingMask_(mask)
        view.addSubview_(b)
        return b

    @objc.python_method
    def _grp(self, view, title, x, top, w):
        """Сірий group-заголовок над карткою. Повертає y верху картки."""
        l = self._lbl(view, title, x + 4, top - 15, w, gray=True, h=14, mask=10)
        l.setFont_(NSFont.systemFontOfSize_(11.0))
        return top - LP_HDR

    @objc.python_method
    def _card(self, view, x, top, w, rows, mask=10):
        """Скляна картка (rounded NSBox) на rows рядків. Повертає (box, top_inner)."""
        h = 2 * LP_PAD + rows * LP_ROW
        box = NSBox.alloc().initWithFrame_(NSMakeRect(x, top - h, w, h))
        box.setBoxType_(4)            # NSBoxCustom
        box.setTitlePosition_(0)      # NSNoTitle
        box.setCornerRadius_(10.0)
        box.setBorderWidth_(1.0)
        box.setBorderColor_(NSColor.separatorColor())
        box.setFillColor_(NSColor.colorWithWhite_alpha_(0.5, 0.09))
        box.setAutoresizingMask_(mask)
        view.addSubview_(box)
        return box, top

    @objc.python_method
    def _cy(self, card_top, i, ch):
        """y (низ) контролю висотою ch у рядку i картки (центрований у рядку)."""
        bandtop = card_top - LP_PAD - i * LP_ROW
        return bandtop - (LP_ROW + ch) / 2.0

    @objc.python_method
    def _field(self, view, x, y, w, placeholder="", h=26, mask=10):
        f = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        f.setEditable_(True); f.setBezeled_(True)
        if placeholder: f.setPlaceholderString_(placeholder)
        f.setAutoresizingMask_(mask)
        view.addSubview_(f)
        return f

    @objc.python_method
    def _sep(self, view, x, y, w):
        b = NSBox.alloc().initWithFrame_(NSMakeRect(x, y, w, 1)); b.setBoxType_(2)
        b.setAutoresizingMask_(10)
        view.addSubview_(b)

    @objc.python_method
    def _build(self):
        W = 700
        # Висота вікна = рівно стільки, щоб найвища вкладка («Загальні», nat 838 + шапка/відступи
        # ≈ 106 = 944) вмістилася БЕЗ скролу — але не вище за робочу область екрана (13"/малі
        # роздільності). Якщо екран нижчий → ріжемо до екрана, тоді вмикається внутр. скрол вкладки.
        NEED_H = 960
        try: screenH = NSScreen.mainScreen().visibleFrame().size.height
        except Exception: screenH = 900
        H = int(max(760, min(NEED_H, screenH - 40)))
        self.win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskResizable
            | NSWindowStyleMaskFullSizeContentView, NSBackingStoreBuffered, False)
        # Дрейф лейблів вбито в КОРЕНІ: всі лейбли/контроли mask=8 (фіксовані, НЕ тягнуться),
        # тож ширину можна вільно тягнути — нічого не налазить (з'являється лише поле справа).
        # На великому екрані вкладка вміщається повністю; на малому вікно тисне до екрана,
        # а внутр. скрол вкладки добирає різницю (показ із верху).
        self.win.setMinSize_((680, 600))   # на 13"/малих дозволяємо нижче — решту бере скрол
        self.win.setMaxSize_((1000, 100000))
        # напівпрозорість справжня: opaque-вікно ігнорувало слайдер прозорості.
        self.win.setOpaque_(False)
        self.win.setBackgroundColor_(NSColor.clearColor())
        self.win.setTitle_("LocalAI — Налаштування")
        self.win.setTitleVisibility_(1)            # NSWindowTitleHidden
        self.win.setTitlebarAppearsTransparent_(True)
        self.win.setMovableByWindowBackground_(True)
        self.win.setDelegate_(self)
        self.win.setReleasedWhenClosed_(False)
        self.win.center()
        # Popover = напівпрозорий матеріал (десктоп просвічує). Слайдер «Прозорість»
        # керує fill-overlay від solid (transp=0, читабельно як System Settings) до
        # frost (transp=100, скло). WindowBackground був майже непрозорий → слайдер
        # відкривав ПІД собою цей непрозорий матеріал, а не десктоп → ефекту не було.
        glass = make_glass(NSMakeRect(0, 0, W, H), NSVisualEffectMaterialPopover)
        self._apply_transp(glass)
        self.win.setContentView_(glass)
        self._glass = glass
        # ── шапка: власний сегмент-перемикач у чистій верхній смузі (тайтл схований,
        #    тож більше нічого з ним не колізить). NSTabView тінтиться лише системним
        #    акцентом → ховаємо рідні вкладки, керуємо сегментом, який фарбуємо акцентом. ──
        # nat = натуральна висота контенту вкладки. Фіксовані вкладки пришпилюються
        # до ВЕРХУ (порожнеча — завжди знизу, узгоджено). chat=None → тягнеться на всю площу.
        TABS = (("general", "Загальні", self._build_general, 838),
                ("voice",   "Голос",    self._build_voice,   400),
                ("models",  "Моделі",   self._build_models,  None),
                ("chat",    "Міні-чат", self._build_chat,    None))
        SEGH = 30
        HEADER = 50                       # верхня смуга під сегмент
        seg = NSSegmentedControl.alloc().initWithFrame_(
            NSMakeRect((W - 460) / 2.0, H - HEADER + (HEADER - SEGH) / 2.0, 460, SEGH))
        seg.setSegmentStyle_(1)            # Rounded — підтримує selectedSegmentBezelColor
        seg.setSegmentCount_(len(TABS))
        for i, (_id, title, _b, _h) in enumerate(TABS):
            seg.setLabel_forSegment_(title, i)
            seg.setWidth_forSegment_(115, i)
        seg.setSelectedSegment_(0)
        seg.setTarget_(self); seg.setAction_("segChanged:")
        seg.setAutoresizingMask_(1 | 4 | 8)   # центр по X, пін до верху
        try: seg.setSelectedSegmentBezelColor_(accent_color())
        except Exception: pass
        glass.addSubview_(seg); self.seg = seg
        # tabview без рідних вкладок — лише контейнер контенту
        tabsH = H - HEADER - 16
        tabs = NSTabView.alloc().initWithFrame_(NSMakeRect(16, 16, W - 32, tabsH))
        tabs.setTabViewType_(6)            # NSNoTabsNoBorder
        tabs.setAutoresizingMask_(18)
        glass.addSubview_(tabs)
        self.tabs = tabs
        CW, CH = W - 32 - 24, tabsH - 40    # видимий внутрішній розмір вкладки
        for ident, title, builder, nat in TABS:
            it = NSTabViewItem.alloc().initWithIdentifier_(ident)
            it.setLabel_(title)
            holder = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, CW, CH))
            holder.setAutoresizingMask_(18)            # тягнеться з вкладкою
            if nat:
                # Фіксована вкладка ЗАВЖДИ у скролі (гарантія: інфо не губиться ніколи).
                # Flipped-clipview → контент пришпилений до ВЕРХУ, старт згори, скролбар
                # з'являється ЛИШЕ коли вкладка (nat) вища за видиму область (CH) —
                # на великому екрані скролу не видно, на 13"/малому добирає різницю.
                sv = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, CW, CH))
                sv.setHasVerticalScroller_(True)
                sv.setHasHorizontalScroller_(False)
                sv.setAutohidesScrollers_(True)   # скролбар лише коли реально не влазить
                sv.setDrawsBackground_(False)
                sv.setAutoresizingMask_(18)
                clip = _TopClipView.alloc().initWithFrame_(NSMakeRect(0, 0, CW, CH))
                clip.setDrawsBackground_(False)
                sv.setContentView_(clip)
                doc = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, CW, nat))
                doc.setAutoresizingMask_(2)        # тягнеться по ширині
                builder(doc, CW, nat)
                sv.setDocumentView_(doc)
                holder.addSubview_(sv)
            else:                                       # chat — на всю площу
                builder(holder, CW, CH)
            it.setView_(holder)
            tabs.addTabViewItem_(it)
        try:
            self.select_tab(min(int(os.environ.get("LOCALAI_TAB", "0")), len(TABS) - 1))
        except Exception: pass

    # ---------- вкладка: ГОЛОС (лише озвучення) ----------
    @objc.python_method
    def _build_voice(self, v, CW, CH):
        x0 = LP_M
        cw = CW - 2 * LP_M
        cx = x0 + LP_PAD + LP_LBL + 12
        cwid = x0 + cw - LP_PAD - cx
        y = CH - 14

        # значення-лейбл праворуч, слайдер ліворуч від нього з відступом (без налазання)
        valw = 54
        gap = 14
        slw = lambda: cwid - valw - gap

        def stepped(yrow, lbl, lo, hi, ticks, cur, action, fmt):
            self._lbl(v, lbl, x0 + LP_PAD, self._cy(top, yrow, 18), LP_LBL, align=1)
            sl = _AccentSlider.alloc().initWithFrame_(
                NSMakeRect(cx, self._cy(top, yrow, 22), slw(), 22))
            sl.setMinValue_(lo); sl.setMaxValue_(hi)
            sl.setNumberOfTickMarks_(ticks)            # дискретні поділки
            sl.setAllowsTickMarkValuesOnly_(True)      # тягнеться кроками, не плавно
            sl.setFloatValue_(cur)
            sl.setContinuous_(True)
            sl.setTarget_(self); sl.setAction_(action); sl.setAutoresizingMask_(2)
            v.addSubview_(sl)
            val = self._lbl(v, fmt(cur), cx + cwid - valw, self._cy(top, yrow, 18),
                            valw, h=18, mask=4, align=1)
            val.setFont_(NSFont.monospacedSystemFontOfSize_weight_(12.0, 0.0))
            return sl, val

        # ── ОЗВУЧЕННЯ ──
        top = self._grp(v, "ОЗВУЧЕННЯ", x0, y, cw)
        self._card(v, x0, top, cw, 3)
        # рядок 0 — голос
        self._lbl(v, "Голос", x0 + LP_PAD, self._cy(top, 0, 18), LP_LBL, align=1)
        pop = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(cx, self._cy(top, 0, 26), cwid, 26), False)
        pop.addItemsWithTitles_(VOICES)
        if self.panel.voice in VOICES:
            pop.selectItemWithTitle_(self.panel.voice)
        pop.setTarget_(self); pop.setAction_("voiceChanged:"); pop.setAutoresizingMask_(10)
        v.addSubview_(pop)
        # рядок 1 — швидкість 0.70–1.30 кроком 0.05 (13 поділок)
        self.speed_sl, self.speed_val = stepped(
            1, "Швидкість", 0.7, 1.3, 13, getattr(self.panel, "speed", 1.0),
            "speedChanged:", lambda x: f"{x:.2f}×")
        # рядок 2 — пауза між реченнями 0.00–0.50 c кроком 0.05 (11 поділок)
        self.pause_sl, self.pause_val = stepped(
            2, "Пауза реч.", 0.0, 0.5, 11, getattr(self.panel, "pause", 0.15),
            "pauseChanged:", lambda x: f"{x:.2f} c")
        # прев'ю-кнопка під карткою
        y = top - (2 * LP_PAD + 3 * LP_ROW)
        btn_y = y - 30
        btn_h = 24
        pv = NSButton.alloc().initWithFrame_(
            NSMakeRect(x0 + LP_PAD, btn_y, 170, btn_h))
        pv.setBezelStyle_(1); pv.setTitle_("Прослухати зразок")
        pv.setTarget_(self); pv.setAction_("previewVoice:"); pv.setAutoresizingMask_(8)
        v.addSubview_(pv)
        # підпис — по центру кнопки по вертикалі (h=16, центр = центр кнопки)
        hint = self._lbl(v, "Тест голосу · швидкості · паузи.",
                         x0 + LP_PAD + 170 + 14, btn_y + (btn_h - 16) / 2.0,
                         cw - LP_PAD - 170 - 14, gray=True, h=16)
        hint.setFont_(NSFont.systemFontOfSize_(12.0))

        # ── РЕЖИМ ОЗВУЧЕННЯ ── перемикач Базовий / Стрім (стабільний дефолт = Базовий)
        y = btn_y - LP_SEC - 6
        top = self._grp(v, "РЕЖИМ ОЗВУЧЕННЯ", x0, y, cw)
        self._card(v, x0, top, cw, 1)
        self._lbl(v, "Режим", x0 + LP_PAD, self._cy(top, 0, 18), LP_LBL, align=1)
        ms = NSSegmentedControl.alloc().initWithFrame_(
            NSMakeRect(cx, self._cy(top, 0, 26), 300, 26))
        ms.setSegmentCount_(3); ms.setSegmentStyle_(1)
        ms.setLabel_forSegment_("Базовий", 0)
        ms.setLabel_forSegment_("Стрім", 1)
        ms.setLabel_forSegment_("Реалтайм", 2)
        ms.setWidth_forSegment_(90, 0); ms.setWidth_forSegment_(90, 1); ms.setWidth_forSegment_(110, 2)
        ms.setSelectedSegment_({"base": 0, "stream": 1, "realtime": 2}.get(tts_mode(), 0))
        try: ms.setSelectedSegmentBezelColor_(accent_color())
        except Exception: pass
        ms.setTarget_(self); ms.setAction_("ttsModeChanged:"); ms.setAutoresizingMask_(8)
        v.addSubview_(ms); self.tts_mode = ms
        cb = top - (2 * LP_PAD + 1 * LP_ROW)           # низ картки
        n = self._lbl(v, "Базовий — цілим файлом (стабільно). "
                         "Стрім — конвеєр, швидкий старт для виділеного/буфера. "
                         "Реалтайм — чат озвучує поки модель пише; звучання трохи гірше — "
                         "тембр стрибає між реченнями (норма для цього режиму).",
                      x0 + LP_PAD, cb - 46, cw - 2 * LP_PAD, gray=True, h=44)
        n.setFont_(NSFont.systemFontOfSize_(11.0))
        try: n.cell().setWraps_(True)
        except Exception: pass

    # ---------- вкладка: ЗАГАЛЬНІ (вигляд · хоткеї · автозапуск · генерація) ----------
    @objc.python_method
    def _build_general(self, v, CW, CH):
        x0 = LP_M
        cw = CW - 2 * LP_M
        cx = x0 + LP_PAD + LP_LBL + 12
        y = CH - 14

        # ── ВИГЛЯД ──
        top = self._grp(v, "ВИГЛЯД", x0, y, cw)
        self._card(v, x0, top, cw, 3)
        self._lbl(v, "Тема", x0 + LP_PAD, self._cy(top, 0, 18), LP_LBL, align=1)
        tp = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(cx, self._cy(top, 0, 26), 220, 26), False)
        tp.addItemsWithTitles_(THEMES)
        tp.selectItemWithTitle_(load_cfg().get("theme", "Авто"))
        tp.setTarget_(self); tp.setAction_("themeChanged:"); tp.setAutoresizingMask_(8)
        v.addSubview_(tp)
        self._lbl(v, "Акцент", x0 + LP_PAD, self._cy(top, 1, 18), LP_LBL, align=1)
        ap = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(cx, self._cy(top, 1, 26), 220, 26), False)
        ap.addItemsWithTitles_(ACCENT_ORDER)
        ap.selectItemWithTitle_(load_cfg().get("accent", "Синій"))
        ap.setTarget_(self); ap.setAction_("accentChanged:"); ap.setAutoresizingMask_(8)
        v.addSubview_(ap)
        sw = NSBox.alloc().initWithFrame_(NSMakeRect(cx + 230, self._cy(top, 1, 18), 30, 18))
        sw.setBoxType_(4); sw.setTitlePosition_(0); sw.setCornerRadius_(5.0)
        sw.setBorderWidth_(0.0); sw.setFillColor_(accent_color()); sw.setAutoresizingMask_(8)
        v.addSubview_(sw); self.accent_swatch = sw
        self._lbl(v, "Прозорість", x0 + LP_PAD, self._cy(top, 2, 18), LP_LBL, align=1)
        sl = _AccentSlider.alloc().initWithFrame_(NSMakeRect(cx, self._cy(top, 2, 22), 220, 22))
        sl.setMinValue_(0.0); sl.setMaxValue_(100.0)
        sl.setFloatValue_(float(load_cfg().get("transp", 35)))
        sl.setContinuous_(True)
        sl.setTarget_(self); sl.setAction_("transpChanged:"); sl.setAutoresizingMask_(8)
        v.addSubview_(sl); self.transp = sl
        y = top - (2 * LP_PAD + 3 * LP_ROW) - LP_SEC

        # ── ГЛОБАЛЬНІ ХОТКЕЇ ──
        top = self._grp(v, "ГЛОБАЛЬНІ ХОТКЕЇ", x0, y, cw)
        self._card(v, x0, top, cw, len(HK_LABELS))
        for i, (act, label) in enumerate(HK_LABELS):
            self._lbl(v, label, x0 + LP_PAD, self._cy(top, i, 18), LP_LBL, align=1)
            cur = self._lbl(v, "", cx, self._cy(top, i, 18), 120)
            cur.setFont_(NSFont.monospacedSystemFontOfSize_weight_(12.5, 0.0))
            self.hk_btns[act] = cur
            xclr = x0 + cw - LP_PAD - 28
            xrec = xclr - 8 - 96
            self._btn(v, "Записати", xrec, self._cy(top, i, 26), 96, "recordHK:", h=26, mask=8).setTag_(i)
            self._ibtn(v, "xmark", xclr, self._cy(top, i, 26), "clearHK:", w=28,
                       tip="Очистити", color=NSColor.secondaryLabelColor()).setTag_(i)
        y = top - (2 * LP_PAD + len(HK_LABELS) * LP_ROW)
        self._lbl(v, "«Записати» → натисни комбо. Esc — скасувати.",
                  x0 + LP_PAD, y - 15, cw - 2 * LP_PAD, gray=True, h=14)
        y -= 15 + LP_SEC

        # ── АВТОЗАПУСК ──
        top = self._grp(v, "АВТОЗАПУСК", x0, y, cw)
        self._card(v, x0, top, cw, 3)
        cfg = load_cfg()
        self.auto_login = NSButton.alloc().initWithFrame_(
            NSMakeRect(x0 + LP_PAD, self._cy(top, 0, 22), cw - 2 * LP_PAD, 22))
        self.auto_login.setButtonType_(3)
        self.auto_login.setTitle_("Запускати LocalAI разом із входом у систему")
        self.auto_login.setState_(1 if cfg.get("autostart_login") else 0)
        self.auto_login.setTarget_(self); self.auto_login.setAction_("autoLoginToggled:")
        self.auto_login.setAutoresizingMask_(8); v.addSubview_(self.auto_login)
        self.auto_oll = NSButton.alloc().initWithFrame_(
            NSMakeRect(x0 + LP_PAD, self._cy(top, 1, 22), cw - 2 * LP_PAD, 22))
        self.auto_oll.setButtonType_(3); self.auto_oll.setTitle_("При відкритті панелі — запускати Ollama")
        self.auto_oll.setState_(1 if cfg.get("autostart_ollama") else 0)
        self.auto_oll.setTarget_(self); self.auto_oll.setAction_("autoOllToggled:")
        self.auto_oll.setAutoresizingMask_(8); v.addSubview_(self.auto_oll)
        self.auto_tts = NSButton.alloc().initWithFrame_(
            NSMakeRect(x0 + LP_PAD, self._cy(top, 2, 22), cw - 2 * LP_PAD, 22))
        self.auto_tts.setButtonType_(3); self.auto_tts.setTitle_("При відкритті панелі — запускати TTS (озвучка)")
        self.auto_tts.setState_(1 if cfg.get("autostart_tts") else 0)
        self.auto_tts.setTarget_(self); self.auto_tts.setAction_("autoTtsToggled:")
        self.auto_tts.setAutoresizingMask_(8); v.addSubview_(self.auto_tts)
        y = top - (2 * LP_PAD + 3 * LP_ROW) - LP_SEC

        # ── ГЕНЕРАЦІЯ ──
        top = self._grp(v, "ГЕНЕРАЦІЯ", x0, y, cw)
        self._card(v, x0, top, cw, 1)
        self._lbl(v, "Відповідь, токенів", x0 + LP_PAD, self._cy(top, 0, 18), LP_LBL, align=1)
        self.token_pop = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(cx, self._cy(top, 0, 26), 120, 26), False)
        self.token_pop.addItemsWithTitles_(TOKEN_OPTS)
        self.token_pop.selectItemWithTitle_(str(load_cfg().get("num_predict", 2048)))
        self.token_pop.setTarget_(self); self.token_pop.setAction_("tokenChanged:")
        self.token_pop.setAutoresizingMask_(8); v.addSubview_(self.token_pop)
        y = top - (2 * LP_PAD + 1 * LP_ROW) - LP_SEC

        # ── ОПТИМІЗАЦІЯ OLLAMA (8ГБ) ──
        top = self._grp(v, "ОПТИМІЗАЦІЯ OLLAMA (8ГБ)", x0, y, cw)
        self._card(v, x0, top, cw, 2)
        cfg = load_cfg()
        self.opt_flash = NSButton.alloc().initWithFrame_(
            NSMakeRect(x0 + LP_PAD, self._cy(top, 0, 22), cw - 2 * LP_PAD, 22))
        self.opt_flash.setButtonType_(3)
        self.opt_flash.setTitle_("Flash Attention — швидше, менше RAM на контекст")
        self.opt_flash.setState_(1 if cfg.get("ollama_flash", True) else 0)
        self.opt_flash.setTarget_(self); self.opt_flash.setAction_("optFlashToggled:")
        self.opt_flash.setAutoresizingMask_(8); v.addSubview_(self.opt_flash)
        self.opt_kv = NSButton.alloc().initWithFrame_(
            NSMakeRect(x0 + LP_PAD, self._cy(top, 1, 22), cw - 2 * LP_PAD, 22))
        self.opt_kv.setButtonType_(3)
        self.opt_kv.setTitle_("KV-кеш 8-біт — ~вдвічі менше пам'яті (потребує Flash)")
        self.opt_kv.setState_(1 if cfg.get("ollama_kv_q8", True) else 0)
        self.opt_kv.setTarget_(self); self.opt_kv.setAction_("optKvToggled:")
        self.opt_kv.setAutoresizingMask_(8); v.addSubview_(self.opt_kv)
        self.opt_kv.setEnabled_(bool(cfg.get("ollama_flash", True)))   # KV без Flash не діє
        y = top - (2 * LP_PAD + 2 * LP_ROW)
        self._lbl(v, "Діє при наступному старті Ollama (СТОП → Старт у меню).",
                  x0 + LP_PAD, y - 15, cw - 2 * LP_PAD, gray=True, h=14)

    # ---------- вкладка 2: моделі ----------
    @objc.python_method
    def _build_models(self, v, CW, CH):
        x0 = LP_M
        cw = CW - 2 * LP_M
        il = x0 + LP_PAD                 # ліва межа контенту картки
        ir = x0 + cw - LP_PAD            # права межа
        iw = ir - il                     # ширина контенту
        y = CH - 14

        # ── АКТИВНА МОДЕЛЬ ──
        top = self._grp(v, "АКТИВНА МОДЕЛЬ", x0, y, cw)
        self._card(v, x0, top, cw, 3)
        self.model_pop = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(il, self._cy(top, 0, 26), iw, 26), False)
        self.model_pop.setTarget_(self); self.model_pop.setAction_("modelChanged:")
        self.model_pop.setAutoresizingMask_(10)
        v.addSubview_(self.model_pop)
        self.loaded_lbl = self._lbl(v, "", il, self._cy(top, 1, 18), iw, gray=True)
        bw = (iw - 2 * LP_GAP) / 3.0
        self.load_btn = self._btn(v, "У RAM", il, self._cy(top, 2, 26), bw, "loadModel:",
                  h=26, symbol="arrow.down.circle")
        self._btn(v, "Вивантажити", il + bw + LP_GAP, self._cy(top, 2, 26), bw, "unloadModel:",
                  h=26, symbol="arrow.up.circle")
        self._btn(v, "Видалити", il + 2 * (bw + LP_GAP), self._cy(top, 2, 26), bw, "deleteModel:",
                  h=26, symbol="trash")
        y = top - (2 * LP_PAD + 3 * LP_ROW) - LP_SEC

        # ── ЗАВАНТАЖИТИ НОВУ ──
        top = self._grp(v, "ЗАВАНТАЖИТИ НОВУ", x0, y, cw)
        self._card(v, x0, top, cw, 3)
        self.pull_field = self._field(v, il, self._cy(top, 0, 26), iw - 140,
                                      "qwen3:4b-instruct-2507-q4_K_M", mask=10)
        self._btn(v, "Завантажити", ir - 130, self._cy(top, 0, 26), 130, "doPull:",
                  h=26, mask=9, symbol="square.and.arrow.down")
        # активне табло прогресу (визначений бар + %), показується лише під час тяги
        self.pull_bar = NSProgressIndicator.alloc().initWithFrame_(
            NSMakeRect(il, self._cy(top, 1, 8) + 4, iw, 8))
        self.pull_bar.setStyle_(0)               # NSProgressIndicatorBarStyle
        self.pull_bar.setIndeterminate_(False)
        self.pull_bar.setMinValue_(0.0); self.pull_bar.setMaxValue_(100.0)
        self.pull_bar.setHidden_(True); self.pull_bar.setAutoresizingMask_(10)
        v.addSubview_(self.pull_bar)
        self.pull_status = self._lbl(v, "ollama.com/library  ·  hf.co/<repo>:Q4_K_M",
                                     il, self._cy(top, 2, 16), iw, gray=True, h=14)
        # довгі назви не ламають верстку — обрізаємо посередині
        try: self.pull_status.cell().setLineBreakMode_(5)   # TruncatingMiddle
        except Exception: pass
        y = top - (2 * LP_PAD + 3 * LP_ROW) - LP_SEC

        # ── ПАПКА МОДЕЛЕЙ (пришпилена ДО НИЗУ — щоб бібліотека росла з висотою вікна) ──
        fb = 6                                   # нижній відступ
        fcard_h = 2 * LP_PAD + 2 * LP_ROW
        fcard_top = fb + fcard_h
        fgrp_top = fcard_top + LP_HDR
        fl = self._lbl(v, "ПАПКА МОДЕЛЕЙ", x0 + 4, fgrp_top - 15, cw, gray=True, h=14, mask=34)
        fl.setFont_(NSFont.systemFontOfSize_(11.0))
        fbox = NSBox.alloc().initWithFrame_(NSMakeRect(x0, fb, cw, fcard_h))
        fbox.setBoxType_(4); fbox.setTitlePosition_(0); fbox.setCornerRadius_(10.0)
        fbox.setBorderWidth_(1.0); fbox.setBorderColor_(NSColor.separatorColor())
        fbox.setFillColor_(NSColor.colorWithWhite_alpha_(0.5, 0.09))
        fbox.setAutoresizingMask_(34); v.addSubview_(fbox)
        self.models_field = self._field(v, il, self._cy(fcard_top, 0, 26), iw - 220, "", mask=34)
        self.models_field.setStringValue_(models_dir())
        self._ibtn(v, "folder", ir - 210, self._cy(fcard_top, 0, 26), "browseModelsDir:",
                   w=40, tip="Огляд…", mask=33)
        self._btn(v, "Застосувати", ir - 160, self._cy(fcard_top, 0, 26), 160, "applyModelsDir:",
                  h=26, mask=33)
        fh = self._lbl(v, "Після зміни — перезапусти Ollama в меню панелі.",
                       il, self._cy(fcard_top, 1, 16), iw, gray=True, h=14, mask=34)

        # ── БІБЛІОТЕКА (огляд + пошук; росте з висотою вікна) ──
        lib_top = y
        hg = self._lbl(v, "БІБЛІОТЕКА МОДЕЛЕЙ", x0 + 4, lib_top - 15, cw, gray=True, h=14, mask=10)
        hg.setFont_(NSFont.systemFontOfSize_(11.0))
        box_top = lib_top - LP_HDR
        box_bottom = fgrp_top + 24
        box = NSBox.alloc().initWithFrame_(NSMakeRect(x0, box_bottom, cw, box_top - box_bottom))
        box.setBoxType_(4); box.setTitlePosition_(0); box.setCornerRadius_(10.0)
        box.setBorderWidth_(1.0); box.setBorderColor_(NSColor.separatorColor())
        box.setFillColor_(NSColor.colorWithWhite_alpha_(0.5, 0.09))
        box.setAutoresizingMask_(18); v.addSubview_(box)
        # рядок 1: джерело (segmented) · сортування · оновити-іконка
        cy = box_top - LP_PAD - 26
        seg = NSSegmentedControl.alloc().initWithFrame_(NSMakeRect(il, cy, 200, 26))
        seg.setSegmentCount_(2); seg.setSegmentStyle_(1)
        seg.setLabel_forSegment_("Ollama", 0)
        seg.setLabel_forSegment_("HuggingFace", 1)
        seg.setWidth_forSegment_(70, 0); seg.setWidth_forSegment_(120, 1)
        seg.setSelectedSegment_(1)               # дефолт — HuggingFace (більше GGUF)
        try: seg.setSelectedSegmentBezelColor_(accent_color())   # акцент, не системний синій
        except Exception: pass
        seg.setTarget_(self); seg.setAction_("sourceChanged:"); seg.setAutoresizingMask_(8)
        v.addSubview_(seg); self.lib_seg = seg
        ref_x = ir - 30
        self.lib_refresh_btn = self._ibtn(v, "arrow.clockwise", ref_x, cy, "libRefresh:",
                   w=30, h=26, mask=9, tip="Оновити список")
        sp = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(il + 210, cy, ref_x - 10 - (il + 210), 26), False)
        sp.addItemsWithTitles_(["↓ Завантаження", "А-Я Назва", "Розмір"])
        sp.setTarget_(self); sp.setAction_("sortChanged:"); sp.setAutoresizingMask_(10)
        v.addSubview_(sp); self.lib_sortpop = sp
        # рядок 2: пошук
        sy = cy - 8 - 26
        self.lib_search = self._field(v, il, sy, iw, "Пошук моделі…", mask=10)
        self.lib_search.setTarget_(self); self.lib_search.setAction_("libSearch:")
        # таблиця (2 колонки: модель · розмір) — тягнеться по висоті
        t_top = sy - 8
        t_bot = box_bottom + LP_PAD
        sc = NSScrollView.alloc().initWithFrame_(NSMakeRect(il, t_bot, iw, t_top - t_bot))
        sc.setHasVerticalScroller_(True); sc.setBorderType_(0)
        sc.setDrawsBackground_(False); sc.setAutoresizingMask_(18)
        table = NSTableView.alloc().initWithFrame_(NSMakeRect(0, 0, iw, t_top - t_bot))
        table.setRowHeight_(22.0); table.setHeaderView_(None)
        table.setBackgroundColor_(NSColor.clearColor())
        table.setColumnAutoresizingStyle_(1)     # рівномірно
        cN = NSTableColumn.alloc().initWithIdentifier_("name"); cN.setWidth_(iw - 96)
        cS = NSTableColumn.alloc().initWithIdentifier_("size"); cS.setWidth_(80)
        cS.dataCell().setAlignment_(2)           # розмір — праворуч
        cS.dataCell().setTextColor_(NSColor.secondaryLabelColor())
        table.addTableColumn_(cN); table.addTableColumn_(cS)
        table.setDataSource_(self); table.setDelegate_(self)
        table.setTarget_(self); table.setDoubleAction_("libPick:")
        sc.setDocumentView_(table)
        v.addSubview_(sc); self.lib_table = table
        # заглушка (офлайн / порожньо) — по центру таблиці, 2 рядки
        self.lib_empty = self._lbl(v, "", il, (t_top + t_bot) / 2.0 - 22,
                                   iw, gray=True, h=44, mask=18, align=1)
        try:
            self.lib_empty.cell().setWraps_(True)
            self.lib_empty.cell().setAlignment_(1)   # 1 = центр (UIKit-style enum)
        except Exception: pass
        self.lib_empty.setHidden_(True)
        # підказка дії (пришпилена до низу, над папкою)
        self.lib_detail = self._lbl(
            v, "Подвійний клік — у поле «Завантажити».  HF → hf.co/repo:Q4_K_M",
            il, fgrp_top + 4, iw, gray=True, h=16, mask=34)
        self.lib_detail.setFont_(NSFont.systemFontOfSize_(11.0))
        self.lib_all = []; self.lib_filtered = []
        self.lib_size_cache = {}; self.lib_size_pending = set()
        self.lib_source = "hf"; self.lib_sort = "dl"; self.lib_online = True
        self._refresh_library()

    # ---------- вкладка 3: міні-чат ----------
    @objc.python_method
    def _build_chat(self, v, CW, CH):
        M = LP_M
        red = NSColor.systemRedColor()
        org = NSColor.systemOrangeColor()
        # ── верхній рядок: модель (зліва) · ＋новий · 🗑очистити · історія (справа) ──
        ty = CH - 30
        self.hist_pop = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(CW - M - 190, ty - 4, 190, 26), False)
        self.hist_pop.setTarget_(self); self.hist_pop.setAction_("histChanged:")
        self.hist_pop.setAutoresizingMask_(9)  # верх-право
        v.addSubview_(self.hist_pop)
        xclr = CW - M - 190 - 8 - 30
        xnew = xclr - 6 - 30
        self._ibtn(v, "trash", xclr, ty - 4, "clearChat:", w=30, mask=9,
                   tip="Очистити", color=NSColor.secondaryLabelColor())
        self._ibtn(v, "plus", xnew, ty - 4, "newChat:", w=30, mask=9,
                   tip="Новий чат", color=accent_color())
        self.chat_model_lbl = self._lbl(v, "", M, ty, xnew - M - 10, gray=True, mask=10)
        # ── низ (знизу вгору): службовий рядок · ввід-пігулка · транскрипт ──
        svc_y = 12
        pill_y = 42
        pill_h = 40
        tr_bottom = pill_y + pill_h + 12
        tr_top = ty - 12
        frame = NSMakeRect(M, tr_bottom, CW - 2 * M, tr_top - tr_bottom)
        web = WKWebView.alloc().initWithFrame_configuration_(
            frame, WKWebViewConfiguration.alloc().init())
        web.setNavigationDelegate_(self)
        web.setAutoresizingMask_(18)
        # рамка-картка довкола чату (як панель у референсах)
        web.setWantsLayer_(True)
        try:
            web.layer().setCornerRadius_(12.0)
            web.layer().setMasksToBounds_(True)
            web.layer().setBorderWidth_(1.0)
            web.layer().setBorderColor_(NSColor.separatorColor().CGColor())
        except Exception:
            pass
        v.addSubview_(web); self.web = web
        web.loadHTMLString_baseURL_(chat_html(), None)
        # ── ввід-пігулка: [ поле … ⏹ ◉ ] — одна заокруглена смуга, як Claude/iMessage ──
        pill = NSBox.alloc().initWithFrame_(NSMakeRect(M, pill_y, CW - 2 * M, pill_h))
        pill.setBoxType_(4); pill.setTitlePosition_(0)
        pill.setCornerRadius_(pill_h / 2.0); pill.setBorderWidth_(1.0)
        pill.setBorderColor_(NSColor.separatorColor())
        pill.setFillColor_(NSColor.colorWithWhite_alpha_(0.5, 0.10))
        pill.setAutoresizingMask_(34)              # ширина тягнеться, пін до низу
        v.addSubview_(pill)
        send_d = 30
        sx = CW - M - 9 - send_d
        stx = sx - 4 - 26
        in_x = M + 16
        in_w = stx - 10 - in_x
        # багаторядкове поле: Enter — надіслати, Shift+Enter — новий рядок (NSTextView,
        # бо NSTextField однорядковий і Shift+Enter у ньому неможливий).
        in_h = 26
        # плейсхолдер ДОДАЄМО ПЕРШИМ (позаду поля) — інакше він перекриває NSTextView
        # і краде кліки (поле не клікалось). Поле зверху → клікабельне; текст прозорий → видно.
        self.chat_ph = self._lbl(v, "Запит…  (Enter — надіслати · Shift+Enter — новий рядок)",
                                 in_x + 4, pill_y + (pill_h - 18) / 2.0, in_w - 8, gray=True, mask=34)
        sc = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(in_x, pill_y + (pill_h - in_h) / 2.0, in_w, in_h))
        sc.setDrawsBackground_(False); sc.setBorderType_(0)
        sc.setHasVerticalScroller_(False); sc.setAutoresizingMask_(34)
        tv = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, in_w, in_h))
        tv.setDrawsBackground_(False); tv.setRichText_(False)
        tv.setFont_(NSFont.systemFontOfSize_(13.5)); tv.setTextColor_(NSColor.labelColor())
        tv.setTextContainerInset_(NSMakeSize(2, 4))   # вертикальне центрування рядка в пігулці
        tv.setDelegate_(self); tv.setAutoresizingMask_(2)
        sc.setDocumentView_(tv)
        v.addSubview_(sc)
        self.chat_input = tv
        self._ibtn(v, "stop.circle", stx, pill_y + (pill_h - 26) / 2.0, "stopGen:",
                   w=26, h=26, mask=33, tip="Зупинити генерацію", color=red)
        self.send_btn = self._sendbtn(v, sx, pill_y + (pill_h - send_d) / 2.0, send_d)
        # ── службовий рядок: озвучка (ліво) · пауза/стоп (поруч) ──
        self.autospeak = NSButton.alloc().initWithFrame_(NSMakeRect(M, svc_y, 175, 22))
        self.autospeak.setButtonType_(3)
        self.autospeak.setTitle_("Озвучувати відповіді")
        self.autospeak.setTarget_(self); self.autospeak.setAction_("autospeakToggled:")
        self.autospeak.setAutoresizingMask_(32)
        v.addSubview_(self.autospeak)
        self._ibtn(v, "pause.fill", M + 182, svc_y - 2, "pauseSpeechBtn:", w=30,
                   mask=32, tip="Пауза / продовжити", color=org)
        self._ibtn(v, "stop.fill", M + 182 + 36, svc_y - 2, "stopSpeechBtn:", w=30,
                   mask=32, tip="Стоп озвучку", color=red)
        # «Відповідь, токенів» перенесено у вкладку «Загальні → Генерація».
        self._reload_hist()

    @objc.python_method
    def _sendbtn(self, view, x, y, d):
        """Кругла акцентна кнопка надсилання (SF Symbol arrow.up.circle.fill)."""
        b = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, d, d))
        b.setBordered_(False); b.setTitle_("")
        b.setTarget_(self); b.setAction_("sendChat:")
        cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(float(d), 0.0)
        img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "arrow.up.circle.fill", "Надіслати")
        if img:
            img = img.imageWithSymbolConfiguration_(cfg) or img
            b.setImage_(img); b.setImagePosition_(1)
        try: b.setContentTintColor_(accent_color())
        except Exception: pass
        b.setToolTip_("Надіслати"); b.setAutoresizingMask_(33)
        view.addSubview_(b)
        return b

    # ---------- дії: голос/хоткеї ----------
    def voiceChanged_(self, sender):
        v = sender.titleOfSelectedItem()
        self.panel.voice = v
        cfg = load_cfg(); cfg["voice"] = v; save_cfg(cfg)

    def speedChanged_(self, sender):
        sp = max(0.7, min(1.3, float(sender.floatValue())))
        self.panel.speed = sp
        if getattr(self, "speed_val", None) is not None:
            self.speed_val.setStringValue_(f"{sp:.2f}×")
        cfg = load_cfg(); cfg["speed"] = round(sp, 2); save_cfg(cfg)

    def pauseChanged_(self, sender):
        pz = max(0.0, min(0.6, float(sender.floatValue())))
        self.panel.pause = pz
        if getattr(self, "pause_val", None) is not None:
            self.pause_val.setStringValue_(f"{pz:.2f} c")
        cfg = load_cfg(); cfg["pause"] = round(pz, 2); save_cfg(cfg)

    def previewVoice_(self, sender):
        # повторний клік під час відтворення → СТОП
        if self.panel._state in ("synth", "playing", "paused"):
            self.panel.stop_speech(None)
            sender.setTitle_("Прослухати зразок")
            return
        sample = ("Привіт. Це зразок мого голосу. "
                  "Перевіряю швидкість і паузу між реченнями. Один, два, три.")
        sender.setTitle_("Зупинити")
        def run():
            self.panel._speak(sample)
            # дочекатись завершення → повернути назву кнопки
            time.sleep(0.4)
            while self.panel._state in ("synth", "playing", "paused"):
                time.sleep(0.15)
            AppHelper.callAfter(sender.setTitle_, "Прослухати зразок")
        threading.Thread(target=run, daemon=True).start()

    def themeChanged_(self, sender):
        t = str(sender.titleOfSelectedItem())
        cfg = load_cfg(); cfg["theme"] = t; save_cfg(cfg)
        apply_theme(t)
        self._reload_web()  # чат під нову тему

    def accentChanged_(self, sender):
        a = str(sender.titleOfSelectedItem())
        cfg = load_cfg(); cfg["accent"] = a; save_cfg(cfg)
        ac = accent_color()
        if self.accent_swatch is not None:
            self.accent_swatch.setFillColor_(ac)
        if self.seg is not None:
            try: self.seg.setSelectedSegmentBezelColor_(ac)   # верхній перемикач теж перефарбувати
            except Exception: pass
        if self.send_btn is not None:
            try: self.send_btn.setContentTintColor_(ac)
            except Exception: pass
        for sg in (self.lib_seg, getattr(self, "tts_mode", None)):
            if sg is not None:
                try: sg.setSelectedSegmentBezelColor_(ac)
                except Exception: pass
        # акцентні слайдери перемалювати під новий колір
        for sl in (getattr(self, "speed_sl", None), getattr(self, "pause_sl", None),
                   getattr(self, "transp", None)):
            if sl is not None: sl.setNeedsDisplay_(True)
        self._update_loaded()   # «У RAM», якщо активна, теж у новий акцент
        self._reload_web()  # перемалювати чат новим акцентом

    def autoOllToggled_(self, sender):
        cfg = load_cfg(); cfg["autostart_ollama"] = bool(sender.state()); save_cfg(cfg)

    def autoTtsToggled_(self, sender):
        cfg = load_cfg(); cfg["autostart_tts"] = bool(sender.state()); save_cfg(cfg)

    def optFlashToggled_(self, sender):
        on = bool(sender.state())
        cfg = load_cfg(); cfg["ollama_flash"] = on; save_cfg(cfg)
        if self.opt_kv is not None:            # KV-кеш без Flash не діє → гасимо
            self.opt_kv.setEnabled_(on)

    def optKvToggled_(self, sender):
        cfg = load_cfg(); cfg["ollama_kv_q8"] = bool(sender.state()); save_cfg(cfg)

    def ttsModeChanged_(self, sender):
        # 0=Базовий (стабільний) · 1=Стрім (конвеєр) · 2=Реалтайм (чат озвучує поки пише)
        m = {0: "base", 1: "stream", 2: "realtime"}.get(sender.selectedSegment(), "base")
        cfg = load_cfg(); cfg["tts_mode"] = m
        cfg["tts_stream"] = (m != "base")          # сумісність зі старим ключем
        save_cfg(cfg)

    def autoLoginToggled_(self, sender):
        on = bool(sender.state())
        ok = set_login_item(on)            # реєстрація login-item лише за галочкою (явний opt-in)
        cfg = load_cfg(); cfg["autostart_login"] = on; save_cfg(cfg)
        if not ok:
            sender.setState_(0)
            cfg = load_cfg(); cfg["autostart_login"] = False; save_cfg(cfg)
            rumps.notification("LocalAI", "Не вдалося внести в автозапуск входу",
                               "Додай вручну: Системні налаштування → Загальні → Елементи входу")

    def transpChanged_(self, sender):
        cfg = load_cfg(); cfg["transp"] = int(sender.floatValue()); save_cfg(cfg)
        if getattr(self, "_glass", None) is not None:
            self._apply_transp(self._glass)

    @objc.python_method
    def _apply_transp(self, glass):
        """Прозорість «скла»: непрозора підкладка поверх блюру, alpha = 1−прозорість.
        0 = суцільний фон (як System Settings), 100 = максимум скла."""
        frac = max(0, min(100, int(load_cfg().get("transp", 35)))) / 100.0
        fill = getattr(self, "_transp_fill", None)
        if fill is None:
            fill = NSView.alloc().initWithFrame_(glass.bounds())
            fill.setWantsLayer_(True)
            fill.setAutoresizingMask_(18)
            glass.addSubview_positioned_relativeTo_(fill, -1, None)  # NSWindowBelow — під контентом
            self._transp_fill = fill
        try:
            c = NSColor.windowBackgroundColor().colorUsingColorSpace_(NSColorSpace.sRGBColorSpace())
            fill.layer().setBackgroundColor_(
                NSColor.colorWithRed_green_blue_alpha_(
                    c.redComponent(), c.greenComponent(), c.blueComponent(), 1.0 - frac).CGColor())
        except Exception: pass

    def browseModelsDir_(self, sender):
        p = NSOpenPanel.openPanel()
        p.setCanChooseDirectories_(True); p.setCanChooseFiles_(False)
        p.setAllowsMultipleSelection_(False); p.setPrompt_("Вибрати")
        if p.runModal() == 1:
            url = p.URLs()[0]
            self.models_field.setStringValue_(str(url.path()))

    def recordHK_(self, sender):
        self.panel.hotkeys.recording = HK_LABELS[sender.tag()][0]

    def clearHK_(self, sender):
        act = HK_LABELS[sender.tag()][0]
        cfg = load_cfg(); hk = cfg.get("hotkeys", dict(DEFAULT_HOTKEYS))
        hk[act] = None; cfg["hotkeys"] = hk; save_cfg(cfg)
        self.panel.hotkeys.reload()

    # ---------- дії: моделі ----------
    def modelChanged_(self, sender):
        t = sender.titleOfSelectedItem()
        self.sel_model = str(t) if t else None
        self._update_loaded()
        self._refresh_chat_header()

    def loadModel_(self, sender):  self.panel.load_model(self.sel_model)
    def unloadModel_(self, sender): self.panel.unload_one(self.sel_model)
    def deleteModel_(self, sender): self.panel.delete_model(self.sel_model)

    def doPull_(self, sender):
        name = str(self.pull_field.stringValue()).strip()
        if name: self.panel.start_pull(name)

    # ── бібліотека моделей (Ollama / HuggingFace) ──
    def numberOfRowsInTableView_(self, tv):
        return len(getattr(self, "lib_filtered", []))

    def tableView_objectValueForTableColumn_row_(self, tv, col, row):
        rows = getattr(self, "lib_filtered", [])
        if not (0 <= row < len(rows)):
            return ""
        r = rows[row]
        if str(col.identifier()) == "size":
            return self._size_for(r)
        dl = r.get("dl")
        return f"{r['id']}    ↓{short_num(dl)}" if dl else r["id"]

    @objc.python_method
    def _size_for(self, r):
        """Розмір рядка з кешем; не в кеші → фонове підвантаження (лише видимі рядки
        просить AppKit) + reload. cache[key] = (human, quant, nbytes)."""
        key = (r["kind"], r["id"])
        if key in self.lib_size_cache:
            return self.lib_size_cache[key][0]
        if key not in self.lib_size_pending:
            self.lib_size_pending.add(key)
            def work():
                if r["kind"] == "hf":
                    nb, quant = fetch_hf_repo_size(r["id"])
                else:
                    nb, quant = fetch_model_size(r["id"]), None
                def done():
                    self.lib_size_cache[key] = (human_size(nb), quant, nb or 0)
                    self.lib_size_pending.discard(key)
                    if self.lib_table is not None:
                        self.lib_table.reloadData()
                AppHelper.callAfter(done)
            threading.Thread(target=work, daemon=True).start()
        return "…"

    def libPick_(self, sender):
        rows = getattr(self, "lib_filtered", [])
        r = self.lib_table.selectedRow() if self.lib_table else -1
        if not (0 <= r < len(rows)):
            return
        row = rows[r]
        if row["kind"] == "hf":
            quant = (self.lib_size_cache.get(("hf", row["id"])) or (None, None))[1] or "Q4_K_M"
            name = f"hf.co/{row['id']}:{quant}"
        else:
            name = row["id"]
        self.pull_field.setStringValue_(name)
        self.set_pull_status(f"Готово до завантаження: {name}")

    def libSearch_(self, sender):
        if self.lib_source == "hf":       # HF — пошук на сервері
            self._refresh_library(force=True)
        else:                             # Ollama — клієнтський фільтр
            self._apply_lib_filter()

    def libRefresh_(self, sender):
        self._refresh_library(force=True)

    def sourceChanged_(self, sender):
        self.lib_source = "hf" if sender.selectedSegment() == 1 else "ollama"
        self._refresh_library(force=True)

    def sortChanged_(self, sender):
        self.lib_sort = ("dl", "name", "size")[max(0, sender.indexOfSelectedItem())]
        self._apply_lib_filter()

    @objc.python_method
    def _apply_lib_filter(self):
        self._apply_lib_online_ui()
        if not self.lib_online:           # офлайн → чистий список + заглушка, без сміття
            self.lib_filtered = []
            if self.lib_table is not None:
                self.lib_table.reloadData()
            self._update_lib_empty()
            return
        q = str(self.lib_search.stringValue()).strip().lower() if self.lib_search else ""
        src = getattr(self, "lib_all", [])
        rows = [r for r in src if q in r["id"].lower()] if q else list(src)
        sk = self.lib_sort
        if sk == "name":
            rows.sort(key=lambda r: r["id"].lower())
        elif sk == "size":
            def sz(r):
                v = self.lib_size_cache.get((r["kind"], r["id"]))
                return v[2] if v and v[2] else float("inf")
            rows.sort(key=sz)
        else:
            rows.sort(key=lambda r: -(r.get("dl") or 0))
        self.lib_filtered = rows
        if self.lib_table is not None:
            self.lib_table.reloadData()
        self._update_lib_empty()

    @objc.python_method
    def _update_lib_empty(self):
        if self.lib_empty is None:
            return
        if not self.lib_online:
            msg = "Немає інтернету — бібліотека недоступна.\nЗʼявиться звʼязок — натисни ⟳ оновити."
        elif not self.lib_filtered:
            msg = "Нічого не знайдено."
        else:
            msg = None
        self.lib_empty.setHidden_(msg is None)
        if msg:
            self.lib_empty.setStringValue_(msg)

    @objc.python_method
    def _apply_lib_online_ui(self):
        """Офлайн → гасимо поле пошуку, перемикач джерела і сортування; ⟳ лишаємо як retry."""
        on = bool(self.lib_online)
        for c in (self.lib_search, self.lib_seg, self.lib_sortpop):
            if c is not None:
                try: c.setEnabled_(on)
                except Exception: pass

    @objc.python_method
    def _refresh_library(self, force=False):
        src = self.lib_source
        q = str(self.lib_search.stringValue()) if self.lib_search else ""
        if self.lib_detail is not None:
            self.lib_detail.setStringValue_("Завантаження списку…")
        def work():
            if os.environ.get("LOCALAI_FORCE_OFFLINE"):   # тест-хук: імітація офлайну
                rows, ok = [], False
            elif src == "hf":
                rows, ok = fetch_hf_gguf(q)
            else:
                ids, ok = fetch_ollama_library()
                rows = [{"id": i, "dl": None, "kind": "ollama"} for i in ids]
            def done():
                self.lib_all = rows
                self.lib_online = ok
                self._apply_lib_filter()
                if self.lib_detail is not None:
                    self.lib_detail.setStringValue_(
                        "Подвійний клік — у поле «Завантажити».  HF → hf.co/repo:Q4_K_M")
            AppHelper.callAfter(done)
        threading.Thread(target=work, daemon=True).start()

    def applyModelsDir_(self, sender):
        p = str(self.models_field.stringValue()).strip()
        cfg = load_cfg(); cfg["models_dir"] = p or None; save_cfg(cfg)
        rumps.notification("LocalAI", "Папку моделей збережено",
                           "Перезапусти Ollama, щоб застосувати")
        self.panel._refresh_settings_models()

    @objc.python_method
    def set_pull_status(self, t):
        if self.pull_status is not None:
            self.pull_status.setStringValue_(t)

    @objc.python_method
    def reload_models(self):
        if self.model_pop is None: return
        cur = self.sel_model
        self.model_pop.removeAllItems()
        ms = list_models()
        self.model_pop.addItemsWithTitles_(ms or ["(моделей нема)"])
        pick = cur if cur in ms else pick_chat_model(ms)
        if pick:
            self.model_pop.selectItemWithTitle_(pick)
        self.sel_model = (str(self.model_pop.titleOfSelectedItem()) if ms else None)
        self._update_loaded()
        self._refresh_chat_header()

    @objc.python_method
    def _update_loaded(self):
        if self.loaded_lbl is None: return
        loaded = ps_loaded()
        cur_loaded = ""
        if loaded:
            name = loaded[0].split("  ")[0].strip()
            sz = ram_size(loaded[0])
            cur_loaded = name
            self.loaded_lbl.setStringValue_(f"Зараз у RAM: {name}" + (f"   ·   {sz}" if sz else ""))
        else:
            self.loaded_lbl.setStringValue_("Зараз у RAM: —  (RAM вільна)")
        # «У RAM» горить акцентом лише коли є що вантажити (модель обрана й ще не в RAM);
        # інакше — тухне в дефолт
        if self.load_btn is not None:
            active = bool(self.sel_model) and (self.sel_model != cur_loaded)
            try:
                if active:
                    self.load_btn.setBezelColor_(accent_color())
                else:
                    self.load_btn.setBezelColor_(None)
            except Exception: pass
            self.load_btn.setEnabled_(active)

    # ---------- чат ----------
    @objc.python_method
    def _refresh_chat_header(self):
        if self.chat_model_lbl is not None:
            if not ollama_up():
                self.chat_model_lbl.setStringValue_("Ollama не запущена — увімкни в меню панелі")
            else:
                self.chat_model_lbl.setStringValue_(
                    f"Модель: {self.panel.current_model() or '—'}")

    @objc.python_method
    def _reload_hist(self):
        if self.hist_pop is None: return
        self.hist_pop.removeAllItems()
        self.hist_pop.addItemsWithTitles_([s["title"] for s in self.sessions])
        self.hist_pop.selectItemAtIndex_(self.cur)

    # ── міст у webview: усі виклики маршалимо на головний потік; до завантаження — у чергу ──
    @objc.python_method
    def _js(self, script):
        def run():
            if self.web is None:
                return
            if not self._web_ready:
                self._js_queue.append(script); return
            self.web.evaluateJavaScript_completionHandler_(script, None)
        AppHelper.callAfter(run)

    def webView_didFinishNavigation_(self, web, nav):
        self._web_ready = True
        q, self._js_queue = self._js_queue, []
        for s in q:
            web.evaluateJavaScript_completionHandler_(s, None)
        self._render_session()

    @objc.python_method
    def _reload_web(self):
        if self.web is None:
            return
        self._web_ready = False
        self._js_queue = []
        self.web.loadHTMLString_baseURL_(chat_html(), None)  # didFinish → _render_session

    @objc.python_method
    def _render_session(self):
        if self.web is None:
            return
        self._js("clearAll()")
        h = self.sessions[self.cur]["history"]
        if not h:
            self._js("empty()"); return
        for m in h:
            fn = "addUser" if m["role"] == "user" else "addAI"
            self._js("%s(%s)" % (fn, json.dumps(m["content"])))

    def newChat_(self, sender):
        self.sessions.append({"title": f"Чат {len(self.sessions) + 1}", "history": []})
        self.cur = len(self.sessions) - 1
        self._reload_hist(); self._render_session()

    def clearChat_(self, sender):
        # видалити поточний чат повністю (не просто очистити історію)
        del self.sessions[self.cur]
        if not self.sessions:
            self.sessions.append({"title": "Чат 1", "history": []})
        self.cur = min(self.cur, len(self.sessions) - 1)
        self._reload_hist(); self._render_session()

    def histChanged_(self, sender):
        i = self.hist_pop.indexOfSelectedItem()
        if 0 <= i < len(self.sessions):
            self.cur = i; self._render_session()

    def autospeakToggled_(self, sender):
        self.autospeak_on = bool(sender.state())

    # кнопки в чаті керують ГЛОБАЛЬНИМ TTS (як хоткеї, але без accessibility)
    def pauseSpeechBtn_(self, sender):
        self.panel.pause_speech(None)

    def stopSpeechBtn_(self, sender):
        self.panel.stop_speech(None)

    def stopGen_(self, sender):
        ev = self.gen_cancel
        if ev is not None:
            ev.set()

    def tokenChanged_(self, sender):
        try: n = int(str(sender.titleOfSelectedItem()))
        except Exception: n = 2048
        cfg = load_cfg(); cfg["num_predict"] = n; save_cfg(cfg)

    def textDidChange_(self, note):
        # ховати плейсхолдер коли є текст
        if getattr(self, "chat_ph", None) is not None:
            try: self.chat_ph.setHidden_(len(str(self.chat_input.string())) > 0)
            except Exception: pass

    def textView_doCommandBySelector_(self, tv, sel):
        # Enter → надіслати; Shift+Enter → новий рядок
        if sel == "insertNewline:":
            ev = NSApp.currentEvent()
            if ev is not None and (ev.modifierFlags() & (1 << 17)):  # Shift
                tv.insertNewlineIgnoringFieldEditor_(None)
                return True
            self.sendChat_(tv)
            return True
        return False

    def sendChat_(self, sender):
        txt = str(self.chat_input.string()).strip()
        if not txt: return
        model = self.panel.current_model()
        if not model:
            self._js("note('нема моделі')"); return
        if not ollama_up():
            self._js("note('Ollama не запущена')"); return
        self.chat_input.setString_("")
        if getattr(self, "chat_ph", None) is not None:
            self.chat_ph.setHidden_(False)
        sess = self.sessions[self.cur]
        if not sess["history"]:
            sess["title"] = (txt[:20] + "…") if len(txt) > 20 else txt
            self._reload_hist()
        self._js("addUser(%s)" % json.dumps(txt))
        self._js("aiStart()")
        sess["history"].append({"role": "user", "content": txt})
        self.gen_cancel = threading.Event()
        threading.Thread(target=self._worker, args=(model, sess, self.gen_cancel), daemon=True).start()

    @objc.python_method
    def _worker(self, model, sess, cancel=None):
        try:
            np = int(load_cfg().get("num_predict", 2048))
            payload = json.dumps({"model": model, "messages": sess["history"], "stream": True,
                                  "think": False,
                                  "options": {"num_predict": np, "temperature": 0.6}}).encode()
            req = urllib.request.Request(f"http://{OLLAMA_HOST}/api/chat", payload,
                                         {"Content-Type": "application/json"})
            acc = []; thought = False; stopped = False
            # РЕАЛТАЙМ: озвучуємо речення поки модель пише (Donatello-ефект)
            realtime = self.autospeak_on and tts_mode() == "realtime"
            live_gen = self.panel._live_begin() if realtime else None
            spoken = 0
            with urllib.request.urlopen(req, timeout=300) as r:
                for line in r:
                    if cancel is not None and cancel.is_set():
                        stopped = True; break
                    if not line.strip(): continue
                    d = json.loads(line)
                    if d.get("error"):
                        if realtime: self.panel._live_end(live_gen)
                        self._js("aiEnd()")
                        self._js("note(%s)" % json.dumps(d["error"][:80])); return
                    msg = d.get("message", {})
                    if msg.get("thinking"): thought = True
                    c = msg.get("content", "")
                    if c:
                        acc.append(c)
                        self._js("aiAppend(%s)" % json.dumps(c))
                        if realtime:                   # подати завершені речення в живу озвучку
                            sents, spoken = pop_sentences("".join(acc), spoken)
                            for s in sents:
                                self.panel._live_feed(live_gen, s)
                    if d.get("done"): break
            full = "".join(acc).strip()
            if realtime:                               # дочитати хвіст і закрити живу чергу
                tail = "".join(acc)[spoken:].strip()
                if tail and not stopped: self.panel._live_feed(live_gen, tail)
                self.panel._live_end(live_gen)
            if stopped:
                if full: sess["history"].append({"role": "assistant", "content": full})
                self._js("aiEnd()")
                self._js("note('зупинено')")
                return
            if not full:
                hint = ("порожньо — модель лише «думає». Обери у вкладці «Моделі» "
                        "gemma3:4b або instruct-2507") if thought else "порожня відповідь"
                self._js("aiAppend(%s)" % json.dumps(hint))
                self._js("aiEnd()")
                return
            sess["history"].append({"role": "assistant", "content": full})
            self._js("aiEnd()")
            if self.autospeak_on and not realtime:     # base/stream — озвучити по завершенні
                AppHelper.callAfter(lambda: self.panel._speak(full))
        except Exception as e:
            self._js("aiEnd()")
            self._js("note(%s)" % json.dumps("помилка: " + str(e)[:80]))

    @objc.python_method
    def _append(self, s, bold=False, color=None):
        tv = self.chat_view
        if tv is None: return
        font = NSFont.boldSystemFontOfSize_(13.0) if bold else NSFont.systemFontOfSize_(13.0)
        attrs = {NSFontAttributeName: font,
                 NSForegroundColorAttributeName: color or NSColor.labelColor()}
        self._append_attr(s, attrs)

    @objc.python_method
    def _append_attr(self, s, attrs):
        tv = self.chat_view
        if tv is None: return
        st = tv.textStorage()
        st.beginEditing()
        st.appendAttributedString_(NSAttributedString.alloc().initWithString_attributes_(s, attrs))
        st.endEditing()
        tv.scrollRangeToVisible_(NSMakeRange(st.length(), 0))

    # ── месенджер-бульбашки: користувач справа (акцент), AI зліва (нейтрально) ──
    @objc.python_method
    def _bubble_attrs(self, role):
        ps = NSMutableParagraphStyle.alloc().init()
        ps.setLineSpacing_(2.0)
        ps.setParagraphSpacing_(8.0)
        ps.setParagraphSpacingBefore_(2.0)
        if role == "user":
            ps.setAlignment_(1)            # right
            ps.setHeadIndent_(90.0); ps.setFirstLineHeadIndent_(90.0); ps.setTailIndent_(-6.0)
            bg = accent_color().colorWithAlphaComponent_(0.16)
        else:
            ps.setAlignment_(0)            # left
            ps.setHeadIndent_(6.0); ps.setFirstLineHeadIndent_(6.0); ps.setTailIndent_(-90.0)
            bg = NSColor.secondaryLabelColor().colorWithAlphaComponent_(0.10)
        return {NSFontAttributeName: NSFont.systemFontOfSize_(13.0),
                NSForegroundColorAttributeName: NSColor.labelColor(),
                NSParagraphStyleAttributeName: ps,
                NSBackgroundColorAttributeName: bg}

    @objc.python_method
    def _bubble(self, role, text):
        self._append_attr("  " + text.strip() + "  \n\n", self._bubble_attrs(role))

    @objc.python_method
    def refresh(self, up=None):
        if self.win is None:
            return
        hk = load_cfg().get("hotkeys", DEFAULT_HOTKEYS)
        rec = self.panel.hotkeys.recording
        for act, fld in self.hk_btns.items():
            fld.setStringValue_("натисни…" if rec == act else fmt_hotkey(hk.get(act)))
        # стан Ollama міг змінитись через трей без перевідкриття вікна → підхопити моделі/хедер
        if up is None:
            up = ollama_up()
        if up != self._last_up:
            self._last_up = up
            self.reload_models()       # перемалює список + хедер під новий стан
        self._update_loaded()


class Panel(rumps.App):
    def __init__(self):
        super().__init__("AI", quit_button=None)
        try:
            NSApplication.sharedApplication().setActivationPolicy_(1)  # accessory (без док-іконки)
        except Exception: pass
        # назва+іконка для Dock (коли вікно відкрите стаємо Foreground)
        try:
            NSProcessInfo.processInfo().setProcessName_("LocalAI")
        except Exception: pass
        try:
            ic = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
            img = NSImage.alloc().initWithContentsOfFile_(ic)
            if img is not None:
                NSApp.setApplicationIconImage_(img)
        except Exception: pass
        try:
            from ApplicationServices import AXIsProcessTrustedWithOptions
            AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": True})
        except Exception: pass
        cfg = load_cfg()
        try: apply_theme(cfg.get("theme", "Авто"))
        except Exception: pass
        if "hotkeys" not in cfg:
            cfg["hotkeys"] = DEFAULT_HOTKEYS; save_cfg(cfg)
        self.voice = cfg.get("voice") if cfg.get("voice") in VOICES else VOICES[0]
        try: self.speed = max(0.7, min(1.3, float(cfg.get("speed", 1.0))))
        except Exception: self.speed = 1.0
        try: self.pause = max(0.0, min(0.6, float(cfg.get("pause", 0.15))))
        except Exception: self.pause = 0.15
        self._snd = None
        self._speak_gen = 0
        self._state = "idle"
        self._live = None
        self._tts_starting = False
        self._settings = None
        self._chat = None
        self.menu = [
            "mem_line",
            rumps.MenuItem("Модель у RAM:"), "loaded_line", None,
            rumps.MenuItem("— Озвучення —"),
            "speak_sel", "speak_clip", "tts_pause", "tts_stop", None,
            rumps.MenuItem("— Сервіси —"),
            "ollama_toggle", "unload_models", "tts_toggle", None,
            "chat_open", "settings", None,
            "quit",
        ]
        self.menu["unload_models"].title = "↳ Вивантажити LLM з RAM"
        self.menu["speak_clip"].title = "Озвучити буфер обміну"
        self.menu["speak_sel"].title = "Озвучити виділене"
        self.menu["tts_pause"].title = "Пауза / продовжити"
        self.menu["tts_stop"].title = "Стоп озвучку"
        self.menu["chat_open"].title = "Міні-чат…"
        self.menu["settings"].title = "Налаштування…"
        self.menu["quit"].title = "Вийти"
        self.menu["ollama_toggle"].set_callback(self.toggle_ollama)
        self.menu["unload_models"].set_callback(self.unload_models)
        self.menu["tts_toggle"].set_callback(self.toggle_tts)
        self.menu["speak_clip"].set_callback(self.speak_clipboard)
        self.menu["speak_sel"].set_callback(self.speak_selection)
        self.menu["tts_pause"].set_callback(self.pause_speech)
        self.menu["tts_stop"].set_callback(self.stop_speech)
        self.menu["chat_open"].set_callback(self.open_chat)
        self.menu["settings"].set_callback(self.open_settings)
        self.menu["quit"].set_callback(self.quit_all)
        self.hotkeys = Hotkeys(self); self.hotkeys.start()
        self.timer = rumps.Timer(self.refresh, 1); self.timer.start()
        self._apply_autostart(cfg)

    def _apply_autostart(self, cfg):
        # Лише за явним opt-in у Налаштуваннях; запуск при ВІДКРИТТІ панелі, НЕ системний демон.
        try:
            if cfg.get("autostart_ollama") and not ollama_up():
                subprocess.Popen(["bash", START_OLLAMA])
            if cfg.get("autostart_tts") and not tts_up():
                self._start_tts_server()
        except Exception:
            pass

    # --- керування моделями (UI у вікні «Налаштування → Моделі») ---
    def _refresh_settings_models(self):
        if self._settings is not None:
            try: self._settings.reload_models()
            except Exception: pass

    def load_model(self, name):
        if not name: return
        if not ollama_up():
            rumps.notification("Ollama", "Спершу запусти Ollama", ""); return
        def run():
            try:
                urllib.request.urlopen(urllib.request.Request(
                    f"http://{OLLAMA_HOST}/api/generate",
                    json.dumps({"model": name, "prompt": "", "keep_alive": "30m"}).encode(),
                    {"Content-Type": "application/json"}), timeout=120).read()
            except Exception: pass
            AppHelper.callAfter(self._refresh_settings_models)
        threading.Thread(target=run, daemon=True).start()

    def unload_one(self, name):
        if not name: return
        sh(f"{OLLAMA} stop {shlex.quote(name)}")
        self._refresh_settings_models()

    def delete_model(self, name):
        if not name: return
        if rumps.alert(title="Видалити модель з диска?",
                       message=f"{name}\n\nФайли буде стерто безповоротно.",
                       ok="Видалити", cancel="Скасувати") != 1:
            return
        out = sh(f"{OLLAMA} rm {shlex.quote(name)}")
        if out.startswith("ERR") or "error" in out.lower():
            rumps.notification("Ollama", "Не вдалось видалити", out[:120])
        else:
            rumps.notification("Ollama", "Видалено", name)
        self._refresh_settings_models()

    def start_pull(self, name):
        name = (name or "").strip()
        if not name: return
        if not ollama_up():
            rumps.notification("Ollama", "Спершу запусти Ollama", ""); return
        threading.Thread(target=self._do_pull, args=(name,), daemon=True).start()

    def _do_pull(self, name):
        short = name.split("/")[-1].split(":")[0][:40]   # коротка назва для табла
        def status(t):
            AppHelper.callAfter(lambda: self._settings and self._settings.set_pull_status(t))
        def bar(pct):                                    # pct: 0..100 або None=сховати
            def go():
                s = self._settings
                if s is None or getattr(s, "pull_bar", None) is None: return
                if pct is None:
                    s.pull_bar.setHidden_(True)
                else:
                    s.pull_bar.setHidden_(False); s.pull_bar.setDoubleValue_(float(pct))
            AppHelper.callAfter(go)
        status(f"Завантаження {short}…"); bar(0)
        try:
            payload = json.dumps({"model": name, "stream": True}).encode()
            req = urllib.request.Request(f"http://{OLLAMA_HOST}/api/pull", payload,
                                         {"Content-Type": "application/json"})
            last = -100
            with urllib.request.urlopen(req, timeout=7200) as resp:
                for line in resp:
                    if not line.strip(): continue
                    d = json.loads(line)
                    if d.get("error"):
                        status("Помилка: " + d["error"][:80]); bar(None); return
                    tot, comp = d.get("total"), d.get("completed")
                    if tot and comp:
                        pct = int(comp * 100 / tot)
                        if pct >= last + 2:
                            last = pct; status(f"{short}: {pct}%"); bar(pct)
            status(f"Готово: {short}"); bar(None)
            rumps.notification("Ollama", "Завантажено", name)
            AppHelper.callAfter(self._refresh_settings_models)
        except Exception as e:
            status("Помилка: " + str(e)[:80]); bar(None)

    def open_settings(self, _):
        if self._settings is None:
            self._settings = SettingsWindow.alloc().initWithPanel_(self)
        self._settings.show()

    def open_chat(self, _):
        if self._settings is None:
            self._settings = SettingsWindow.alloc().initWithPanel_(self)
        self._settings.show()
        self._settings.select_tab(3)

    def current_model(self):
        m = self._settings.sel_model if self._settings is not None else None
        return m or pick_chat_model(list_models())

    def _update_activation(self):
        vis = ((self._settings is not None and self._settings.is_open)
               or (self._chat is not None and self._chat.is_open))
        try: NSApp.setActivationPolicy_(0 if vis else 1)  # Dock коли є вікно, інакше трей
        except Exception: pass

    def _set_icon(self, up, tts):
        try:
            if self._state == "synth":     name, tint = "hourglass", True
            elif self._state == "playing": name, tint = "waveform", True
            elif self._state == "paused":  name, tint = "pause.fill", True
            else:
                name = "cpu.fill" if up else "cpu"
                tint = tts
            btn = self._nsapp.nsstatusitem.button()
            img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, "LocalAI")
            if not img:
                return
            if tint:
                c = NSImageSymbolConfiguration.configurationWithHierarchicalColor_(NSColor.systemOrangeColor())
                img = img.imageWithSymbolConfiguration_(c) or img
                img.setTemplate_(False)
            else:
                img.setTemplate_(True)
            btn.setImage_(img); self.title = ""
        except Exception: pass

    def refresh(self, _):
        up = ollama_up(); free, swap = mem(); tts = tts_up()
        if self._tts_starting and tts: self._tts_starting = False
        if self._state == "playing" and self._snd is not None and not self._snd.isPlaying():
            self._state = "idle"; self._snd = None
        self._set_icon(up, tts)
        hk = load_cfg().get("hotkeys", {})
        def _ch(act):
            c = fmt_hotkey(hk.get(act)); return "" if c == "—" else c
        try: sw = float(swap)
        except Exception: sw = 0.0
        warn = "  ⚠" if sw > 3000 else ""
        self.menu["mem_line"].title = f"RAM вільно {free}% · swap {swap}M{warn}"
        set_menu_title(self.menu["speak_sel"], "Озвучити виділене", _ch("speak_sel"))
        set_menu_title(self.menu["speak_clip"], "Озвучити буфер обміну", _ch("speak_clip"))
        set_menu_title(self.menu["tts_stop"], "Стоп озвучку", _ch("tts_stop"))
        self.menu["ollama_toggle"].title = "■ Зупинити Ollama" if up else "▶ Запустити Ollama"
        if self._tts_starting:
            self.menu["tts_toggle"].title = "⏳ Голос запускається…"
        else:
            self.menu["tts_toggle"].title = "■ Зупинити голос (TTS)" if tts else "▶ Запустити голос (TTS)"
        loaded = ps_loaded()
        if loaded:
            nm = loaded[0].split("  ")[0].strip(); sz = ram_size(loaded[0])
            self.menu["loaded_line"].title = "   " + nm + (f"  ·  {sz}" if sz else "")
        else:
            self.menu["loaded_line"].title = "   (нічого — RAM вільна)"
        if self._state == "synth":   p = "⏳ Синтез…"
        elif self._state == "playing": p = "❚❚ Пауза"
        elif self._state == "paused":  p = "▶ Продовжити"
        else: p = "Пауза / продовжити"
        set_menu_title(self.menu["tts_pause"], p, _ch("tts_pause"))
        active = self._state in ("synth", "playing", "paused")
        self.menu["tts_stop"].set_callback(self.stop_speech if active else None)
        self.menu["tts_pause"].set_callback(
            self.pause_speech if self._state in ("playing", "paused") else None)
        self.menu["unload_models"].set_callback(self.unload_models if loaded else None)
        if self._settings is not None:
            self._settings.refresh(up)

    # --- Ollama ---
    def toggle_ollama(self, _):
        if ollama_up(): sh("pkill -f 'ollama serve'"); rumps.notification("Ollama", "Зупинено", "")
        else: subprocess.Popen(["bash", START_OLLAMA]); rumps.notification("Ollama", "Запуск…", "")

    def unload_models(self, _):
        for r in ps_loaded(): sh(f"{OLLAMA} stop {r.split()[0]}")
        rumps.notification("Ollama", "Моделі вивантажено з RAM", "сервер далі працює")

    # --- TTS сервер ---
    def toggle_tts(self, _):
        if tts_up():
            sh(f"kill $(lsof -ti :{TTS_PORT})")
            self._tts_starting = False
            rumps.notification("TTS", "Сервер зупинено", "")
        else:
            self._start_tts_server()
            rumps.notification("TTS", "Сервер запускається…", "перша загрузка ~20с (torch+модель)")

    def _start_tts_server(self):
        self._tts_starting = True
        subprocess.Popen(["bash", f"{TTS_DIR}/start-tts.sh"], start_new_session=True)

    def _wait_tts(self, secs=40):
        if tts_up(): return True
        if not self._tts_starting: self._start_tts_server()
        for _ in range(secs):
            if tts_up(): return True
            time.sleep(1)
        return False

    # --- Озвучення (нативний NSSound: справжня пауза/продовження) ---
    def _synth_sound(self, ch, gen):
        """Один шматок → NSSound (POST у TTS-сервер). None якщо скасовано/збій."""
        if gen != self._speak_gen: return None
        ch = strip_emoji(ch)                      # емоджі StyleTTS2 не озвучує — чистимо
        if not ch: return None                    # шматок був лише з емоджі
        payload = json.dumps({"model": "styletts2-ua", "input": ch,
                              "voice": self.voice,
                              "speed": getattr(self, "speed", 1.0),
                              "pause": getattr(self, "pause", 0.15)}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{TTS_PORT}/v1/audio/speech",
                                     payload, {"Content-Type": "application/json"})
        audio = urllib.request.urlopen(req, timeout=120).read()
        if gen != self._speak_gen: return None
        f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False); f.write(audio); f.close()
        snd = NSSound.alloc().initWithContentsOfFile_byReference_(f.name, True)
        if snd is not None:
            try: snd.setPlaybackDeviceIdentifier_(None)
            except Exception: pass
        return snd

    def _play_sound(self, snd, gen):
        """Програти й дочекатися кінця, поважаючи паузу/стоп. False = скасовано."""
        if gen != self._speak_gen: return False
        self._snd = snd; self._state = "playing"; snd.play()
        while True:
            if gen != self._speak_gen:
                try: snd.stop()
                except Exception: pass
                return False
            if self._state == "paused":
                time.sleep(0.1); continue
            if not snd.isPlaying(): break
            time.sleep(0.08)
        return True

    def _speak(self, text):
        text = (text or "").strip()
        if not text: rumps.notification("TTS", "Порожньо", ""); return
        self.stop_speech(None)
        self._speak_gen += 1
        gen = self._speak_gen           # токен скасування: stop інкрементує → синтез не заграє
        self._state = "synth"
        if tts_mode() != "base":                   # stream і realtime → конвеєр для ручного озвучення
            self._speak_stream(text, gen); return
        chunks = split_blocks(text[:6000]) or [text[:700]]
        def run():
            pool = NSAutoreleasePool.alloc().init()
            try:
                if not self._wait_tts():
                    self._state = "idle"; rumps.notification("TTS", "Сервер не піднявся", ""); return
                for ch in chunks:
                    if gen != self._speak_gen: return          # стоп під час черги
                    self._state = "synth"
                    snd = self._synth_sound(ch, gen)
                    if gen != self._speak_gen: return
                    if snd is None:
                        self._state = "idle"; rumps.notification("TTS", "Не зміг відтворити", ""); return
                    if not self._play_sound(snd, gen): return
                self._state = "idle"
            except Exception as ex:
                self._state = "idle"; rumps.notification("TTS", "Помилка", str(ex)[:80])
            finally:
                del pool
        threading.Thread(target=run, daemon=True).start()

    def _speak_stream(self, text, gen):
        """Конвеєр ①: продюсер синтезує наступний шматок у фоні, поки плеєр грає
        поточний → майже миттєвий старт, без дірок між реченнями. База не чіпається."""
        chunks = split_stream(text[:6000]) or [text[:700]]
        _q = __import__("queue")
        q = _q.Queue(maxsize=1)                       # prefetch на 1 шматок наперед
        END = object()                                # маркер кінця (≠ пропущений шматок)

        def _put(item):                               # put, що не висне якщо плеєр скасовано
            while gen == self._speak_gen:
                try: q.put(item, timeout=0.2); return True
                except _q.Full: continue
            return False

        def producer():
            pool = NSAutoreleasePool.alloc().init()
            try:
                for ch in chunks:
                    if gen != self._speak_gen: break
                    try:
                        snd = self._synth_sound(ch, gen)
                    except Exception:
                        snd = None
                    if gen != self._speak_gen: break
                    if snd is not None and not _put(snd):  # пропущені (None) не кладемо
                        break
            finally:
                _put(END); del pool                   # сентинел кінця черги

        def consumer():
            pool = NSAutoreleasePool.alloc().init()
            try:
                if not self._wait_tts():
                    self._state = "idle"; rumps.notification("TTS", "Сервер не піднявся", ""); return
                threading.Thread(target=producer, daemon=True).start()
                first = True
                while True:
                    if gen != self._speak_gen: return
                    try: snd = q.get(timeout=0.2)     # get, що прокидається на скасування
                    except _q.Empty: continue
                    if snd is END: break              # черга вичерпана
                    if gen != self._speak_gen: return
                    if not first:                      # дихалка між шматками (сервер так робить
                        gap = max(0.12, getattr(self, "pause", 0.15))   # всередині POST, а між
                        t_end = time.time() + gap                       # шматками тиші нема)
                        while time.time() < t_end:
                            if gen != self._speak_gen: return
                            time.sleep(0.04)
                    first = False
                    if not self._play_sound(snd, gen): return
                self._state = "idle"
            except Exception as ex:
                self._state = "idle"; rumps.notification("TTS", "Помилка", str(ex)[:80])
            finally:
                del pool
        threading.Thread(target=consumer, daemon=True).start()

    # ── РЕАЛТАЙМ: відкрита черга — годуємо реченнями LLM на льоту (Donatello-ефект) ──
    def _live_begin(self):
        """Старт живої озвучки. Воркер чекає речення в черзі й читає їх по черзі,
        поки LLM ще пише. Повертає gen-токен (передати у feed/end)."""
        self.stop_speech(None)
        self._speak_gen += 1
        gen = self._speak_gen
        self._state = "synth"
        _q = __import__("queue")
        q = _q.Queue()
        END = object()
        self._live = (gen, q, END)

        def worker():
            pool = NSAutoreleasePool.alloc().init()
            first = True
            try:
                if not self._wait_tts():
                    self._state = "idle"; return
                while True:
                    if gen != self._speak_gen: return
                    try: item = q.get(timeout=0.2)
                    except _q.Empty: continue
                    if item is END: break
                    if gen != self._speak_gen: return
                    try: snd = self._synth_sound(item, gen)
                    except Exception: snd = None
                    if snd is None: continue
                    if gen != self._speak_gen: return
                    if not first:                      # дихалка між реченнями
                        gap = max(0.12, getattr(self, "pause", 0.15))
                        t_end = time.time() + gap
                        while time.time() < t_end:
                            if gen != self._speak_gen: return
                            time.sleep(0.04)
                    first = False
                    if not self._play_sound(snd, gen): return
                self._state = "idle"
            except Exception:
                self._state = "idle"
            finally:
                del pool
        threading.Thread(target=worker, daemon=True).start()
        return gen

    def _live_feed(self, gen, sentence):
        live = getattr(self, "_live", None)
        if live and live[0] == gen and gen == self._speak_gen:
            sentence = (sentence or "").strip()
            if sentence: live[1].put(sentence)

    def _live_end(self, gen):
        live = getattr(self, "_live", None)
        if live and live[0] == gen:
            live[1].put(live[2])                       # END-сентинел

    def speak_clipboard(self, _): self._speak(sh("pbpaste"))

    def speak_selection(self, _):
        txt = ax_selection() or selection_via_clipboard()
        self._speak(txt)

    def pause_speech(self, _):
        if self._snd is None: return
        if self._state == "playing":
            if self._snd.pause(): self._state = "paused"
        elif self._state == "paused":
            if self._snd.resume(): self._state = "playing"

    def stop_speech(self, _):
        self._speak_gen += 1            # скасувати будь-який синтез, що ще триває
        if self._snd is not None:
            try: self._snd.stop()
            except Exception: pass
        self._snd = None; self._state = "idle"

    def quit_all(self, _):
        self.stop_speech(None)
        for r in ps_loaded(): sh(f"{OLLAMA} stop {r.split()[0]}")
        sh("pkill -f 'ollama serve'")
        sh(f"kill $(lsof -ti :{TTS_PORT})")
        rumps.quit_application()


if __name__ == "__main__":
    _p = Panel()
    if os.environ.get("LOCALAI_OPEN_SETTINGS"):  # тест-хук: одразу показати Налаштування
        def _open_once(t):
            t.stop(); _p.open_settings(None)
            if os.environ.get("LOCALAI_CHAT_DEMO") and _p._settings:
                s = _p._settings
                s.sessions[0]["history"] = [
                    {"role": "user", "content": "Привіт! Назви три кольори українською."},
                    {"role": "assistant", "content": "Звісно: червоний, зелений та синій."}]
                s._render_session()
        rumps.Timer(_open_once, 1).start()
    _p.run()
