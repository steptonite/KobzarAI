#!/usr/bin/env python3
# KobzarAI — menu-bar керування Ollama + TTS + RAM + глобальні хоткеї. Без автозапуску, ручний СТОП.
import os, subprocess, tempfile, threading, time, urllib.request, json, shlex, re, shutil
import base64, mimetypes
import sys
import rumps
import objc
from AppKit import (NSImage, NSSound, NSWindow, NSBackingStoreBuffered,
    NSWindowStyleMaskTitled, NSWindowStyleMaskClosable, NSWindowStyleMaskResizable,
    NSWindowStyleMaskFullSizeContentView,
    NSMenu, NSMenuItem,
    NSTextField, NSPopUpButton, NSButton, NSView, NSApp, NSColor, NSSlider,
    NSImageSymbolConfiguration, NSApplication, NSWorkspace, NSURL, NSPasteboard, NSScreen, NSClipView,
    NSScrollView, NSTextView, NSFont, NSAttributedString,
    NSMutableAttributedString, NSTextTab, NSRightTextAlignment, NSBox,
    NSVisualEffectView, NSVisualEffectBlendingModeBehindWindow, NSVisualEffectStateActive,
    NSVisualEffectMaterialHUDWindow,
    NSVisualEffectMaterialWindowBackground, NSVisualEffectMaterialUnderWindowBackground,
    NSOpenPanel, NSAppearance, NSMutableParagraphStyle, NSColorSpace,
    NSFontAttributeName, NSForegroundColorAttributeName, NSParagraphStyleAttributeName,
    NSBackgroundColorAttributeName, NSTrackingArea,
    NSTableView, NSTableColumn, NSProgressIndicator, NSSliderCell, NSBezierPath,
    NSAlert, NSStackView, NSSwitch, NSLayoutConstraint,
    NSToolbar, NSToolbarItem, NSWindowToolbarStyleUnified,
    NSUserInterfaceLayoutOrientationVertical, NSUserInterfaceLayoutOrientationHorizontal,
    NSLayoutAttributeLeading, NSLayoutAttributeCenterY)
from Foundation import (NSObject, NSAutoreleasePool, NSMakeRect, NSMakeRange,
    NSMakeSize, NSMakePoint, NSProcessInfo, NSInsetRect, NSTimer)
from AppKit import NSTableRowView, NSViewBoundsDidChangeNotification, NSWindowStyleMaskMiniaturizable
from Foundation import NSNotificationCenter, NSIndexSet
from Quartz import CAGradientLayer, CATransaction
from WebKit import WKWebView, WKWebViewConfiguration
from PyObjCTools import AppHelper
import chatfiles as _cf       # 30.09: картки файлів, перегляд тексту, що бачить модель, drop, відео/звук

# Необов'язкове доповнення: якщо поруч із цим файлом є тека addons/ з модулем kobzar_addon,
# Кобзар питає в нього про додаткові вкладки налаштувань і команди чату. Без модуля нічого не змінюється.
try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "addons"))
    import kobzar_addon as _addon
    if not _addon.available():
        _addon = None
except Exception:
    _addon = None

def _browser_chat_menu():
    """Optional addon owns its tab; no menu entry without an installed browser addon."""
    if _addon is None:
        return []
    try:
        return ["browser_chats"] if any(t.get("key") == "browser" for t in _addon.tabs()) else []
    except Exception:
        return []


# 26.09: автодоповнення команд @/… у чаті — borderless non-activating панель.
try:
    from AppKit import NSPanel, NSWindowStyleMaskNonactivatingPanel, NSFloatingWindowLevel
except Exception:
    NSPanel = objc.lookUpClass("NSPanel")
    NSWindowStyleMaskNonactivatingPanel = 1 << 7
    NSFloatingWindowLevel = 3

# 🔴 22.08.2026, перша чужа установка (Катя, M4). Тут стояло два хардкоди автора,
# і разом вони робили панель мертвою на будь-якій іншій машині:
#   APA = "/Volumes/ExternalSSD"  → моделі шукались на томі, якого в неї нема;
#   OLLAMA = "/opt/homebrew/..."  → на Intel і при нативному Ollama.app бінарника
#                                   за цим шляхом немає, і `ollama list` мовчки порожній.
# setup.sh тим часом чесно ставив Ollama і тягнув bge-m3 у СТАНДАРТНУ ~/.ollama/models.
# Тобто інсталятор і панель не домовлялись між собою — людина бачила «нічого не працює».
# Правило: жоден шлях, унікальний для машини автора, не має права бути дефолтом.

def _find_ollama() -> str:
    """CLI Ollama там, де він реально стоїть. Порожній рядок = не встановлена."""
    env = (os.environ.get("KOBZARAI_OLLAMA_BIN") or "").strip()
    cands = [env] if env else []
    cands.append(shutil.which("ollama") or "")
    cands += ["/opt/homebrew/bin/ollama", "/usr/local/bin/ollama",
              "/Applications/Ollama.app/Contents/Resources/ollama"]
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return ""


OLLAMA_BIN = _find_ollama()
# для команд лишаємо голе ім'я: без бінарника вони мають провалитись чесно,
# а не перетворитись на виклик чужої команди через порожній префікс
OLLAMA = OLLAMA_BIN or "ollama"
DEFAULT_MODELS_DIR = os.path.expanduser("~/.ollama/models")
# Зовнішній диск лишається можливим — але як СВІДОМИЙ вибір людини
# (поле «Папка моделей» у Налаштуваннях або KOBZARAI_DISK), не як дефолт.
DISK = (os.environ.get("KOBZARAI_DISK") or "").strip()


def ollama_blocker():
    """Що саме заважає підняти Ollama: (короткий підпис у меню, пояснення людині).
    None = перешкод нема. Три причини раніше зливались в одну фразу «диск з
    моделями недоступний» — вона брехала тому, у кого ніякого диска й не було."""
    if not OLLAMA_BIN:
        return ("Не стартує: Ollama не встановлена",
                "Панель не знайшла Ollama на цьому Mac.\n\n"
                "Постав її однією з команд:\n"
                "    brew install ollama\n"
                "або завантаж застосунок з ollama.com\n\n"
                "Після встановлення перезапусти KobzarAI.")
    if not os.path.isfile(START_OLLAMA):
        return ("Не стартує: немає лаунчера",
                f"Немає файлу {START_OLLAMA}.\n\n"
                "Його кладе інсталятор. Виконай у теці KobzarAI:\n"
                "    ./setup.sh")
    md = models_dir()
    if not os.path.isdir(md):
        return ("Не стартує: папка моделей недоступна",
                f"Панель шукає моделі тут:\n    {md}\n\n"
                "Такої папки нема. Якщо це зовнішній диск — під'єднай його.\n"
                "Якщо моделі лежать деінде — вкажи шлях у\n"
                "Налаштування → Загальні → Папка моделей.")
    return None


def models_dir():
    """Папка моделей: config.json (UI) → KOBZARAI_DISK → OLLAMA_MODELS → стандартна.

    Якщо заданий шлях недоступний (відпав зовнішній диск), а стандартна папка
    з моделями на місці — беремо її. Інакше панель тихо мертва саме тоді,
    коли причину найважче вгадати."""
    try:
        chosen = (load_cfg().get("models_dir") or "").strip()
    except Exception:
        chosen = ""
    if not chosen and DISK:
        chosen = f"{DISK}/ollama-models"
    if not chosen:
        chosen = (os.environ.get("OLLAMA_MODELS") or "").strip()
    if chosen and os.path.isdir(chosen):
        return chosen
    if chosen and os.path.isdir(os.path.join(DEFAULT_MODELS_DIR, "manifests")):
        return DEFAULT_MODELS_DIR      # заданий шлях відпав, стандартний живий
    return chosen or DEFAULT_MODELS_DIR
START_OLLAMA = os.path.expanduser("~/.ollama/start-ollama.sh")
TTS_DIR = os.path.expanduser("~/.local/styletts2-ua-server")
TTS_PORT = 5050
TTS_MAX_CHARS = 200000          # стеля довжини озвучення (~ глава книги); раніше 6000 мовчки різало великі тексти
TTS_GROUP_CHARS = 200           # таргет довжини спана синтезу на сервері (server: дефолт 20=Cherry); більший = менше стиків, менше рваності
OLLAMA_HOST = "127.0.0.1:11434"
VOICES_FALLBACK = ["Артем Окороков", "Анастасія Павленко", "Денис Денисенко", "filatov"]


def _fetch_voices():
    """Список голосів беремо з СЕРВЕРА, не з константи.

    🔴 ЧОМУ: тут роками стояли захардкожені 4 імені, а сервер віддає 31 —
    решта 27 голосів фізично лежали в `voices/` і були недосяжні з панелі.
    Джерело правди — той, хто ці голоси вміє синтезувати. Статичний список
    лишається лише як фолбек на випадок, коли сервер ще не піднявся."""
    try:
        import json as _json
        import urllib.request as _u
        with _u.urlopen(f"http://127.0.0.1:{TTS_PORT}/voices", timeout=2) as r:
            d = _json.loads(r.read().decode("utf-8"))
        names = list(d.get("multispeaker") or []) + list(d.get("single") or [])
        return names or VOICES_FALLBACK
    except Exception:
        return VOICES_FALLBACK


VOICES = _fetch_voices()


def refresh_voices():
    """Перечитати список із сервера перед показом вибору.

    ЧОМУ не досить разового читання на старті: панель САМА піднімає TTS-сервер,
    тож на момент імпорту його ще нема → лишився б фолбек із 4 імен, і людина
    знову не побачила б решту. Тому список оновлюється щоразу, коли його
    показують; коштує це один локальний GET."""
    global VOICES
    fresh = _fetch_voices()
    if fresh and fresh != VOICES:
        VOICES = fresh
    return VOICES
VOICE_LABELS = {"filatov": "Filatov"}          # серверні ключі lowercase → людський підпис
def voice_label(v): return VOICE_LABELS.get(v, v)
CONFIG = os.path.expanduser("~/.local/kobzarai/config.json")

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
# side-aware модифікатори: токени lcmd/rcmd/... зберігають ФІЗИЧНУ сторону (ліва/права).
# _MOD_BASE зводить їх до бази для порядку/символу; _MOD_SIDE — маркер сторони у показі.
_MOD_BASE = {"lctrl": "ctrl", "rctrl": "ctrl", "lalt": "alt", "ralt": "alt",
             "lshift": "shift", "rshift": "shift", "lcmd": "cmd", "rcmd": "cmd"}
_MOD_SIDE = {"l": "ᴸ", "r": "ᴿ"}
_KC2CHAR = {0:"A",1:"S",2:"D",3:"F",4:"H",5:"G",6:"Z",7:"X",8:"C",9:"V",11:"B",12:"Q",
    13:"W",14:"E",15:"R",16:"Y",17:"T",18:"1",19:"2",20:"3",21:"4",22:"6",23:"5",24:"=",
    25:"9",26:"7",27:"-",28:"8",29:"0",30:"]",31:"O",32:"U",33:"[",34:"I",35:"P",37:"L",
    38:"J",39:"'",40:"K",41:";",42:"\\",43:",",44:"/",45:"N",46:"M",47:".",49:"Space",
    50:"`",36:"Return",48:"Tab",122:"F1",120:"F2",99:"F3",118:"F4",96:"F5",97:"F6"}


def fmt_hotkey(v):
    if not v:
        return "—"
    mods = v.get("mods", [])
    bybase = {}                              # база → конкретний токен (sided чи ні)
    for m in mods:
        bybase[_MOD_BASE.get(m, m)] = m
    s = ""
    side = None
    for base in _MOD_ORDER:
        if base in bybase:
            tok = bybase[base]
            sym = _MOD_SYM[base]
            if tok != base:                  # sided токен (lcmd/rcmd…)
                cur_side = _MOD_SIDE.get(tok[0], "")
                if side is None:
                    side = cur_side
                elif side != cur_side:
                    side = "mixed"
            s += sym
    if side and side != "mixed":
        s += side
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


_cfg_lock = threading.Lock()


def save_cfg(d):
    # Атомарно (tmp → os.replace) і під локом: конфіг пишуть і головний потік,
    # і потік хоткей-тапа — прямий open("w") давав шанс обірваного/змішаного файлу,
    # який load_cfg мовчки читав як {} → «настройки злетіли».
    try:
        with _cfg_lock:
            tmp = CONFIG + ".tmp"
            with open(tmp, "w") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
            os.replace(tmp, CONFIG)
    except Exception:
        pass


# ── збереження чатів: локально, по файлу на чат (відкривається у Finder) ──
DEFAULT_CHATS_DIR = os.path.expanduser("~/Documents/KobzarAI/Чати")


def chats_dir():
    """Тека де лежать чати (UI-налаштування, інакше дефолт у Документах)."""
    try:
        return load_cfg().get("chats_dir") or DEFAULT_CHATS_DIR
    except Exception:
        return DEFAULT_CHATS_DIR


def _safe_name(s):
    s = re.sub(r'[/\\:\n\r\t]+', '_', str(s)).strip()
    return (s or "chat")[:60]


def load_chats():
    """Підняти всі чати з теки (відсортовані за часом, новіші зверху)."""
    d = chats_dir(); out = []
    try:
        files = [f for f in os.listdir(d) if f.endswith(".json")]
    except Exception:
        return out
    for f in files:
        try:
            with open(os.path.join(d, f)) as fp:
                j = json.load(fp)
            if isinstance(j, dict) and isinstance(j.get("history"), list):
                j.setdefault("title", "Чат")
                j.setdefault("ts", os.path.getmtime(os.path.join(d, f)))
                j.setdefault("id", str(int(j["ts"] * 1000)))   # стабільна ідентичність рядка
                j["_file"] = f
                out.append(j)
        except Exception:
            pass
    out.sort(key=lambda s: s.get("ts", 0), reverse=True)
    return out


def save_chat(sess):
    """Записати один чат у його файл (створює теку за потреби)."""
    d = chats_dir()
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        return
    if not sess.get("id"):
        sess["id"] = str(int(time.time() * 1000))
    fname = sess.get("_file") or ("%s-%s.json" % (sess["id"], _safe_name(sess.get("title", ""))))
    sess["_file"] = fname
    try:
        with open(os.path.join(d, fname), "w") as fp:
            json.dump({"id": sess["id"], "title": sess.get("title", ""),
                       "ts": sess.get("ts", time.time()),
                       "history": sess.get("history", [])},
                      fp, ensure_ascii=False, indent=2)
    except Exception:
        pass


def delete_chat_file(sess):
    f = sess.get("_file")
    if not f:
        return
    try:
        os.remove(os.path.join(chats_dir(), f))
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


# ── авто-вивантаження TTS з RAM по простою (оптимізація для 8 ГБ) ──
TTS_IDLE_LABELS = ["Ніколи", "2 хв", "5 хв", "10 хв", "30 хв"]
TTS_IDLE_MIN    = [0, 2, 5, 10, 30]


_AUDIO_OUT_CACHE = None

def audio_outputs():
    """Список (назва, UID) пристроїв ВИВОДУ через CoreAudio (ctypes, детерміновано).
    UID годиться напряму для NSSound.setPlaybackDeviceIdentifier_. [] якщо збій."""
    global _AUDIO_OUT_CACHE
    if _AUDIO_OUT_CACHE is not None:
        return _AUDIO_OUT_CACHE
    res = []
    try:
        import ctypes, ctypes.util, struct
        ca = ctypes.CDLL(ctypes.util.find_library("CoreAudio"))
        cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
        fcc = lambda s: struct.unpack(">I", s.encode())[0]
        class AOPA(ctypes.Structure):
            _fields_ = [("s", ctypes.c_uint32), ("sc", ctypes.c_uint32), ("e", ctypes.c_uint32)]
        SYS = 1; GLOB = fcc('glob'); OUT = fcc('outp')
        cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
        def cfstr(ref):
            if not ref: return None
            buf = ctypes.create_string_buffer(512)
            if cf.CFStringGetCString(ref, buf, 512, 0x08000100):
                return buf.value.decode("utf-8", "replace")
            return None
        A = lambda sel, sc=GLOB: AOPA(fcc(sel), sc, 0)
        sz = ctypes.c_uint32(0)
        ca.AudioObjectGetPropertyDataSize(SYS, ctypes.byref(A('dev#')), 0, None, ctypes.byref(sz))
        n = sz.value // 4
        arr = (ctypes.c_uint32 * n)()
        ca.AudioObjectGetPropertyData(SYS, ctypes.byref(A('dev#')), 0, None, ctypes.byref(sz), arr)
        for did in arr:
            s2 = ctypes.c_uint32(0)
            ca.AudioObjectGetPropertyDataSize(did, ctypes.byref(A('stm#', OUT)), 0, None, ctypes.byref(s2))
            if not s2.value:                                  # без output-стрімів → не пристрій виводу
                continue
            nref = ctypes.c_void_p(0); us = ctypes.c_uint32(8)
            ca.AudioObjectGetPropertyData(did, ctypes.byref(A('lnam', OUT)), 0, None, ctypes.byref(us), ctypes.byref(nref))
            uref = ctypes.c_void_p(0); us2 = ctypes.c_uint32(8)
            ca.AudioObjectGetPropertyData(did, ctypes.byref(A('uid ', OUT)), 0, None, ctypes.byref(us2), ctypes.byref(uref))
            nm, uid = cfstr(nref), cfstr(uref)
            if nm and uid:
                res.append((nm, uid))
    except Exception:
        res = []
    _AUDIO_OUT_CACHE = res
    return res


def tts_idle_min():
    """Хвилин простою до вивантаження TTS-сервера з RAM. 0 = ніколи (тримати завжди)."""
    try:
        m = int(load_cfg().get("tts_idle_min", 0) or 0)
    except Exception:
        return 0
    return m if m in TTS_IDLE_MIN else 0


def tts_idle_index():
    m = tts_idle_min()
    return TTS_IDLE_MIN.index(m) if m in TTS_IDLE_MIN else 0


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
    # timeout=2 давав хибні «впав»: під swap синтез на single-Flask тримає потік і
    # /health не встигав за 2с → watchdog піднімав 2-й сервер. 4с — запас на лаг.
    try: urllib.request.urlopen(f"http://127.0.0.1:{TTS_PORT}/health", timeout=4); return True
    except Exception: return False


def notify(title, subtitle="", message=""):
    return   # ПУШІ ВИМКНЕНО (рішення користувача): жодних системних сповіщень
    """Системне сповіщення через osascript. Чому не інакше:
    • rumps.notification спирається на стару NSUserNotification, яку на macOS 26 прибрано;
    • нативний UNUserNotificationCenter віддає UNErrorDomain Code=1 (not-allowed), бо апка
      підписана ad-hoc і збирається вручну — система не авторизує її як клієнта сповіщень.
    osascript 'display notification' доставляється завжди (іде під «Редактор скриптів»)."""
    def esc(s): return str(s).replace("\\", "\\\\").replace('"', '\\"')
    scr = f'display notification "{esc(message)}" with title "{esc(title)}"'
    if subtitle: scr += f' subtitle "{esc(subtitle)}"'
    try: subprocess.Popen(["osascript", "-e", scr])
    except Exception: pass


# ПУШІ ВИМКНЕНО глобально — rumps.notification теж глушимо (нічого не показуємо)
rumps.notification = lambda *a, **k: None


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


# 26.09: таймер панелі тікає щосекунди, і за один тік `ollama ps` питали тричі (меню, слоти RAM,
# шапка чату), а шапка ще й `ollama list` — кожен виклик = новий процес і пара HTTP-запитів,
# ~380 запитів/хв до Ollama. Таймерні шляхи беруть свіже не старше max_age; дії (load/unload)
# кличуть без max_age і заразом оновлюють кеш.
_PS_CACHE = [0.0, []]
_LS_CACHE = [0.0, []]


def ps_loaded(max_age=0):
    now = time.time()
    if max_age and now - _PS_CACHE[0] < max_age:
        return list(_PS_CACHE[1])
    out = sh(f"{OLLAMA} ps 2>/dev/null")
    rows = [l for l in out.splitlines()[1:] if l.strip()]
    _PS_CACHE[:] = [now, rows]
    return rows


def ram_size(line):
    """Розмір моделі в RAM з рядка `ollama ps` (напр. '3.3 GB')."""
    m = re.search(r"(\d+(?:[.,]\d+)?\s?[GM]B)", line or "")
    return m.group(1) if m else ""


# TTS_ACTIVE_PEAK_GB — виміряно vmmap 01.07.2026: реальний Physical Footprint (не ps/RSS,
# той GPU/Metal-памʼять не бачить) під час серії активних синтезів на CPU StyleTTS2
# стабілізується на цій стелі. RAM_SAFETY_MARGIN_GB — запас під macOS+фонові апки
# (Claude/браузер/Telegram і т.п.), емпірично з живих спостережень тиску на 8ГБ.
TTS_ACTIVE_PEAK_GB = 4.0
RAM_SAFETY_MARGIN_GB = 2.0


def total_ram_gb():
    try: return int(sh("sysctl -n hw.memsize 2>/dev/null")) / (1024 ** 3)
    except Exception: return 8.0   # безпечний дефолт для цього класу машин


def _size_to_gb(sz):
    m = re.match(r"([\d.,]+)\s?([GM])B", sz or "")
    if not m: return 0.0
    n = float(m.group(1).replace(",", "."))
    return n if m.group(2) == "G" else n / 1024.0


def realtime_ram_risk():
    """Текст попередження якщо режим «Наживо» (Ollama генерує + TTS озвучує ОДНОЧАСНО)
    ймовірно не влізе в RAM без важкого свопу, або None якщо все ок / модель не завантажена."""
    model_gb = sum(_size_to_gb(ram_size(l)) for l in ps_loaded())
    if model_gb <= 0:
        return None                 # нема завантаженої моделі зараз — нема чого рахувати
    need = model_gb + TTS_ACTIVE_PEAK_GB + RAM_SAFETY_MARGIN_GB
    total = total_ram_gb()
    if need <= total:
        return None
    return (f"Тісно з RAM: модель ~{model_gb:.1f} ГБ + жива озвучка ~{TTS_ACTIVE_PEAK_GB:.0f} ГБ "
            f"на {total:.0f} ГБ разом — може гальмувати. Спробуй меншу модель або режим «Швидко».")


def list_models(max_age=0):
    now = time.time()
    if max_age and now - _LS_CACHE[0] < max_age:
        return list(_LS_CACHE[1])
    out = sh(f"{OLLAMA} list 2>/dev/null")
    rows = [l.split()[0] for l in out.splitlines()[1:] if l.strip()]
    _LS_CACHE[:] = [now, rows]
    return rows


def model_size(name):
    """Розмір моделі на диску з `ollama list` (напр. «4.1 GB»). Порожньо якщо нема."""
    if not name or name.startswith("("):
        return ""
    try:
        out = sh(f"{OLLAMA} list 2>/dev/null")
        for l in out.splitlines()[1:]:
            p = l.split()
            if p and p[0] == name and len(p) >= 4:
                return ("%s %s" % (p[2], p[3])).replace("GB", "ГБ").replace("MB", "МБ")
    except Exception:
        pass
    return ""


def human_model_label(name):
    """Людське слово поруч із кодом моделі (26.09) — «bge-m3», «gemma3:1b» нічого
    не кажуть людині, яка не вбирала номенклатуру Ollama. Порожньо, якщо сімейство
    невідоме — нічого не домальовуємо, ніж вигадувати."""
    n = (name or "").lower()
    if any(k in n for k in ("llava", "vl", "vision")):
        return "розуміє картинки"
    if any(k in n for k in ("bge", "nomic", "embed")):
        return "пошук по бібліотеці"
    if any(k in n for k in ("gemma", "qwen", "llama", "mistral")):
        return "локальна модель для чату"
    return ""


# Системний промт бази знань (30.09): фрагменти — особисті нотатки; брати лише дотичне.
KB_PREAMBLE = ("Нижче — фрагменти з особистих нотаток користувача (його база знань). "
               "Використовуй їх лише тоді, коли вони справді стосуються запитання. "
               "Коли спираєшся на фрагмент, назви джерело в квадратних дужках, наприклад [назва_файлу.md]. "
               "Якщо фрагменти не по темі — не згадуй їх, відповідай звичайно зі своїх загальних знань "
               "і не вдавай, що знайшов щось у нотатках. Відповідай тією мовою, якою написав користувач.\n\n"
               "=== НОТАТКИ ===\n")
KB_CHARS_PER_TOKEN = 2.5     # обережна оцінка для кирилиці: скільки символів у токені

# Вкладення чату (30.09): копія в ~/Documents/KobzarAI/Вкладення/<дата>/, мініатюра для картинок.
_ATT_IMG = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".tif", ".tiff")
_ATT_VID = (".mp4", ".mov", ".webm", ".m4v")
_THUMBS = {}


def att_root():
    return os.path.join(os.path.expanduser("~/Documents/KobzarAI/Вкладення"), time.strftime("%Y-%m-%d"))


def att_kind(path):
    return _cf.kind_of(path)          # img/vid/aud/md/txt/csv/json/code/pdf/doc/sheet/slides/zip/file


def att_store(src, name=None):
    """Копіює файл у теку вкладень (APFS-клон, без місця й часу), імʼя не перезаписує чуже."""
    root = att_root(); os.makedirs(root, exist_ok=True)
    name = re.sub(r"[/\\:\x00-\x1f]", "_", name or os.path.basename(src)).strip(". ") or "файл"
    base, ext = os.path.splitext(name); dst = os.path.join(root, name); n = 1
    while os.path.exists(dst):
        n += 1; dst = os.path.join(root, "%s %d%s" % (base, n, ext))
    if subprocess.run(["cp", "-c", src, dst], capture_output=True).returncode != 0:
        shutil.copy2(src, dst)
    return dst


def att_thumb(path, px=200):
    """Мініатюра-JPEG у data-URL (ImageIO, без читання всієї картинки в памʼять). "" якщо не вийшло."""
    try:
        key = (path, os.path.getmtime(path))
        if key in _THUMBS: return _THUMBS[key]
        import Quartz as Q
        src = Q.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(path), None)
        img = Q.CGImageSourceCreateThumbnailAtIndex(src, 0, {
            Q.kCGImageSourceCreateThumbnailFromImageAlways: True,
            Q.kCGImageSourceCreateThumbnailWithTransform: True,
            Q.kCGImageSourceThumbnailMaxPixelSize: px}) if src else None
        if img is None: return ""
        from Foundation import NSMutableData
        buf = NSMutableData.data()
        dst = Q.CGImageDestinationCreateWithData(buf, "public.jpeg", 1, None)
        Q.CGImageDestinationAddImage(dst, img, {Q.kCGImageDestinationLossyCompressionQuality: 0.8})
        Q.CGImageDestinationFinalize(dst)
        out = "data:image/jpeg;base64," + base64.b64encode(bytes(buf)).decode()
        if len(_THUMBS) > 200: _THUMBS.clear()
        _THUMBS[key] = out
        return out
    except Exception:
        return ""


def att_view(a):
    """Запис історії {name,path,kind} → те, що малює сторінка (мініатюра щоразу з файлу; gone, якщо файл зник)."""
    p = a.get("path", "")
    v = _cf.card_info(p, a.get("name"))     # імʼя, тип, розмір, «можна переглянути», адреса програвача
    if v["kind"] == "img" and not v["gone"]:
        v["thumb"] = att_thumb(p)
    return v


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
            headers={"User-Agent": "KobzarAI-panel"})
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
    return f"{g:.1f} ГБ" if g >= 1 else f"{nbytes / 1e6:.0f} МБ"


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
            "User-Agent": "KobzarAI-panel"})
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
        req = urllib.request.Request(url, headers={"User-Agent": "KobzarAI-panel"})
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
        req = urllib.request.Request(url, headers={"User-Agent": "KobzarAI-panel"})
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
        sizes = sorted(ggufs.values())
        med = sizes[len(sizes) // 2]
        nm = next(k for k, v in ggufs.items() if v == med)
        return ggufs[nm], None
    except Exception:
        return None, None


# бажаний дефолт для міні-чату (qwen3-vl/embed — пропускати: німі/не-чат)
CHAT_PREF = ("qwen3:4b-instruct-2507-q4_K_M", "gemma3:4b",
             "hf.co/INSAIT-Institute/MamayLM-Gemma-3-4B-IT-v1.0-GGUF:Q4_K_M", "gemma3:1b")

# ембед/реранк-моделі — НЕ чат: /api/chat на них дає 400. bge-m3 не містить «embed»
# у назві, тож ловимо за коренями сімейств явно.
_EMBED_MARKERS = ("embed", "bge", "nomic-embed", "gte", "e5-", "mxbai", "snowflake-arctic-embed",
                  "reranker", "rerank")


def is_embed_model(name):
    low = (name or "").lower()
    return any(m in low for m in _EMBED_MARKERS)


def ram_menu_lines(loaded, limit=3):
    """Рядки для меню трея: (заголовок, [до `limit` рядків]) з виводу `ollama ps`.
    Кожна модель окремо «назва · розмір»; ембед-модель (для пошуку) — з приміткою."""
    rows = []
    for l in loaded or []:
        nm = l.split("  ")[0].strip()
        if not nm:
            continue
        sz = ram_size(l)
        txt = "   " + nm + (f"  ·  {sz}" if sz else "")
        if is_embed_model(nm):
            txt += "  ·  для пошуку"
        rows.append(txt)
    if not rows:
        return "Модель у RAM:", ["   (нічого — RAM вільна)"]
    return ("Моделі в RAM:" if len(rows) > 1 else "Модель у RAM:"), rows[:limit]


def ram_chips(loaded, limit=2):
    """Плашки шапки чату з виводу `ollama ps`: [(колір, текст, підказка)].
    Чат-модель першою, пошукова — з приміткою «для пошуку»; понад `limit` — плашка «+N».
    Підказка в кожної плашки — повний список зі розмірами."""
    rows = []
    for l in loaded or []:
        parts = (l or "").split()
        if not parts:
            continue
        nm = parts[0]
        size = ram_size(l).replace("GB", "ГБ").replace("MB", "МБ").replace(".", ",")
        rows.append((is_embed_model(nm), nm.replace(":latest", ""), size))
    if not rows:
        return []
    rows.sort(key=lambda r: r[0])                       # стабільно: чат-моделі перед пошуковими
    tip = "У памʼяті зараз:\n" + "\n".join(
        "%s%s — %s" % (n, " (для пошуку)" if e else "", sz or "розмір невідомий") for e, n, sz in rows)
    out = []
    for emb, nm, sz in rows[:limit]:
        out.append(("green", nm + (" · для пошуку" if emb else (" · " + sz if sz else "")), tip))
    if len(rows) > limit:
        out.append(("more", "+%d" % (len(rows) - limit), tip))
    return out


def pick_chat_model(models):
    for p in CHAT_PREF:
        if p in models:
            return p
    for m in models:
        if is_embed_model(m) or "vl" in m.lower():
            continue
        return m
    return None                        # лише ембед/vl-моделі → чат-моделі НЕМА (не брешемо)


# 26.09.2026: медіа у відповідях. Якщо в тексті відповіді є локальний шлях до файлу —
# показуємо картку/мініатюру інлайн, а не голим текстом чи лінком, що не працює.
_MEDIA_IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
_MEDIA_VID_EXT = (".mp4", ".mov", ".webm", ".m4v")
_MEDIA_AUD_EXT = tuple(sorted(_cf.AUD_EXT))
_MEDIA_FILE_EXT = _MEDIA_IMG_EXT + _MEDIA_VID_EXT + _MEDIA_AUD_EXT + (
    ".pdf", ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".zip", ".docx", ".doc", ".xlsx", ".xls",
    ".pptx", ".ppt", ".key", ".rtf", ".odt", ".numbers", ".pages", ".yaml", ".yml", ".log")
_MEDIA_MAX_BYTES = 8 * 1024 * 1024                    # ~8 МБ — стеля на base64-інлайн
# 30.09.2026: картинка 1,6 МБ → base64 2,2 МБ → ще копії в JS-рядку, атрибуті src і замиканні
# кнопок = ~10 МБ на ОДНУ картинку. На 8 ГБ Маці під свопом це роняло/глушило веб-вʼю.
# Тепер велике йде МІНІАТЮРОЮ (sips, ≤1280 px, JPEG): клік по ній відкриває оригінал.
_MEDIA_INLINE_MAX = 400 * 1024                        # дрібніше — інлайнимо як є
_MEDIA_THUMB_SRC_MAX = 64 * 1024 * 1024               # оригінал більший — навіть на мініатюру не беремось (чіп)
_MEDIA_THUMB_PX = 1280
_MEDIA_THUMB_DIR = os.path.expanduser("~/Library/Caches/KobzarAI/thumbs")
_MEDIA_PATH_RE = re.compile(
    r"(/[^\s`'\"]+?(?:" + "|".join(re.escape(e) for e in _MEDIA_FILE_EXT) + r")(?![A-Za-z0-9]))", re.I)


def _media_data_url(path, ext):
    try:
        mime = mimetypes.guess_type(path)[0] or (
            "image/png" if ext in _MEDIA_IMG_EXT else "video/mp4")
        with open(path, "rb") as fh:
            data = fh.read()
        return "data:%s;base64,%s" % (mime, base64.b64encode(data).decode("ascii"))
    except Exception:
        return None


def _media_thumb_url(path, size, mtime):
    """Мініатюра картинки як data-URL (кеш на диску) або None. Без сторонніх залежностей: sips."""
    try:
        import hashlib
        key = hashlib.sha1(("%s|%d|%d|%d" % (path, size, int(mtime), _MEDIA_THUMB_PX)).encode()).hexdigest()[:24]
        os.makedirs(_MEDIA_THUMB_DIR, exist_ok=True)
        out = os.path.join(_MEDIA_THUMB_DIR, key + ".jpg")
        if not (os.path.isfile(out) and os.path.getsize(out) > 0):
            tmp = out + ".part"
            r = subprocess.run(["/usr/bin/sips", "-Z", str(_MEDIA_THUMB_PX), "-s", "format", "jpeg",
                                "-s", "formatOptions", "82", path, "--out", tmp],
                               capture_output=True, timeout=20)
            if r.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) == 0:
                try: os.remove(tmp)
                except OSError: pass
                return None
            os.replace(tmp, out)
        with open(out, "rb") as fh:
            return "data:image/jpeg;base64,%s" % base64.b64encode(fh.read()).decode("ascii")
    except Exception:
        return None


def _embed_local_media(text):
    """Локальний шлях до картинки/відео (існуючий файл) → інлайн-токен для md() у chatui.py:
    ![[img:NAME|PATH]](data:...) / ![[vid:...]]. Картинка >400 КБ йде мініатюрою (≤1280 px), а
    оригінал відкривається кліком; >8 МБ теж мініатюрою (якщо вдалось), інакше файл-чіп
    ![[file:NAME|PATH]](file). Відео ≤8 МБ інлайн, більше — чіп.
    Шлях, якого нема на диску, або що не читається — лишаємо як звичайний текст."""
    def sub(m):
        p = m.group(1)
        try:
            if not os.path.isfile(p):
                return p
            size = os.path.getsize(p)
            mtime = os.path.getmtime(p)
        except Exception:
            return p
        ext = os.path.splitext(p)[1].lower()
        base = os.path.basename(p)
        if ext in _MEDIA_IMG_EXT and size > 0:
            data = None
            if size <= _MEDIA_INLINE_MAX or (ext == ".gif" and size <= _MEDIA_MAX_BYTES):
                data = _media_data_url(p, ext)              # дрібне / анімований gif — як є
            elif size <= _MEDIA_THUMB_SRC_MAX:
                data = _media_thumb_url(p, size, mtime)
                if data is None and size <= _MEDIA_MAX_BYTES:
                    data = _media_data_url(p, ext)          # sips не зміг — оригінал, якщо ≤8 МБ
            if data:
                return "![[img:%s|%s]](%s)" % (base, p, data)
        elif ext in _MEDIA_VID_EXT and size > 0:
            # 30.09: відео й звук — не base64, а локальна адреса kobzar-file:// (будь-який розмір, з перемоткою)
            return "![[vid:%s|%s]](%s)" % (base, p, _cf.serve_url(p))
        elif ext in _MEDIA_AUD_EXT and size > 0:
            return "![[aud:%s|%s]](%s)" % (base, p, _cf.serve_url(p))
        return "![[file:%s|%s]](%s)" % (base, p, _cf.token_tail(p))
    try:
        return _MEDIA_PATH_RE.sub(sub, text or "")
    except Exception:
        return text or ""


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
        # mods — side-aware токени (lcmd/rcmd/…); упорядкувати за базою ⌃⌥⇧⌘
        ordered = sorted(mods, key=lambda m: _MOD_ORDER.index(_MOD_BASE.get(m, m)))
        hk[act] = {"mods": ordered, "keycode": keycode}
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
        # device-dependent біти у CGEvent flags розрізняють ФІЗИЧНУ сторону клавіші
        # (NX_DEVICE*KEYMASK). Generic-маски вище кажуть лише «cmd натиснуто», не яка.
        DEV = {"lctrl": 0x00000001, "rctrl": 0x00002000,
               "lshift": 0x00000002, "rshift": 0x00000004,
               "lcmd": 0x00000008, "rcmd": 0x00000010,
               "lalt": 0x00000020, "ralt": 0x00000040}

        def sides_of(flags):                  # натиснуті side-токени (lcmd/rcmd/…)
            return frozenset(n for n, b in DEV.items() if flags & b)

        def gens_of(flags):                   # натиснуті бази (cmd/ctrl/…), будь-яка сторона
            return frozenset(n for n, b in MB.items() if flags & b)

        def hit(bm, flags):
            """Чи відповідає набір модифікаторів bm (sided або generic токени) поточним
            flags. Бази мусять збігтися ТОЧНО (без зайвих), а sided-токен вимагає саме
            своєї фізичної сторони. Generic-токен (cmd) матчить будь-яку сторону —
            бекснап-сумісність зі старими дефолтами ⌃⌥."""
            req_bases = frozenset(_MOD_BASE.get(t, t) for t in bm)
            if gens_of(flags) != req_bases:
                return False
            sd = sides_of(flags)
            return all((t not in DEV) or (t in sd) for t in bm)

        def hit_peak(bm, peak):
            """Те саме, але для modifier-only (порівняння з накопиченим peak side-токенів)."""
            req_bases = frozenset(_MOD_BASE.get(t, t) for t in bm)
            if frozenset(_MOD_BASE.get(t, t) for t in peak) != req_bases:
                return False
            return all((t not in DEV) or (t in peak) for t in bm)

        def cb(proxy, etype, event, refcon):
            try:
                flags = CGEventGetFlags(event)
                s = sides_of(flags)                        # side-токени (lcmd/rcmd/…)
                if etype in _MOUSE_DOWN:
                    # клік миші із затиснутими модифікаторами (⌃⌥-drag, mod+клік) —
                    # епізод «брудний», modifier-only хоткей на відпусканні НЕ стріляє
                    if self._active:
                        self._dirty = True
                    return event
                if etype == kCGEventKeyDown:
                    kc = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
                    if kc in (54, 55, 56, 57, 58, 59, 60, 61, 62, 63):  # самі модифікатори — ігнор
                        return event
                    if self.recording is not None:
                        if kc == 53:                      # Esc -> скасувати запис
                            self.recording = None
                        elif s:                            # комбо mod+клавіша (sided)
                            self._record(s, kc)
                        return event
                    self._dirty = True
                    for act, (bm, bkc) in self.binds.items():
                        if bkc is not None and bkc == kc and hit(bm, flags):
                            self._fire(act); break
                elif etype == kCGEventFlagsChanged:
                    if s:
                        if not self._active:
                            self._active = True; self._dirty = False; self._episode = set()
                        self._episode |= set(s)
                    else:                                  # всі модифікатори відпущені
                        if self._active:
                            peak = frozenset(self._episode); self._active = False
                            if peak and not self._dirty:
                                if self.recording is not None:
                                    self._record(peak, None)
                                else:
                                    for act, (bm, bkc) in self.binds.items():
                                        if bkc is None and hit_peak(bm, peak):
                                            self._fire(act); break
            except Exception:
                pass
            return event

        # mouse-down типи (CGEventType): left=1, right=3, other=25 — щоб бачити
        # mod+клік і не стріляти modifier-only хоткеєм на відпусканні модифікаторів
        _MOUSE_DOWN = (1, 3, 25)
        mask = (CGEventMaskBit(kCGEventFlagsChanged) | CGEventMaskBit(kCGEventKeyDown)
                | CGEventMaskBit(1) | CGEventMaskBit(3) | CGEventMaskBit(25))
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
    """Старе скло (NSVisualEffectView, blur за вікном) — ФОЛБЕК для < macOS 26."""
    fx = NSVisualEffectView.alloc().initWithFrame_(frame)
    fx.setMaterial_(material)
    fx.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
    fx.setState_(NSVisualEffectStateActive)
    fx.setAutoresizingMask_(18)  # ширина|висота тягнуться
    return fx


# --- СПРАВЖНЄ Liquid Glass (macOS 26 Tahoe): NSGlassEffectView ---
# Дає реальне заломлення десктопу по контуру (лінза), а не плаский матовий blur.
try:
    NSGlassEffectView = objc.lookUpClass("NSGlassEffectView")
    # Regular(0) = ЗВИЧАЙНЕ матове скло Apple (як віджети/сайдбари): прозорість + ОБЕРЕЖНИЙ
    # блюр + лінза/переливи. Clear(1) — надто прозоре, без блюру (текст під вікном читається).
    _GLASS_REGULAR = 0
    _HAS_GLASS = True
except Exception:
    NSGlassEffectView = None
    _HAS_GLASS = False


THEMES = ["Авто", "Світла", "Темна"]
TOKEN_OPTS = ["512", "1024", "2048", "4096"]
CTX_OPTS = ["2048", "4096", "8192", "16384"]   # розмір контекстного вікна (num_ctx)
THERM_OPTS = [85, 88, 90, 92, 95, 98, 100, 103, 105]   # поріг термо-паузи, °C
# імена message-хендлерів webview-налаштувань (міст HTML→Python). Розширюється стадіями.
SETTINGS_MSGS = ["ui"]

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
LP_SBW = 196   # ширина бічного списку чатів
LP_SBG = 14    # відступ між списком і колонкою чату
LP_PAD = 14    # внутрішнє поле картки
LP_ROW = 34    # висота рядка
LP_SEC = 16    # відстань між секціями
LP_LBL = 140   # колонка лейблів (вирівняна праворуч)
LP_HDR = 20    # висота group-заголовка над карткою
LP_GAP = 10    # проміжок між контролями


def accent_color():
    # Системний акцент macOS (Системні параметри → Вигляд → Акцентний колір).
    # Один колір на весь застосунок: наші кнопки/слайдери/кільця + рідні виділення
    # таблиці й меню збігаються автоматично, бо всі беруть controlAccentColor.
    try: return NSColor.controlAccentColor()
    except Exception: return NSColor.systemBlueColor()


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




_UKR_MON = ["січ", "лют", "бер", "кві", "тра", "чер",
            "лип", "сер", "вер", "жов", "лис", "гру"]

def rel_time(ts):
    """Короткий підпис часу для списку чатів (як «Topics» у Cherry): сьогодні→HH:MM,
    учора→«вчора», інакше→«D міс»."""
    if not ts:
        return ""
    now = time.localtime(); t = time.localtime(ts)
    if (now.tm_year, now.tm_yday) == (t.tm_year, t.tm_yday):
        return time.strftime("%H:%M", t)
    yest = time.localtime(time.mktime(now) - 86400)
    if (yest.tm_year, yest.tm_yday) == (t.tm_year, t.tm_yday):
        return "вчора"
    return "%d %s" % (t.tm_mday, _UKR_MON[t.tm_mon - 1])


class ChatRowView(NSTableRowView):
    """Рядок списку чатів з округлою підсвіткою активного (як Cherry/Finder),
    без інверсії тексту — підписи лишаються темними й читабельними.
    Підсвітку малюємо В background (а не drawSelectionInRect_), бо таблиця
    в стилі None не дасть AppKit малювати ні власну заливку, ні обведену
    menu-target рамку на правий клік (інакше двоїлося)."""
    def setSelected_(self, flag):
        # стиль None → AppKit НЕ перемальовує row-view при зміні виділення →
        # стара підсвітка лишається (привид), нова не малюється. Форсуємо перемальов.
        objc.super(ChatRowView, self).setSelected_(flag)
        self.setNeedsDisplay_(True)

    def drawBackgroundInRect_(self, rect):
        if not self.isSelected():
            return
        inset = NSInsetRect(self.bounds(), 4, 1)
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(inset, 7, 7)
        NSColor.controlAccentColor().colorWithAlphaComponent_(0.18).set()
        path.fill()




class _LibRowView(NSTableRowView):
    """Рядок бібліотеки моделей: заокруглена вставлена підсвітка (як ChatRowView,
    єдиний UI), трохи помітніша (0.22) + тонка рамка-акцент. Текст лишається
    темним (без інверсії) → читабельний і центрований коміркою."""
    def setSelected_(self, flag):
        # стиль None → AppKit не інвалідує row-view при зміні вибору → форсуємо
        # перемальов, інакше підсвітка двоїться (стара лишається) / не показується.
        objc.super(_LibRowView, self).setSelected_(flag)
        self.setNeedsDisplay_(True)

    def drawBackgroundInRect_(self, rect):
        if not self.isSelected():
            return
        inset = NSInsetRect(self.bounds(), 4, 2)
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(inset, 7, 7)
        NSColor.controlAccentColor().colorWithAlphaComponent_(0.22).set()
        path.fill()
        NSColor.controlAccentColor().colorWithAlphaComponent_(0.55).set()
        path.setLineWidth_(1.0); path.stroke()


def chat_html():
    # 26.09.2026: чат = одна сторінка (chatui.py) (старий _CHAT_HTML прибрано 27.09.2026)
    try:
        import chatui
    except ImportError:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import chatui
    return chatui.page(is_dark(), accent_hex())


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


class SlidingSegment(NSView):
    """Сегмент-перемикач з акцентною плашкою, що ЇЗДИТЬ між пунктами (ease-out,
    таймер) — як у HTML-мокапі. Нативний NSSegmentedControl так не вміє: лише
    перемикає підсвітку без руху. Плашку Й текст малюємо разом у drawRect (текст
    ЗАВЖДИ над плашкою), тож обраний підпис не ховається. Обраний текст білий,
    решта — secondary. Drop-in: selectedSegment()/setSelectedSegment_/setTarget_action_."""
    def initWithLabels_frame_(self, labels, fr):
        self = objc.super(SlidingSegment, self).initWithFrame_(fr)
        if self is None: return None
        self._labels = list(labels)
        self._sel = 0
        self._target = None
        self._action = None
        self._font = NSFont.systemFontOfSize_weight_(12.5, 0.30)
        self._pill_x = None                       # анімований центр плашки (None → центр обраного)
        self._anim = None                         # {"from","to","t0","dur"}
        self._timer = None
        self._track = True
        self.setWantsLayer_(True)
        # капсула повністю заокруглена (radius=h/2) → узгоджується зі скляною
        # капсулою unified-тулбара та пігулкою всередині (юзер: «форма не співвідноситься»)
        self.layer().setCornerRadius_(max(1.0, fr.size.height / 2.0))
        self._paint_track()
        return self

    @objc.python_method
    def _paint_track(self):
        # track=True → заглиблений контейнер (інлайн-контрол); False → плаваючі вкладки.
        # tint під тему + тонка обводка → НЕ зливається зі склом на макс. прозорості
        # (узгоджено зі слайдер-картками Голосу).
        if self._track:
            dark = "Dark" in str(self.effectiveAppearance().name())
            bg = (NSColor.colorWithRed_green_blue_alpha_(1, 1, 1, 0.10) if dark
                  else NSColor.colorWithRed_green_blue_alpha_(0, 0, 0, 0.07))
            self.layer().setBackgroundColor_(bg.CGColor())
            self.layer().setBorderWidth_(1.0)
            self.layer().setBorderColor_(NSColor.separatorColor().CGColor())
        else:
            self.layer().setBackgroundColor_(NSColor.clearColor().CGColor())
            self.layer().setBorderWidth_(0.0)

    def setTrackless_(self, on):
        self._track = not on
        self._paint_track()
        self.setNeedsDisplay_(True)

    @objc.python_method
    def _widths(self):
        """Ширини сегментів пропорційні підписам (довгий підпис не впирається в краї)."""
        tot = self.bounds().size.width
        nat = []
        for lab in self._labels:
            sz = NSAttributedString.alloc().initWithString_attributes_(
                lab, {NSFontAttributeName: self._font}).size()
            nat.append(sz.width + 28.0)
        k = tot / max(1.0, sum(nat))
        return [n * k for n in nat]

    @objc.python_method
    def _center(self, i):
        ws = self._widths()
        return sum(ws[:i]) + ws[i] / 2.0

    @objc.python_method
    def _pill_w(self, x):
        """Ширина плашки в позиції x: між сусідніми сегментами плавно перетікає."""
        ws = self._widths(); cs = [self._center(i) for i in range(len(ws))]
        if x <= cs[0]: return ws[0]
        for i in range(1, len(ws)):
            if x <= cs[i]:
                t = (x - cs[i - 1]) / max(1e-6, cs[i] - cs[i - 1])
                return ws[i - 1] + (ws[i] - ws[i - 1]) * t
        return ws[-1]

    @objc.python_method
    def _index_at(self, x):
        acc = 0.0
        for i, w in enumerate(self._widths()):
            acc += w
            if x < acc: return i
        return len(self._labels) - 1

    def setTarget_action_(self, t, a):
        self._target = t; self._action = a

    def selectedSegment(self):
        return self._sel

    def setSelectedSegment_(self, i):
        self._sel = max(0, min(len(self._labels) - 1, int(i)))
        if self._anim is None:        # не збивати плашку, що ЇДЕ (tabChanged повторно сетить сегмент)
            self._pill_x = self._center(self._sel)
        self.setNeedsDisplay_(True)

    def reaccent(self):
        self.setNeedsDisplay_(True)

    def drawRect_(self, r):
        if self._pill_x is None:
            self._pill_x = self._center(self._sel)
        h = self.bounds().size.height
        ws = self._widths()
        pw = self._pill_w(self._pill_x) - 6; ph = h - 6
        rad = ph / 2.0                       # повністю кругла пігулка (нести в круглій капсулі)
        pill = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(self._pill_x - pw / 2.0, 3, pw, ph), rad, rad)
        # неактивне вікно → плашка сіра, обраний текст темний (як нативні контроли)
        win = self.window()
        key = (win is None) or win.isKeyWindow()
        if key:
            accent_color().setFill(); sel_col = NSColor.whiteColor()
        else:
            NSColor.unemphasizedSelectedContentBackgroundColor().setFill()
            sel_col = NSColor.labelColor()
        pill.fill()
        x0 = 0.0
        for i, lab in enumerate(self._labels):
            col = sel_col if i == self._sel else NSColor.secondaryLabelColor()
            s = NSAttributedString.alloc().initWithString_attributes_(
                lab, {NSForegroundColorAttributeName: col, NSFontAttributeName: self._font})
            sz = s.size()
            s.drawAtPoint_(NSMakePoint(x0 + (ws[i] - sz.width) / 2.0, (h - sz.height) / 2.0))
            x0 += ws[i]

    def mouseDown_(self, e):
        p = self.convertPoint_fromView_(e.locationInWindow(), None)
        i = max(0, min(len(self._labels) - 1, self._index_at(p.x)))
        if i == self._sel:
            return
        self._sel = i
        frm = self._pill_x if self._pill_x is not None else self._center(i)
        self._anim = {"from": frm, "to": self._center(i), "t0": time.time(), "dur": 0.34}
        if self._timer is None:
            self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                1 / 60.0, self, "_tick:", None, True)
        self.setNeedsDisplay_(True)
        if self._target is not None and self._action is not None:
            NSApp.sendAction_to_from_(self._action, self._target, self)

    def _tick_(self, timer):
        a = self._anim
        if a is None:
            if self._timer is not None:
                self._timer.invalidate(); self._timer = None
            return
        t = (time.time() - a["t0"]) / a["dur"]
        if t >= 1.0:
            self._pill_x = a["to"]; self._anim = None
            if self._timer is not None:
                self._timer.invalidate(); self._timer = None
        else:
            ease = 1.0 - (1.0 - t) ** 3            # ease-out cubic
            self._pill_x = a["from"] + (a["to"] - a["from"]) * ease
        self.setNeedsDisplay_(True)


class _DangerButton(NSButton):
    """Кнопка небезпечної дії: червоний текст завжди, повний червоний фон + білий
    текст на час натиску (mouseDown тримає трекінг до відпускання)."""
    @objc.python_method
    def _paint(self, pressed):
        col = NSColor.whiteColor() if pressed else NSColor.systemRedColor()
        try:
            a = NSAttributedString.alloc().initWithString_attributes_(
                getattr(self, "_danger_title", self.title()),
                {NSForegroundColorAttributeName: col,
                 NSFontAttributeName: NSFont.systemFontOfSize_(13.0)})
            self.setAttributedTitle_(a)
        except Exception: pass
        try: self.setBezelColor_(NSColor.systemRedColor() if pressed else None)
        except Exception: pass

    def mouseDown_(self, e):
        self._paint(True)
        objc.super(_DangerButton, self).mouseDown_(e)
        self._paint(False)


FADE_TOP = 30.0   # висота смуги згасання зверху (px)


class _TopClipView(NSClipView):
    """Перевернутий clip-view: документ пришпилений до ВЕРХУ, скрол стартує згори."""
    def isFlipped(self):
        return True


class _FadeScrollView(NSScrollView):
    """Скрол з делікатним fade зверху — як macOS 26 System Settings: контент
    РОЗЧИНЯЄТЬСЯ у скло на верхній кромці viewport, під плаваючим скляним сегментом
    (Загальні/Голос/Моделі/Чат), а не обрізається грубою лінією.

    Правильна реалізація (попередня не їхала за скролом): маска-градієнт на шарі
    clip-view, її origin.y ЩОРАЗУ дорівнює bounds.origin.y → смуга згасання завжди
    стоїть на верху ВИДИМОЇ області, а не пливе з контентом. Слухаємо
    NSViewBoundsDidChangeNotification (зветься на КОЖЕН скрол, на відміну від tile()).
    Implicit-анімація шару вимкнена (CATransaction) — інакше маска «здоганяє» скрол
    ривками. Маска лише на clip → скролбар (сусідній сабвʼю, поза clip) не згасає."""
    def initWithFrame_(self, fr):
        self = objc.super(_FadeScrollView, self).initWithFrame_(fr)
        if self is None:
            return None
        self._fade_mask = None
        self._fade_obs = False
        return self

    @objc.python_method
    def _ensure_observer(self):
        cv = self.contentView()
        if cv is None or self._fade_obs:
            return
        cv.setPostsBoundsChangedNotifications_(True)
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, "_fadeBoundsChanged:", NSViewBoundsDidChangeNotification, cv)
        self._fade_obs = True

    @objc.python_method
    def _ensure_mask(self):
        cv = self.contentView()
        if cv is None:
            return None
        cv.setWantsLayer_(True)
        if self._fade_mask is None:
            g = CAGradientLayer.layer()
            clear = NSColor.clearColor().CGColor()
            solid = NSColor.blackColor().CGColor()   # масці важлива лише alpha, не колір
            # 4 стопи: прозоро за тулбаром → плавна поява одразу під його нижньою кромкою
            g.setColors_([clear, clear, solid, solid])
            g.setStartPoint_((0.5, 0.0))             # flipped-layer: (0)=верх viewport=верх вікна
            g.setEndPoint_((0.5, 1.0))               # (1)=низ
            self._fade_mask = g
            if cv.layer() is not None:
                cv.layer().setMask_(g)
        return self._fade_mask

    @objc.python_method
    def _layout_mask(self):
        cv = self.contentView()
        g = self._ensure_mask()
        if cv is None or g is None or cv.layer() is None:
            return
        if cv.layer().mask() is not g:               # шар clip міг перестворитись
            cv.layer().setMask_(g)
        b = cv.bounds()
        h = b.size.height; w = b.size.width
        if h <= 0:
            return
        # T = висота тулбара (верхній contentInset): контент під ним прихований (clear),
        # виринаючи з-під нижньої кромки — плавно проявляється протягом ~22px.
        try: T = float(self.contentInsets().top)
        except Exception: T = 0.0
        top_clear = max(0.0, T - 6.0)                # майже до нижньої кромки тулбара — прозоро
        solid_at = T + 22.0                          # повна непрозорість трохи нижче кромки
        l1 = min(0.999, top_clear / h)
        l2 = min(1.0, solid_at / h)
        if l2 <= l1: l2 = min(1.0, l1 + 0.001)
        CATransaction.begin(); CATransaction.setDisableActions_(True)
        g.setLocations_([0.0, l1, l2, 1.0])
        g.setFrame_(NSMakeRect(b.origin.x, b.origin.y, w, h))
        CATransaction.commit()

    def _fadeBoundsChanged_(self, note):
        self._layout_mask()

    def tile(self):
        objc.super(_FadeScrollView, self).tile()
        self._ensure_observer()
        self._layout_mask()


class _FocusRing(NSView):
    """Акцентне кільце-оверлей навколо поля. Пропускає кліки (hitTest→None),
    тож не заважає ставити курсор; показується лише поки поле в фокусі."""
    def hitTest_(self, p):
        return None
    def drawRect_(self, r):
        b = self.bounds()
        rect = NSMakeRect(b.origin.x + 1.5, b.origin.y + 1.5,
                          b.size.width - 3.0, b.size.height - 3.0)
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, 6.0, 6.0)
        accent_color().setStroke()
        path.setLineWidth_(2.0)
        path.stroke()


class _RingField(NSTextField):
    """Поле вводу, що САМО показує акцентне кільце у фокусі (надійніше за
    delegate-нотифікації, які у фоновому вікні не завжди приходять)."""
    def becomeFirstResponder(self):
        ok = objc.super(_RingField, self).becomeFirstResponder()
        r = getattr(self, "_ring", None)
        if ok and r is not None:
            r.setNeedsDisplay_(True); r.setHidden_(False)
        return ok
    def textDidEndEditing_(self, notif):
        objc.super(_RingField, self).textDidEndEditing_(notif)
        r = getattr(self, "_ring", None)
        if r is not None: r.setHidden_(True)


class _HoverButton(NSButton):
    """Іконка-кнопка: нейтральна в спокої, акцент-tint на hover, alpha-flash на натиск."""
    def initWithFrame_(self, fr):
        self = objc.super(_HoverButton, self).initWithFrame_(fr)
        if self is None: return None
        self._hovcolor = None
        self._area = None
        self._danger = False
        return self

    def setHoverColor_(self, c):
        self._hovcolor = c

    def setDangerFlash_(self, f):
        self._danger = bool(f)         # натиск → заливка червоним + біла іконка (як .trash:active в мокапі)

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
        if self._danger:
            # .btn.danger:active — заливка червона + БІЛИЙ текст (і іконка). Текст міняємо
            # окремо: contentTintColor не перебиває колір attributed-заголовка (черв. текст
            # «Видалити KobzarAI…» лишався б червоним на червоному).
            prev = self.attributedTitle()
            try:
                self.setBezelColor_(NSColor.systemRedColor())
                self.setContentTintColor_(NSColor.whiteColor())
                s = str(self.title())
                if s:
                    white = NSAttributedString.alloc().initWithString_attributes_(
                        s, {NSForegroundColorAttributeName: NSColor.whiteColor(),
                            NSFontAttributeName: self.font() or NSFont.systemFontOfSize_(0)})
                    self.setAttributedTitle_(white)
            except Exception: pass
            objc.super(_HoverButton, self).mouseDown_(e)   # блокує до відпускання
            try:
                self.setBezelColor_(None)
                self.setContentTintColor_(None)
                if prev is not None: self.setAttributedTitle_(prev)
            except Exception: pass
            return
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
        self.tok_num = None
        self.tok_idx = 2
        self.ctx_num = None
        self.ctx_idx = 1
        self.transp_val = None
        self._scroll = None
        self._cards = []
        self._pages = {}
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
        self.pull_btn = None
        self.preview_btn = None
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
        self.lib_sort = "size"
        self.lib_online = True
        self.sel_model = None
        self._last_up = None   # відстеження стану Ollama для авто-підхоплення в refresh
        # чат (WKWebView)
        self.web = None
        self._web_ready = False
        self._js_queue = []
        # вікно налаштувань (окремий WKWebView, рендерить ui/settings.html)
        self.set_web = None
        self._settings_ready = False
        self.chat_view = None
        self.chat_input = None
        self.chat_pill = None
        self.chat_sc = None
        self.chat_stop = None
        self.chat_model_lbl = None
        self.chat_size_lbl = None
        self.chat_dot = None
        self.chat_at = None
        # 26.09: автодоповнення команд @/… у чаті (бордерлес-панель над полем)
        self.hist_tbl = None
        self._chat_host = None      # повноекранний контейнер чату (поза скрол-сторінками)
        self._chat_built = False
        # База знань (self-contained RAG): вмикається тумблером у пігулці, індексує
        # обрану теку через Ollama bge-m3. Ліниво — щоб апка не падала, коли kb.py/модель
        # відсутні (портативність: у того, хто просто завантажив, це просто вимкнено).
        _kbcfg = load_cfg()
        self.kb_on = bool(_kbcfg.get("kb_on", False))
        self.kb_folder = _kbcfg.get("kb_folder", "") or ""
        self.kb_index = _kbcfg.get("kb_index", "") or ""   # шлях до ГОТОВОГО індексу (read-only)
        self._kb = None
        self._kb_busy = False
        self.autospeak = None
        self.autospeak_on = False
        self._ram_warned = False    # попередження про тісний RAM у режимі «Наживо» — раз за сесію
        self._pull_cancel = threading.Event()   # кооп. скасування завантаження моделі (HTTP-стрім, не subprocess)
        self.accent_swatch = None
        self.send_btn = None
        self._generating = False
        self.sessions = load_chats() or [
            {"title": "Чат 1", "history": [], "ts": time.time(), "id": str(int(time.time() * 1000))}]
        self.cur = 0
        return self

    @objc.python_method
    def show(self):
        if self.win is None:
            self._build()
        self.is_open = True
        self.panel._update_activation()
        self._install_edit_menu()
        if os.environ.get("KOBZARAI_ONSCREEN"):     # тест-хук: над десктопом, без крадіжки фокуса (перевірка скла)
            self.win.setFrameOrigin_((80.0, 120.0))
            self.win.orderFront_(None)
        elif os.environ.get("KOBZARAI_NOACTIVATE"):   # тест-хук: рендер за екраном, без крадіжки фокуса
            fr = self.win.frame()
            self.win.setFrameOrigin_((-4000.0, 200.0))
            self.win.makeKeyAndOrderFront_(None)
        else:
            NSApp.activateIgnoringOtherApps_(True)
            self.win.makeKeyAndOrderFront_(None)
        if os.environ.get("KOBZARAI_FOCUS_PULL") and self.pull_field is not None:
            self.win.makeFirstResponder_(self.pull_field)   # тест-хук: фокус у поле
        else:
            self.win.makeFirstResponder_(None)   # без авто-фокуса поля (кільце лише на клік)
        self.reload_models()
        self._sync_voices()
        self._refresh_chat_header()
        self.refresh()

    @objc.python_method
    def _sync_voices(self):
        """Перечитати голоси з сервера і ПЕРЕЗІБРАТИ пункти попапа на кожному показі.

        🔴 ЧОМУ цього не робить `refresh_voices()` у `_page_voice`: сторінки
        будуються РІВНО ОДИН раз (`_build`), а вікно кешується у `panel._settings`.
        Перше відкриття зазвичай припадає на момент, коли панель щойно підняла
        TTS-сервер і `/voices` ще не відповідає за 2 с ⇒ у попап назавжди сідає
        фолбек із 4 імен, і жоден рестарт застосунку цього не лікує (сценарій
        01.08.2026: сервер віддає 31 голос, у вікні досі 4)."""
        pop = getattr(self, "voice_pop", None)
        if pop is None:
            return
        try:
            names = refresh_voices()
            titles = [voice_label(x) for x in names]
            if list(pop.itemTitles()) == titles:
                return
            prev = pop.titleOfSelectedItem()
            pop.removeAllItems()
            pop.addItemsWithTitles_(titles)
            want = voice_label(getattr(self.panel, "voice", None) or names[0])
            for t in (want, prev):
                if t and t in titles:
                    pop.selectItemWithTitle_(t)
                    break
        except Exception:
            pass                            # список голосів не має ламати відкриття вікна

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
        i = max(0, min(3 + len(self._ext_tabs()), int(i)))
        if self.seg is not None:
            try: self.seg.setSelectedSegment_(i)
            except Exception: pass
        if i == 3:                      # Чат — не скрол-сторінка, а повноекранний сплит
            self._show_chat_page()
            return
        # інші вкладки: ховаємо чат, повертаємо скрол зі сторінками
        if self._chat_host is not None:
            self._chat_host.setHidden_(True)
        if self._scroll is not None:
            self._scroll.setHidden_(False)
        keys = {0: "general", 1: "voice", 2: "models"}
        builders = {0: self._page_general, 1: self._page_voice, 2: self._page_models}
        tab = None
        if i >= 4:                                # вкладка, яку додало доповнення
            tab = self._ext_tabs()[i - 4]
            keys[i] = tab["key"]; builders[i] = lambda: tab["build"](self)
        key = keys[i]
        page = self._pages.get(key)
        if page is None:
            if tab is None:
                page = builders[i]()
            else:
                try: page = builders[i]()
                except Exception: page = self._page([])
            self._pages[key] = page
        elif tab is not None and tab.get("show"):
            try: tab["show"](self)                # що могло змінитись, поки вкладку не бачили
            except Exception: pass
        self._set_page(page, key)

    @objc.python_method
    def _show_chat_page(self):
        """Чат займає весь простір під тулбаром (сайдбар+транскрипт+пігулка),
        НЕ скролиться як сторінка → ховаємо скрол, показуємо власний контейнер."""
        if self._scroll is not None:
            self._scroll.setHidden_(True)
        ch = self._chat_host
        if ch is None:
            host = self._host
            try:    r = self.win.contentLayoutRect()      # площа під unified-тулбаром
            except Exception: r = host.bounds()
            ch = NSView.alloc().initWithFrame_(r)
            ch.setAutoresizingMask_(18)                   # ширина+висота тягнуться, верх. відступ фікс
            host.addSubview_(ch)
            self._chat_host = ch
            # будуємо після того, як контейнер отримав реальний фрейм
            self._build_chat(ch, r.size.width, r.size.height)
            self._chat_built = True
            self._refresh_chat_header()
        else:
            ch.setHidden_(False)
            self._refresh_chat_header()

    @objc.python_method
    def _set_page(self, page, key=None):
        sc = self._scroll
        # Кеш обгорток: пересоздання wrap+констрейнтів на КОЖНЕ перемикання давало
        # повний Auto Layout прохід сторінки → відчутний лаг табів (надто під свопом).
        # Повторний показ = чистий setDocumentView + реактивація крос-констрейнтів
        # (вони деактивуються, коли wrap вилітає з ієрархії).
        wraps = getattr(self, "_wraps", None)
        if wraps is None:
            wraps = {}; self._wraps = wraps
        cached = wraps.get(key)
        if cached is not None:
            w, cons = cached
            sc.setDocumentView_(w)
            NSLayoutConstraint.activateConstraints_(cons)
            return
        # обгортка на всю ширину viewport; контент центрований всередині (стеля 600).
        # (центрувати вузький documentView напряму в clip-view не можна — NSScrollView
        #  кладе його в лівий-верх; тому повнорозмірний wrap = documentView.)
        wrap = self._al(NSView.alloc().init())
        wrap.addSubview_(page)
        sc.setDocumentView_(wrap)
        cv = sc.contentView()
        wEq = page.widthAnchor().constraintEqualToAnchor_constant_(wrap.widthAnchor(), -48)
        wEq.setPriority_(750)
        cons = [
            wrap.topAnchor().constraintEqualToAnchor_(cv.topAnchor()),
            wrap.leadingAnchor().constraintEqualToAnchor_(cv.leadingAnchor()),
            wrap.trailingAnchor().constraintEqualToAnchor_(cv.trailingAnchor()),
            wrap.widthAnchor().constraintEqualToAnchor_(sc.widthAnchor()),
            page.topAnchor().constraintEqualToAnchor_constant_(wrap.topAnchor(), 10),
            page.bottomAnchor().constraintEqualToAnchor_constant_(wrap.bottomAnchor(), -16),
            page.centerXAnchor().constraintEqualToAnchor_(wrap.centerXAnchor()),
            wEq]      # без стелі 720 — контент тягнеться за шириною вікна (мінус поле 48)
        NSLayoutConstraint.activateConstraints_(cons)
        if key is not None:
            wraps[key] = (wrap, cons)

    def tabChanged_(self, sender):
        self.select_tab(sender.selectedSegment())

    # старий сегмент-хендлер (мертвий, на випадок зовнішніх викликів)
    def segChanged_(self, sender):
        try: self.select_tab(sender.selectedSegment())
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
    def _btn(self, view, title, x, y, w, action, h=28, mask=8, symbol=None, primary=False,
             danger=False, sym_pt=None, sym_w=4):
        # danger=True → натиск заливає червоним (кнопки видалення в мокапі)
        # sym_pt → тонший/менший SF-символ (sym_w: вага, 4=regular) — не чіпає інші вкладки
        cls = _HoverButton if danger else NSButton
        b = cls.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        b.setTitle_(title); b.setBezelStyle_(1)
        b.setTarget_(self); b.setAction_(action)
        if danger: b.setDangerFlash_(True)
        if symbol:
            img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, title)
            if img:
                if sym_pt is not None:
                    try:
                        cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(
                            float(sym_pt), sym_w)
                        img = img.imageWithSymbolConfiguration_(cfg) or img
                    except Exception: pass
                b.setImage_(img); b.setImagePosition_(2)  # NSImageLeft
        if primary:
            b.setKeyEquivalent_("\r")
            try: b.setBezelColor_(accent_color())
            except Exception: pass
        b.setAutoresizingMask_(mask)
        view.addSubview_(b)
        return b

    @objc.python_method
    def _ibtn(self, view, symbol, x, y, action, w=30, h=26, mask=8, tip="", color=None,
              danger=False, sym_pt=None, sym_w=4):
        """Компактна іконка-кнопка (SF Symbol). color → мінімальний акцент іконки.
        danger=True → натиск заливає червоним (як кнопки видалення в мокапі).
        sym_pt → тонший/менший символ (sym_w: вага) — опційно, не чіпає інші виклики."""
        b = _HoverButton.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        b.setBezelStyle_(1); b.setTitle_("")
        b.setTarget_(self); b.setAction_(action)
        img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, tip)
        if img:
            if sym_pt is not None:
                try:
                    cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(
                        float(sym_pt), sym_w)
                    img = img.imageWithSymbolConfiguration_(cfg) or img
                except Exception: pass
            b.setImage_(img); b.setImagePosition_(1)  # NSImageOnly (template → нейтральний)
        if color is not None:
            b.setHoverColor_(color)        # колір лише на hover, не в спокої
        if danger:
            b.setDangerFlash_(True)
        if tip: b.setToolTip_(tip)
        b.setAutoresizingMask_(mask)
        view.addSubview_(b)
        return b

    @objc.python_method
    def _token_stepper(self, view, x, y, w, mask=9):
        """Степер ± «Відповідь, токенів» (як .stepper у мокапі): [−][num][+] у
        заокругленій плашці. Крокає по TOKEN_OPTS. Стан → self.tok_idx, cfg num_predict."""
        try: self.tok_idx = TOKEN_OPTS.index(str(load_cfg().get("num_predict", 2048)))
        except ValueError: self.tok_idx = 2
        h = 28
        box = NSBox.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        box.setBoxType_(4); box.setTitlePosition_(0); box.setCornerRadius_(7.0)
        box.setBorderWidth_(1.0); box.setBorderColor_(NSColor.separatorColor())
        box.setFillColor_(NSColor.colorWithWhite_alpha_(0.5, 0.09))
        box.setAutoresizingMask_(mask); view.addSubview_(box)
        bw = 30; nw = w - 2 * bw
        for tag, sym, bx in ((-1, "−", 0), (1, "+", w - bw)):
            btn = _HoverButton.alloc().initWithFrame_(NSMakeRect(x + bx, y, bw, h))
            btn.setBordered_(False); btn.setTitle_(sym)
            btn.setFont_(NSFont.systemFontOfSize_(16.0))
            btn.setTag_(tag); btn.setTarget_(self); btn.setAction_("tokStep:")
            btn.setAutoresizingMask_(mask); view.addSubview_(btn)
        # вертикальні роздільники навколо числа
        for sx in (x + bw, x + bw + nw):
            sep = NSBox.alloc().initWithFrame_(NSMakeRect(sx, y + 4, 1, h - 8))
            sep.setBoxType_(2); sep.setAutoresizingMask_(mask); view.addSubview_(sep)
        num = NSTextField.alloc().initWithFrame_(NSMakeRect(x + bw, y + 5, nw, 18))
        num.setBezeled_(False); num.setDrawsBackground_(False); num.setEditable_(False)
        num.setSelectable_(False); num.setAlignment_(2)   # center
        num.setFont_(NSFont.systemFontOfSize_(13.0))
        num.setStringValue_(TOKEN_OPTS[self.tok_idx])
        num.setAutoresizingMask_(mask); view.addSubview_(num)
        self.tok_num = num

    @objc.python_method
    def _field(self, view, x, y, w, placeholder="", h=26, mask=10):
        f = _RingField.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        f.setEditable_(True); f.setBezeled_(True)
        if placeholder: f.setPlaceholderString_(placeholder)
        f.setFocusRingType_(1)          # без системного синього кільця → акцентне кільце нижче
        # однорядкове поле: довгий текст СКРОЛИТЬСЯ горизонтально (курсор веде), а не
        # переноситься/розпирає висоту — стандартна поведінка полів macOS
        f.setUsesSingleLineMode_(True)
        try:
            c = f.cell()
            c.setScrollable_(True); c.setWraps_(False)
            c.setLineBreakMode_(5)      # TruncatingMiddle, коли поле поза фокусом
        except Exception: pass
        f.setDelegate_(self)
        f.setAutoresizingMask_(mask)
        view.addSubview_(f)
        # акцентне кільце-оверлей (приховане; підсвічується у фокусі самим полем)
        ring = _FocusRing.alloc().initWithFrame_(NSMakeRect(x - 2, y - 2, w + 4, h + 4))
        ring.setHidden_(True); ring.setAutoresizingMask_(mask)
        view.addSubview_(ring)
        f._ring = ring
        if not hasattr(self, "_all_rings"): self._all_rings = []
        self._all_rings.append(ring)
        return f

    def controlTextDidChange_(self, notif):
        if notif.object() is self.pull_field:
            self._update_pull_btn()

    @objc.python_method
    def _update_pull_btn(self):
        b = self.pull_btn
        if b is None or self.pull_field is None: return
        has = bool(str(self.pull_field.stringValue()).strip())
        try: b.setBezelColor_(accent_color() if has else None)
        except Exception: pass

    @objc.python_method
    def _acc_check(self, b):
        """Галочка у колір акценту; текст лишається нейтральним (labelColor)."""
        try:
            b.setContentTintColor_(accent_color())
            t = str(b.title())
            if t:
                att = NSAttributedString.alloc().initWithString_attributes_(
                    t, {NSForegroundColorAttributeName: NSColor.labelColor(),
                        NSFontAttributeName: b.font() or NSFont.systemFontOfSize_(0)})
                b.setAttributedTitle_(att)
        except Exception: pass

    @objc.python_method
    def _sep(self, view, x, y, w):
        b = NSBox.alloc().initWithFrame_(NSMakeRect(x, y, w, 1)); b.setBoxType_(2)
        b.setAutoresizingMask_(10)
        view.addSubview_(b)

    # ===================== Auto Layout тулкіт (нативні контроли) =====================
    # Жодних піксельних координат: NSStackView + констрейнти. Контроли — СИСТЕМНІ
    # (NSSwitch/NSSlider/NSPopUpButton/NSSegmentedControl) → на macOS 26 = Liquid Glass самі.
    @objc.python_method
    def _al(self, v):
        v.setTranslatesAutoresizingMaskIntoConstraints_(False); return v

    @objc.python_method
    def _fillx(self, child, parent, inset=0.0):
        NSLayoutConstraint.activateConstraints_([
            child.leadingAnchor().constraintEqualToAnchor_constant_(parent.leadingAnchor(), inset),
            child.trailingAnchor().constraintEqualToAnchor_constant_(parent.trailingAnchor(), -inset)])

    @objc.python_method
    def _vstack(self, spacing=10):
        s = self._al(NSStackView.alloc().init())
        s.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
        s.setAlignment_(NSLayoutAttributeLeading); s.setSpacing_(spacing)
        return s

    @objc.python_method
    def _hstack(self, spacing=8):
        s = self._al(NSStackView.alloc().init())
        s.setOrientation_(NSUserInterfaceLayoutOrientationHorizontal)
        s.setAlignment_(NSLayoutAttributeCenterY); s.setSpacing_(spacing)
        return s

    @objc.python_method
    def _albl(self, text, gray=False, size=13.0, bold=False):
        f = NSTextField.labelWithString_(text)
        f.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
        if gray: f.setTextColor_(NSColor.secondaryLabelColor())
        return self._al(f)

    @objc.python_method
    def _shadowed(self, f):
        """No-op (тінь робила гірше — однотонна тінь зливалась із текстом).
        Читабельність на склі тепер дає молочний tint скла + насиченіший колір
        заголовків, без тіні. Лишено як прохід-пустушка, щоб не правити виклики."""
        return f

    @objc.python_method
    def _keycap_tint(self):
        # окремий tint для keycap — інакше зливається з карткою (та сама поверхня).
        # темна тема — світліший лифт; світла — легке затемнення (інсет-клавіша).
        if self._is_dark():
            return NSColor.colorWithRed_green_blue_alpha_(1, 1, 1, 0.14)
        return NSColor.colorWithRed_green_blue_alpha_(0, 0, 0, 0.06)

    @objc.python_method
    def _cap(self, inner, w=None, h=26.0):
        """Keycap-капсула довкола клавіш хоткея: клавіша ВЦЕНТРОВАНА обома осями."""
        box = self._al(NSBox.alloc().init())
        box.setBoxType_(4); box.setTitlePosition_(0); box.setCornerRadius_(6.0)
        box.setBorderWidth_(1.0); box.setBorderColor_(NSColor.separatorColor())
        box.setFillColor_(self._keycap_tint()); self._keycaps = getattr(self, "_keycaps", [])
        self._keycaps.append(box)
        box.setContentViewMargins_(NSMakeSize(0, 0))
        box.setContentView_(inner)
        NSLayoutConstraint.activateConstraints_([
            inner.centerXAnchor().constraintEqualToAnchor_(box.centerXAnchor()),
            inner.centerYAnchor().constraintEqualToAnchor_(box.centerYAnchor()),
            inner.leadingAnchor().constraintGreaterThanOrEqualToAnchor_constant_(box.leadingAnchor(), 6),
        ])
        box.heightAnchor().constraintEqualToConstant_(h).setActive_(True)
        if w: box.widthAnchor().constraintEqualToConstant_(w).setActive_(True)
        return box

    @objc.python_method
    def _arow(self, left, right, minh=36.0):
        """Рядок картки: left пришпилений ЛІВОРУЧ, right ПРАВОРУЧ — явні констрейнти
        (детерміновано; вкладені NSStackView-gravity «гуляли» → криві контроли)."""
        if isinstance(left, str): left = self._albl(left)
        row = self._al(NSView.alloc().init())
        row.addSubview_(left); row.addSubview_(right)
        H = NSUserInterfaceLayoutOrientationHorizontal
        left.setContentHuggingPriority_forOrientation_(250, H)
        left.setContentCompressionResistancePriority_forOrientation_(490, H)
        right.setContentHuggingPriority_forOrientation_(751, H)
        right.setContentCompressionResistancePriority_forOrientation_(751, H)
        NSLayoutConstraint.activateConstraints_([
            left.leadingAnchor().constraintEqualToAnchor_(row.leadingAnchor()),
            left.centerYAnchor().constraintEqualToAnchor_(row.centerYAnchor()),
            left.topAnchor().constraintGreaterThanOrEqualToAnchor_(row.topAnchor()),
            left.bottomAnchor().constraintLessThanOrEqualToAnchor_(row.bottomAnchor()),
            right.trailingAnchor().constraintEqualToAnchor_(row.trailingAnchor()),
            right.centerYAnchor().constraintEqualToAnchor_(row.centerYAnchor()),
            right.topAnchor().constraintGreaterThanOrEqualToAnchor_(row.topAnchor()),
            right.bottomAnchor().constraintLessThanOrEqualToAnchor_(row.bottomAnchor()),
            right.leadingAnchor().constraintGreaterThanOrEqualToAnchor_constant_(left.trailingAnchor(), 8),
            row.heightAnchor().constraintGreaterThanOrEqualToConstant_(minh)])
        return row

    @objc.python_method
    def _titled(self, lbl, sub=None):
        """Ліва частина рядка: назва + (опц.) сірий підпис під нею."""
        if sub is None: return self._albl(lbl)
        v = self._vstack(1)
        v.addArrangedSubview_(self._albl(lbl))
        s = self._albl(sub, gray=True, size=11.0); v.addArrangedSubview_(s)
        return v

    @objc.python_method
    def _is_dark(self):
        try:
            ap = self._glass.effectiveAppearance() if getattr(self, "_glass", None) else NSApp.effectiveAppearance()
            return "Dark" in str(ap.name())
        except Exception:
            return True

    @objc.python_method
    def _card_tint(self):
        # ПІДНЯТА напівпрозора поверхня: читається як картка АЛЕ пропускає скло.
        # dark — світлий лифт; light — майже-білий фрост.
        if self._is_dark():
            return NSColor.colorWithRed_green_blue_alpha_(1, 1, 1, 0.055)
        return NSColor.colorWithRed_green_blue_alpha_(1, 1, 1, 0.6)

    @objc.python_method
    def _card(self, rows, sep=True, gap=0):
        box = self._al(NSBox.alloc().init())
        box.setBoxType_(4); box.setTitlePosition_(0); box.setCornerRadius_(11.0)
        box.setBorderWidth_(1.0); box.setBorderColor_(NSColor.separatorColor())
        box.setFillColor_(self._card_tint())
        self._cards.append(box)
        box.setContentViewMargins_(NSMakeSize(0, 0))
        inner = self._vstack(gap)               # gap>0 → відступ між блоками (без ліній-роздільників)
        for i, r in enumerate(rows):
            if i > 0 and sep:                      # sep=False → стек без ліній (як у HTML-мокапі)
                ln = self._al(NSBox.alloc().init()); ln.setBoxType_(2)
                inner.addArrangedSubview_(ln)
                ln.heightAnchor().constraintEqualToConstant_(1).setActive_(True)
                self._fillx(ln, inner)             # роздільник на всю ширину картки
            inner.addArrangedSubview_(r)
            self._fillx(r, inner, inset=14)        # рядки — з бічним полем 14
        box.setContentView_(inner)
        self._fillx(inner, box)
        inner.topAnchor().constraintEqualToAnchor_constant_(box.topAnchor(), 5).setActive_(True)
        inner.bottomAnchor().constraintEqualToAnchor_constant_(box.bottomAnchor(), -5).setActive_(True)
        return box

    @objc.python_method
    def _section(self, title, rows, red=False):
        v = self._vstack(7)
        hdr = self._albl(title, size=12.0)
        # насичений напівжирний заголовок — читається на склі без тіні
        hdr.setFont_(NSFont.systemFontOfSize_weight_(12.0, 0.30))   # medium
        if red:
            hdr.setTextColor_(NSColor.systemRedColor())
        else:
            hdr.setTextColor_(NSColor.secondaryLabelColor())
        v.addArrangedSubview_(hdr)
        card = self._card(rows); v.addArrangedSubview_(card); self._fillx(card, v)
        return v

    @objc.python_method
    def _hint(self, text):
        f = self._albl(text, gray=True, size=11.0)
        f.setUsesSingleLineMode_(False)
        try:
            f.cell().setWraps_(True); f.cell().setLineBreakMode_(0)   # 0=word-wrap
        except Exception: pass
        f.setContentHuggingPriority_forOrientation_(250, NSUserInterfaceLayoutOrientationVertical)
        self._shadowed(f)   # читабельність на склі
        # КРИТИЧНО: довгий хінт НЕ мусить розпирати ширину/блокувати ресайз вікна —
        # хай переноситься. Низька compression-resistance по горизонталі = поступається.
        f.setContentCompressionResistancePriority_forOrientation_(
            200, NSUserInterfaceLayoutOrientationHorizontal)
        f.setContentHuggingPriority_forOrientation_(
            200, NSUserInterfaceLayoutOrientationHorizontal)
        return f

    @objc.python_method
    def _aswitch(self, on, action):
        s = self._al(NSSwitch.alloc().init())
        s.setState_(1 if on else 0); s.setTarget_(self); s.setAction_(action)
        return s

    @objc.python_method
    def _apopup(self, items, sel_title, action):
        p = self._al(NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(0, 0, 10, 24), False))
        p.addItemsWithTitles_(items)
        if sel_title and sel_title in items: p.selectItemWithTitle_(sel_title)
        p.setTarget_(self); p.setAction_(action)
        p.widthAnchor().constraintGreaterThanOrEqualToConstant_(160).setActive_(True)
        return p

    @objc.python_method
    def _abtn(self, title, action, danger=False, prim=False, symbol=None, tip=None):
        cls = _DangerButton if danger else NSButton
        b = self._al(cls.alloc().init())
        b.setTitle_(title); b.setBezelStyle_(1)
        b.setTarget_(self); b.setAction_(action)
        if symbol:
            try:
                img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, tip or title)
                if img is not None:
                    b.setImage_(img)
                    b.setImagePosition_(1 if not title else 2)  # 1=ImageOnly 2=ImageLeft
            except Exception: pass
        if tip: b.setToolTip_(tip)
        if prim:
            try: b.setBezelColor_(accent_color())
            except Exception: pass
        if danger:
            b._danger_title = title; b._paint(False)
        return b

    @objc.python_method
    def _build(self):
        W = 660
        try: screenH = NSScreen.mainScreen().visibleFrame().size.height
        except Exception: screenH = 900
        H = int(max(520, min(680, screenH - 80)))
        self.win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskResizable
            | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskFullSizeContentView,
            NSBackingStoreBuffered, False)
        self.win.setMinSize_((600, 460))
        self.win.setMaxSize_((100000, 100000))     # без штучного обмеження ширини
        self.win.setCollectionBehavior_(1 << 9)    # FullScreenNone
        self.win.setTitle_("KobzarAI — Налаштування")
        self.win.setTitleVisibility_(1)            # NSWindowTitleHidden
        self.win.setTitlebarAppearsTransparent_(True)
        self.win.setOpaque_(False)
        self.win.setBackgroundColor_(NSColor.clearColor())
        self.win.setDelegate_(self)
        self.win.setReleasedWhenClosed_(False)
        self.win.center()
        # скляна підкладка — СПРАВЖНЄ Liquid Glass (NSGlassEffectView): десктоп
        # заломлюється по контуру (лінза), текст чіткий. transp-слайдер керує
        # fill-overlay (0=твердо як System Settings, 100=повне скло).
        if _HAS_GLASS:
            glass = NSGlassEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))
            try: glass.setStyle_(_GLASS_REGULAR)     # матове скло з обережним блюром
            except Exception: pass
            # contentLensing вимкнено: безперервне заломлення рухомого десктопу = головний
            # GPU-кошт (WindowServer роздувався при відкритому вікні на 8 ГБ). Блюр+прозорість
            # лишаються; зникає лише переливання по краю. Вмикається назад при потребі.
            try: glass.set_contentLensing_(False)
            except Exception: pass
            glass.setAutoresizingMask_(18)
            host = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))
            host.setAutoresizingMask_(18)
            glass.setContentView_(host)
            self.win.setContentView_(glass)
            self._glass = glass; self._host = host
        else:
            glass = make_glass(NSMakeRect(0, 0, W, H), NSVisualEffectMaterialUnderWindowBackground)
            glass.setAutoresizingMask_(18)
            self.win.setContentView_(glass)
            self._glass = glass; self._host = glass
        self._apply_transp(glass)
        host = self._host
        # — сегмент-навігація в UNIFIED-тулбарі —
        # macOS САМ центрує світлофор по висоті тулбара (як System Settings), тож
        # світлофор і сегмент стають на одну лінію без ручного зсуву кнопок (той ламався:
        # кнопки живуть у 32px-тайтлбарі, нижче не влазять). Бонус: сегмент «плаває
        # скляний» над контентом, що скролиться під ним (узгоджено з fade зверху).
        _labels = ["Загальні", "Голос", "Моделі", "Чат"] + [t["title"] for t in self._ext_tabs()]
        self._segw = 88 * len(_labels)                # 352 для чотирьох, 440 для п'яти
        seg = SlidingSegment.alloc().initWithLabels_frame_(_labels, NSMakeRect(0, 0, self._segw, 30))
        self._al(seg)
        seg.setSelectedSegment_(0); seg.setTarget_action_(self, "tabChanged:")
        # trackless: власну track-плашку НЕ малюємо — її роль грає скляна капсула
        # unified-тулбара (macOS малює сам під центрованим item). Інакше дві плашки
        # накладались концентрично (track сегмента + капсула тулбара).
        seg.setTrackless_(True)
        seg.widthAnchor().constraintEqualToConstant_(self._segw).setActive_(True)
        seg.heightAnchor().constraintEqualToConstant_(30).setActive_(True)
        self.seg = seg
        tb = NSToolbar.alloc().initWithIdentifier_("kobzar.settings.nav")
        tb.setDelegate_(self)
        tb.setAllowsUserCustomization_(False)
        try: tb.setCenteredItemIdentifiers_({"nav"})        # macOS 13+
        except Exception:
            try: tb.setCenteredItemIdentifier_("nav")        # 11–12
            except Exception: pass
        self.win.setToolbar_(tb)
        try: self.win.setToolbarStyle_(NSWindowToolbarStyleUnified)
        except Exception: pass
        # — скрол на ВСЮ висоту host; контент заходить ПІД тулбар, fade згори —
        scroll = self._al(_FadeScrollView.alloc().init())
        clip = _TopClipView.alloc().init()      # перевернутий clip → контент пришпилений до ВЕРХУ
        clip.setDrawsBackground_(False)         # прозорий → скло видно крізь скрол
        scroll.setContentView_(clip)
        scroll.setDrawsBackground_(False); scroll.setHasVerticalScroller_(True)
        scroll.setAutohidesScrollers_(True)
        host.addSubview_(scroll); self._scroll = scroll
        NSLayoutConstraint.activateConstraints_([
            scroll.topAnchor().constraintEqualToAnchor_(host.topAnchor()),
            scroll.leadingAnchor().constraintEqualToAnchor_(host.leadingAnchor()),
            scroll.trailingAnchor().constraintEqualToAnchor_(host.trailingAnchor()),
            scroll.bottomAnchor().constraintEqualToAnchor_(host.bottomAnchor())])
        self._pages = {}
        self.tabs = None
        self.select_tab(0)
        try:    # тест-хук (прибрати перед релізом): відкрити одразу на вкладці N
            _t = int(os.environ.get("KOBZARAI_TAB", "0"))
            if _t: self.seg.setSelectedSegment_(_t); self.select_tab(_t)
        except Exception: pass
        # верхній відступ контенту = висота тулбара (контент стартує ПІД ним, скролиться під низ)
        AppHelper.callAfter(self._sync_top_inset)

    # ── unified-тулбар: делегат + синхронізація верхнього відступу контенту ──
    def toolbarDefaultItemIdentifiers_(self, tb): return ["nav"]
    def toolbarAllowedItemIdentifiers_(self, tb): return ["nav"]

    def toolbar_itemForItemIdentifier_willBeInsertedIntoToolbar_(self, tb, ident, flag):
        if str(ident) != "nav":
            return None
        it = NSToolbarItem.alloc().initWithItemIdentifier_("nav")
        it.setView_(self.seg)
        _w = getattr(self, "_segw", 440)
        it.setMinSize_(NSMakeSize(_w, 30)); it.setMaxSize_(NSMakeSize(_w, 30))
        return it

    @objc.python_method
    def _sync_top_inset(self):
        """Верхній відступ скролу = висота тулбара: контент починається під сегментом,
        але вільно заходить під нього при скролі (де його перехоплює fade)."""
        sc = getattr(self, "_scroll", None)
        if sc is None or self.win is None:
            return
        try:
            wh = self.win.contentView().frame().size.height
            top = max(0.0, wh - self.win.contentLayoutRect().size.height)
        except Exception:
            top = 52.0
        if top <= 0:
            top = 52.0
        try:
            sc.setAutomaticallyAdjustsContentInsets_(False)
            sc.setContentInsets_((top, 0.0, 0.0, 0.0))      # NSEdgeInsets (top,left,bottom,right)
            sc.setScrollerInsets_((top, 0.0, 0.0, 0.0))
            sc._layout_mask()
        except Exception:
            pass

    @objc.python_method
    def _page(self, children):
        v = self._vstack(18)
        for c in children:
            v.addArrangedSubview_(c); self._fillx(c, v)
        return v

    @objc.python_method
    def _group(self, section, hint=None):
        """Секція + (опц.) хінт, приклеєний під картку малим проміжком."""
        if hint is None: return section
        v = self._vstack(5)
        v.addArrangedSubview_(section); self._fillx(section, v)
        h = self._hint(hint); v.addArrangedSubview_(h); self._fillx(h, v)
        return v

    @objc.python_method
    def _page_general(self, *_):
        cfg = load_cfg()
        hk = cfg.get("hotkeys", DEFAULT_HOTKEYS)
        # — Глобальні хоткеї —
        rows = []
        for idx, (act, title) in enumerate(HK_LABELS):
            kbd = self._albl(fmt_hotkey(hk.get(act)) or "—")
            kbd.setTextColor_(NSColor.labelColor())    # повний колір — клавіша читабельна
            kbd.setFont_(NSFont.monospacedSystemFontOfSize_weight_(13.5, 0.30))
            kbd.setAlignment_(2)                       # центр у капсулі
            self.hk_btns[act] = kbd
            cap = self._cap(kbd, w=128)                # фікс-ширина → столбець вирівняний
            b = self._abtn("Записати", "recordHK:"); b.setTag_(idx)
            rst = self._abtn("", "clearHK:", symbol="arrow.uturn.backward",
                             tip="Скинути хоткей"); rst.setTag_(idx)
            trio = self._hstack(8)
            for w in (cap, b, rst): trio.addArrangedSubview_(w)
            rows.append(self._arow(title, trio))
        hk_sec = self._section("Глобальні хоткеї", rows)
        # — Вигляд —
        theme = self._apopup(THEMES, cfg.get("theme", "Авто"), "themeChanged:")
        # той самий slider-рядок, що й у Голосі (Швидкість/Гучність) — однакова підкладка
        trow, self.transp_sl, self.transp_val = self._aslider_row(
            "Прозорість фону", 0, 100, int(cfg.get("transp", 20)), "transpChanged:",
            lambda x: "%d%%" % int(x))
        look = self._section("Вигляд", [self._arow("Тема", theme), trow])
        # — Автозапуск —
        self.auto_login = self._aswitch(cfg.get("autostart_login"), "autoLoginToggled:")
        self.auto_oll = self._aswitch(cfg.get("autostart_ollama"), "autoOllToggled:")
        self.auto_tts = self._aswitch(cfg.get("autostart_tts"), "autoTtsToggled:")
        auto = self._section("Автозапуск", [
            self._arow("Разом із входом у систему", self.auto_login),
            self._arow("Ollama", self.auto_oll),
            self._arow("Озвучення (TTS)", self.auto_tts)])
        # — Оптимізація Ollama —
        self.opt_flash = self._aswitch(cfg.get("ollama_flash", True), "optFlashToggled:")
        self.opt_kv = self._aswitch(cfg.get("ollama_kv_q8", True), "optKvToggled:")
        opt = self._section("Оптимізація Ollama (8 ГБ)", [
            self._arow(self._titled("Flash Attention", "швидше, менше RAM на контекст"), self.opt_flash),
            self._arow(self._titled("KV-кеш 8-біт", "~вдвічі менше памʼяті (потребує Flash)"), self.opt_kv)])
        # — Термозахист (thermal.py читає config щоразу → діє одразу, і для Кобзаря, і для бібліотекаря) —
        self.th_on = self._aswitch(cfg.get("thermal_on", True), "thermOnToggled:")
        self.th_now = self._albl(self._therm_now_txt(), gray=True)
        therm = self._section("Термозахист", [
            self._arow(self._titled("Пауза при перегріві",
                                    "ембед і пошук чекають, поки Mac охолоне — у треї ❄️"), self.th_on),
            self._arow(self._titled("Поріг паузи",
                                    "продовження на 8° нижче · Air без кулера 90–92, Pro 100+"), self._atherm()),
            self._arow("Температура SoC зараз", self.th_now)])
        # — Чати —
        self.chats_field = self._afield("")             # редаговане поле — як Папка моделей
        self.chats_field.setStringValue_(chats_dir())
        self.chats_field.setFont_(NSFont.monospacedSystemFontOfSize_weight_(11.5, 0.0))
        chats_btns = self._hstack_pair(
            self._abtn("", "browseChatsDir:", symbol="folder", tip="Огляд…"),
            self._abtn("Застосувати", "applyChatsDir:"))
        chats = self._section("Чати", [self._arow(self.chats_field, chats_btns)])
        # — База знань (RAG) —
        # Готові індекси: НЕ переembedимо мільйони токенів — читаємо вже пораховане
        # (librarian та ін.) через sqlite-vec. Внизу — альтернатива: своя тека з нуля.
        self._kb_index_paths = [""]                # 0 = «готового не використовувати»
        opts = ["— готовий індекс не обрано —"]
        try:
            import kb as _kbmod
            for it in _kbmod.discover_indexes():
                top = sorted(it["sources"].items(), key=lambda kv: -kv[1])[:2]
                lbl = os.path.basename(os.path.dirname(it["path"])) or os.path.basename(it["path"])
                tail = (" · " + ", ".join(s for s, _ in top)) if top else ""
                opts.append("%s · %d фрагм%s" % (lbl, it["chunks"], tail))
                self._kb_index_paths.append(it["path"])
        except Exception:
            pass
        self.kb_index_pop = self._apopup(opts, opts[0], "kbIndexChanged:")
        if self.kb_index in self._kb_index_paths:
            self.kb_index_pop.selectItemAtIndex_(self._kb_index_paths.index(self.kb_index))
        self.kb_field = self._afield("або тека з нотатками (.md, .txt) для власного індексу…")
        self.kb_field.setStringValue_(self.kb_folder)
        self.kb_field.setFont_(NSFont.monospacedSystemFontOfSize_weight_(11.5, 0.0))
        self.kb_status = self._albl(self._kb_status_text(), gray=True)
        self.kb_browse_btn = self._abtn("", "browseKbDir:", symbol="folder", tip="Обрати теку…")
        self.kb_index_btn = self._abtn("Проіндексувати", "reindexKb:")
        kb_btns = self._hstack_pair(self.kb_browse_btn, self.kb_index_btn)
        kb_sec = self._section("База знань", [
            self._arow("Готовий індекс", self.kb_index_pop),
            self._arow(self.kb_field, kb_btns),
            self._arow("Стан", self.kb_status)])
        self._kb_sync_controls()
        # — Небезпечна зона —
        danger = self._section("Небезпечна зона", [self._arow(
            self._titled("Видалити KobzarAI",
                         "зупинить сервіси й безповоротно зітре застосунок, лаунчер і TTS"),
            self._abtn("Видалити…", "uninstallApp:", danger=True))], red=True)
        return self._page([
            self._group(hk_sec, "«Записати» → натисни комбо. Esc — скасувати."),
            self._group(look),
            self._group(auto, "Ollama та голос стартують самі при відкритті застосунку."),
            self._group(opt, "Діє при наступному старті Ollama (СТОП → Старт у меню)."),
            self._group(therm, "Вимкни на Mac з активним кулером (MacBook Pro), якщо не треба."),
            self._group(chats, "Кожен чат — окремий .json. Зміна теки стосується подальших."
                        + ("" if _addon is not None else
                           " Є окрема приватна версія з чатами в браузері — напиши @steptonite.")),
            self._group(kb_sec, "Локальний семантичний пошук по обраній теці (Ollama bge-m3). "
                                "Тумблер «книжки» у полі чату вмикає використання."),
            self._group(danger, "Моделі на зовнішньому диску НЕ чіпаються.")])

    @objc.python_method
    def _hstack_pair(self, a, b):
        h = self._hstack(8); h.addArrangedSubview_(a); h.addArrangedSubview_(b)
        return h

    @objc.python_method
    def _aslider_row(self, title, mn, mx, val, action, valfmt):
        """Рядок: лейбл · нативний слайдер (розпирається) · значення праворуч.
        Повертає (row, slider, value_label)."""
        sl = self._al(NSSlider.alloc().init())
        sl.setMinValue_(mn); sl.setMaxValue_(mx); sl.setFloatValue_(float(val))
        sl.setContinuous_(True); sl.setTarget_(self); sl.setAction_(action)
        sl.setContentHuggingPriority_forOrientation_(1, NSUserInterfaceLayoutOrientationHorizontal)
        vlbl = self._albl(valfmt(val), gray=True)
        vlbl.widthAnchor().constraintEqualToConstant_(56).setActive_(True)
        tlbl = self._albl(title)
        tlbl.widthAnchor().constraintGreaterThanOrEqualToConstant_(150).setActive_(True)
        tlbl.setContentHuggingPriority_forOrientation_(250, NSUserInterfaceLayoutOrientationHorizontal)
        row = self._hstack(10)
        for w in (tlbl, sl, vlbl): row.addArrangedSubview_(w)
        row.heightAnchor().constraintGreaterThanOrEqualToConstant_(36).setActive_(True)
        return row, sl, vlbl

    @objc.python_method
    def _page_voice(self, *_):
        p = self.panel
        # — Озвучення —
        refresh_voices()                    # сервер = джерело правди, не константа
        voice = self._apopup([voice_label(x) for x in VOICES],
                             voice_label(getattr(p, "voice", VOICES[0])), "voiceChanged:")
        self.voice_pop = voice              # тримаємо посилання: список оновлюється на кожному show()
        srow, self.speed_sl, self.speed_val = self._aslider_row(
            "Швидкість", 0.7, 1.3, getattr(p, "speed", 1.0), "speedChanged:",
            lambda x: f"×{x:.2f}")
        vrow, self.vol_sl, self.vol_val = self._aslider_row(
            "Гучність", 0.0, 1.0, getattr(p, "volume", 0.85), "volumeChanged:",
            lambda x: f"{int(round(x * 100))}%")
        prow, self.pause_sl, self.pause_val = self._aslider_row(
            "Пауза між реченнями", 0.0, 0.5, getattr(p, "pause", 0.15), "pauseChanged:",
            lambda x: f"{x:.2f} с")
        listen = self._abtn("Прослухати", "previewVoice:")
        self.listen_btn = listen
        listen.heightAnchor().constraintEqualToConstant_(30).setActive_(True)
        voc = self._section("Озвучення", [
            self._arow("Голос моделі", voice), srow, vrow, prow,
            self._arow("Зразок голосу", listen)])
        # — Режим озвучення (сегмент, що їде) —
        mode = SlidingSegment.alloc().initWithLabels_frame_(
            ["Базово", "Швидко", "Наживо"], NSMakeRect(0, 0, 280, 28))
        self._al(mode)
        mode.setSelectedSegment_({"base": 0, "stream": 1, "realtime": 2}.get(tts_mode(), 0))
        mode.setTarget_action_(self, "ttsModeChanged:")
        mode.widthAnchor().constraintEqualToConstant_(280).setActive_(True)
        mode.heightAnchor().constraintEqualToConstant_(28).setActive_(True)
        self.tts_mode = mode
        mode_sec = self._section("Режим озвучення", [self._arow("Режим", mode)])
        # — Оптимізація RAM —
        idle = self._apopup(TTS_IDLE_LABELS, TTS_IDLE_LABELS[tts_idle_index()], "ttsIdleChanged:")
        self.tts_idle = idle
        ram_sec = self._section("Оптимізація RAM (8 ГБ)", [self._arow(
            self._titled("Вивантажити TTS",
                         "після N хв без озвучки звільнити ~2 ГБ; наступний голос — холодний старт ~20 c"),
            idle)])
        # — Вивід звуку —
        op = self._al(NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(0, 0, 10, 24), False))
        op.addItemWithTitle_("Системний за замовч.")
        self._out_uids = [None]
        cur = getattr(p, "out_device", None)
        for nm, uid in audio_outputs():
            op.addItemWithTitle_(nm); self._out_uids.append(uid)
            if uid == cur: op.selectItemAtIndex_(len(self._out_uids) - 1)
        op.setTarget_(self); op.setAction_("outDeviceChanged:")
        op.widthAnchor().constraintGreaterThanOrEqualToConstant_(160).setActive_(True)
        self.out_pop = op
        out_sec = self._section("Вивід звуку", [self._arow("Пристрій виводу", op)])
        return self._page([
            voc,
            # пояснення режимів приклеєне ПІД секцію «Режим озвучення» (повернуто)
            self._group(mode_sec,
                "Базово — цілим файлом (рівніший тембр).\n"
                "Швидко — миттєвий старт.\n"
                "Наживо — озвучує поки модель пише (лише у вбудованому чаті)."),
            self._group(ram_sec,
                "«Ніколи» — тримати голос у RAM завжди (швидше, але −2 ГБ)."),
            self._group(out_sec,
                "За замовч. — поточний вихід системи. Діє на нову озвучку.")])
    @objc.python_method
    def _afield(self, placeholder=""):
        """Нативне однорядкове поле (констрейнти, без піксельних координат)."""
        f = self._al(NSTextField.alloc().init())
        f.setEditable_(True); f.setBezeled_(True); f.setBezelStyle_(0)
        if placeholder: f.setPlaceholderString_(placeholder)
        f.setFocusRingType_(1); f.setUsesSingleLineMode_(True)
        try:
            c = f.cell(); c.setScrollable_(True); c.setWraps_(False); c.setLineBreakMode_(5)
        except Exception: pass
        f.setContentHuggingPriority_forOrientation_(250, NSUserInterfaceLayoutOrientationHorizontal)
        f.heightAnchor().constraintEqualToConstant_(24).setActive_(True)
        return f

    @objc.python_method
    def _mk_step(self, sym, tag, action="tokStep:"):
        b = self._al(_HoverButton.alloc().init())
        b.setBordered_(False); b.setTitle_(sym); b.setFont_(NSFont.systemFontOfSize_(16.0))
        b.setTag_(tag); b.setTarget_(self); b.setAction_(action)
        b.widthAnchor().constraintEqualToConstant_(32).setActive_(True)
        return b

    @objc.python_method
    def _atok(self):
        """Нативний степер ± «Відповідь, токенів» у заокругленій плашці."""
        try: self.tok_idx = TOKEN_OPTS.index(str(load_cfg().get("num_predict", 2048)))
        except ValueError: self.tok_idx = 2
        box = self._al(NSBox.alloc().init())
        box.setBoxType_(4); box.setTitlePosition_(0); box.setCornerRadius_(7.0)
        box.setBorderWidth_(1.0); box.setBorderColor_(NSColor.separatorColor())
        box.setFillColor_(self._card_tint()); self._cards.append(box)
        box.setContentViewMargins_(NSMakeSize(0, 0))
        minus = self._mk_step("−", -1); plus = self._mk_step("+", 1)
        self.tok_num = self._albl(TOKEN_OPTS[self.tok_idx]); self.tok_num.setAlignment_(2)
        self.tok_num.widthAnchor().constraintEqualToConstant_(52).setActive_(True)
        h = self._hstack(0)
        for w in (minus, self.tok_num, plus): h.addArrangedSubview_(w)
        box.setContentView_(h); self._fillx(h, box)
        h.topAnchor().constraintEqualToAnchor_(box.topAnchor()).setActive_(True)
        h.bottomAnchor().constraintEqualToAnchor_(box.bottomAnchor()).setActive_(True)
        box.heightAnchor().constraintEqualToConstant_(28).setActive_(True)
        box.widthAnchor().constraintEqualToConstant_(124).setActive_(True)
        return box

    @objc.python_method
    def _atherm(self):
        """Степер ± порогу термо-паузи (°C) — та сама плашка, що «Відповідь, токенів»."""
        cur = int(load_cfg().get("thermal_cool_at", 92))
        self.th_idx = min(range(len(THERM_OPTS)), key=lambda i: abs(THERM_OPTS[i] - cur))
        box = self._al(NSBox.alloc().init())
        box.setBoxType_(4); box.setTitlePosition_(0); box.setCornerRadius_(7.0)
        box.setBorderWidth_(1.0); box.setBorderColor_(NSColor.separatorColor())
        box.setFillColor_(self._card_tint()); self._cards.append(box)
        box.setContentViewMargins_(NSMakeSize(0, 0))
        minus = self._mk_step("−", -1, "thermStep:"); plus = self._mk_step("+", 1, "thermStep:")
        self.th_num = self._albl("%d°C" % THERM_OPTS[self.th_idx]); self.th_num.setAlignment_(2)
        self.th_num.widthAnchor().constraintEqualToConstant_(52).setActive_(True)
        h = self._hstack(0)
        for w in (minus, self.th_num, plus): h.addArrangedSubview_(w)
        box.setContentView_(h); self._fillx(h, box)
        h.topAnchor().constraintEqualToAnchor_(box.topAnchor()).setActive_(True)
        h.bottomAnchor().constraintEqualToAnchor_(box.bottomAnchor()).setActive_(True)
        box.heightAnchor().constraintEqualToConstant_(28).setActive_(True)
        box.widthAnchor().constraintEqualToConstant_(124).setActive_(True)
        return box

    @objc.python_method
    def _therm_now_txt(self):
        try:
            import thermal as _th
            t = _th.read_max()
        except Exception:
            t = None
        if t is None:
            return "датчик недоступний — пауза не спрацює"
        cfg = load_cfg()
        if not cfg.get("thermal_on", True):
            return "%.0f°C · захист вимкнено" % t
        ca = int(cfg.get("thermal_cool_at", 92))
        return "%.0f°C · пауза з %d°C" % (t, ca) + ("  🔥" if t >= ca else "")

    @objc.python_method
    def _actx(self):
        """Степер ± «Контекст, токенів» (num_ctx) — скільки тексту модель «памʼятає»
        за раз. Крокає по CTX_OPTS; стан → self.ctx_idx, cfg num_ctx."""
        try: self.ctx_idx = CTX_OPTS.index(str(load_cfg().get("num_ctx", 4096)))
        except ValueError: self.ctx_idx = 1
        box = self._al(NSBox.alloc().init())
        box.setBoxType_(4); box.setTitlePosition_(0); box.setCornerRadius_(7.0)
        box.setBorderWidth_(1.0); box.setBorderColor_(NSColor.separatorColor())
        box.setFillColor_(self._card_tint()); self._cards.append(box)
        box.setContentViewMargins_(NSMakeSize(0, 0))
        minus = self._mk_step("−", -1, "ctxStep:"); plus = self._mk_step("+", 1, "ctxStep:")
        self.ctx_num = self._albl(CTX_OPTS[self.ctx_idx]); self.ctx_num.setAlignment_(2)
        self.ctx_num.widthAnchor().constraintEqualToConstant_(52).setActive_(True)
        h = self._hstack(0)
        for w in (minus, self.ctx_num, plus): h.addArrangedSubview_(w)
        box.setContentView_(h); self._fillx(h, box)
        h.topAnchor().constraintEqualToAnchor_(box.topAnchor()).setActive_(True)
        h.bottomAnchor().constraintEqualToAnchor_(box.bottomAnchor()).setActive_(True)
        box.heightAnchor().constraintEqualToConstant_(28).setActive_(True)
        box.widthAnchor().constraintEqualToConstant_(124).setActive_(True)
        return box

    # ═══ Місце для доповнень: додаткові вкладки налаштувань і обробник чату ═══
    @objc.python_method
    def _ext_tabs(self):
        """[{key, title, build(вікно), show(вікно)}] від доповнення; порожньо, якщо його нема."""
        tabs = getattr(self, "_ext_tabs_c", None)
        if tabs is None:
            try: tabs = list(_addon.tabs()) if _addon is not None else []
            except Exception: tabs = []
            self._ext_tabs_c = tabs
        return tabs

    @objc.python_method
    def _ext_tab_index(self, key):
        for n, t in enumerate(self._ext_tabs()):
            if t.get("key") == key:
                return 4 + n
        return None

    @objc.python_method
    def _ext_page_extras(self, page):
        """Додаткові секції доповнення на стандартній сторінці (напр. «models»)."""
        if _addon is None:
            return []
        try: return list(_addon.page_sections(self, page))
        except Exception: return []

    @objc.python_method
    def _ext(self):
        """Обробник чату від доповнення (або None). Створюється один раз на вікно."""
        h = getattr(self, "_ext_h", False)
        if h is False:
            h = None
            if _addon is not None:
                try:
                    h = _addon.chat_hook(self, {"save_chat": save_chat, "att_view": att_view,
                                                "embed": _embed_local_media,
                                                "call_after": AppHelper.callAfter})
                except Exception:
                    h = None
            self._ext_h = h
        return h

    @objc.python_method
    def _ext_owns(self, m):
        """Повідомлення історії належить доповненню (у локальну модель не йде)."""
        h = self._ext()
        try: return bool(h is not None and h.owns(m))
        except Exception: return False

    @objc.python_method
    def _chat_cmds(self):
        """[[токен, опис]] для меню чату (@ і /). Без доповнення меню порожнє."""
        h = self._ext()
        if h is None:
            return []
        try: return h.commands()
        except Exception: return []

    @objc.python_method
    def _page_models(self, *_):
        # — Активна модель —
        self.model_pop = self._al(NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(0, 0, 10, 24), False))
        self.model_pop.setTarget_(self); self.model_pop.setAction_("modelChanged:")
        self.model_pop.setFocusRingType_(1)
        self.model_pop.widthAnchor().constraintGreaterThanOrEqualToConstant_(220).setActive_(True)
        # ── два РІВНОЦІННІ слоти RAM (Ollama MAX_LOADED=2: будь-які дві моделі, що влазять) ──
        # слот 2 з'являється, лише коли слот 1 зайнятий; кожен вивантажується окремо
        self.slot_name, self.slot_sub, self.slot_btn, self.slot_row = [], [], [], []
        self._slot_models = ["", ""]
        slot_rows = []
        for i in range(2):
            nm = self._albl("—")
            try: nm.cell().setLineBreakMode_(5)            # довгий HF-шлях обрізається посередині
            except Exception: pass
            sub = self._albl("слот %d · вільний" % (i + 1), gray=True, size=11.0)
            v = self._vstack(1); v.addArrangedSubview_(nm); v.addArrangedSubview_(sub)
            b = self._abtn("Вивантажити", "unloadSlot:", symbol="eject")
            b.setTag_(i)
            row = self._arow(v, b)
            nm.setContentCompressionResistancePriority_forOrientation_(
                1, NSUserInterfaceLayoutOrientationHorizontal)
            self.slot_name.append(nm); self.slot_sub.append(sub)
            self.slot_btn.append(b); self.slot_row.append(row); slot_rows.append(row)
        self.loaded_lbl = self.slot_name[0]               # сумісність: «вкладка Моделі збудована»
        self.load_btn = self._abtn("У RAM", "loadModel:", symbol="arrow.down.circle")
        delete = self._abtn("Видалити", "deleteModel:", danger=True)
        active = self._section("Активна модель", [
            self._arow("Модель", self.model_pop),
            self._arow(self.load_btn, delete)] + slot_rows)
        # лінія-роздільник над слотом 2 ховається разом із ним
        try:
            sibs = list(self.slot_row[1].superview().arrangedSubviews())
            self._slot2_sep = sibs[sibs.index(self.slot_row[1]) - 1]
        except Exception:
            self._slot2_sep = None
        self.model_pop.setContentCompressionResistancePriority_forOrientation_(
            1, NSUserInterfaceLayoutOrientationHorizontal)
        try: self.model_pop.cell().setLineBreakMode_(5)   # TruncatingMiddle
        except Exception: pass
        # — Генерація —
        gen = self._section("Генерація", [
            self._arow(
                self._titled("Відповідь, токенів", "довша відповідь — більше RAM і часу"),
                self._atok()),
            self._arow(
                self._titled("Контекст, токенів", "скільки тексту модель памʼятає — більше RAM"),
                self._actx())])
        # — Завантажити нову —
        self.pull_field = self._afield("qwen3:4b-instruct-2507-q4_K_M")
        self.pull_field.setStringValue_("qwen3:4b-instruct-2507-q4_K_M")
        self.pull_field.setDelegate_(self)
        # ✕ всередині поля справа — стерти весь текст одним кліком
        self.pull_clear = self._abtn("", "clearPull:", symbol="xmark", tip="Очистити")
        self.pull_clear.setBordered_(False)
        self.pull_field.addSubview_(self.pull_clear)
        NSLayoutConstraint.activateConstraints_([
            self.pull_clear.trailingAnchor().constraintEqualToAnchor_constant_(
                self.pull_field.trailingAnchor(), -4),
            self.pull_clear.centerYAnchor().constraintEqualToAnchor_(
                self.pull_field.centerYAnchor()),
            self.pull_clear.widthAnchor().constraintEqualToConstant_(18),
            self.pull_clear.heightAnchor().constraintEqualToConstant_(18)])
        self.pull_btn = self._abtn("Завантажити", "doPull:", symbol="square.and.arrow.down")
        self.pull_bar = self._al(NSProgressIndicator.alloc().init())
        self.pull_bar.setStyle_(0); self.pull_bar.setIndeterminate_(False)
        self.pull_bar.setMinValue_(0.0); self.pull_bar.setMaxValue_(100.0)
        self.pull_bar.setHidden_(True)
        self.pull_bar.heightAnchor().constraintEqualToConstant_(8).setActive_(True)
        # скасування — лише поки триває завантаження (симетрично з show/hide pull_bar)
        self.pull_cancel_btn = self._abtn("Скасувати", "cancelPull:", symbol="xmark.circle")
        self.pull_cancel_btn.setHidden_(True)
        self.pull_status = self._albl("ollama.com/library  ·  hf.co/<repo>:Q4_K_M",
                                      gray=True, size=11.0)
        try: self.pull_status.cell().setLineBreakMode_(5)
        except Exception: pass
        # картка лише з полем+кнопкою; прогрес-бар і підказка — ПІД карткою (без
        # розділювачів-ліній, що з'являлись між рядками картки → виглядало брудно).
        pull = self._section("Завантажити нову", [
            self._arow(self.pull_field, self.pull_btn)])
        pull.addArrangedSubview_(self.pull_bar); self._fillx(self.pull_bar, pull)
        pull.addArrangedSubview_(self.pull_cancel_btn)
        pull.addArrangedSubview_(self.pull_status); self._fillx(self.pull_status, pull)
        self._update_pull_btn()
        # — Папка моделей —
        self.models_field = self._afield("")
        self.models_field.setStringValue_(models_dir())
        self.models_field.setFont_(NSFont.monospacedSystemFontOfSize_weight_(11.5, 0.0))
        mdir_btns = self._hstack_pair(
            self._abtn("", "browseModelsDir:", symbol="folder", tip="Огляд…"),
            self._abtn("Застосувати", "applyModelsDir:"))
        mdir = self._section("Папка моделей", [self._arow(self.models_field, mdir_btns)])
        # — Бібліотека моделей —
        self.lib_seg = SlidingSegment.alloc().initWithLabels_frame_(
            ["Ollama", "HuggingFace"], NSMakeRect(0, 0, 210, 28))
        self._al(self.lib_seg); self.lib_seg.setSelectedSegment_(1)
        self.lib_seg.setTarget_action_(self, "sourceChanged:")
        self.lib_seg.widthAnchor().constraintEqualToConstant_(210).setActive_(True)
        self.lib_seg.heightAnchor().constraintEqualToConstant_(28).setActive_(True)
        self.lib_refresh_btn = self._abtn("", "libRefresh:", symbol="arrow.clockwise",
                                          tip="Оновити список")
        self.lib_sortpop = self._apopup(
            ["Сортувати: розмір ↑", "Сортувати: завантаження ↓", "Сортувати: назва"],
            "Сортувати: розмір ↑", "sortChanged:")
        self.lib_search = self._afield("Пошук моделі…")
        self.lib_search.setTarget_(self); self.lib_search.setAction_("libSearch:")
        sc = self._al(NSScrollView.alloc().init())
        sc.setHasVerticalScroller_(True); sc.setBorderType_(0)   # без квадратного bezel — список лежить на площині картки
        sc.setDrawsBackground_(False); sc.setFocusRingType_(1)
        sc.setWantsLayer_(True)                                  # заокруглені кути блоку-списку → не читається квадратом
        sc.layer().setCornerRadius_(8.0); sc.layer().setMasksToBounds_(True)
        sc.heightAnchor().constraintEqualToConstant_(240).setActive_(True)
        table = NSTableView.alloc().initWithFrame_(NSMakeRect(0, 0, 400, 240))
        table.setRowHeight_(26.0); table.setHeaderView_(None); table.setFocusRingType_(1)
        table.setBackgroundColor_(NSColor.clearColor()); table.setColumnAutoresizingStyle_(1)
        table.setSelectionHighlightStyle_(-1)       # None: AppKit не малює повноширинний прямокутник → заокруглену дає ChatRowView (як список чатів)
        table.setAllowsMultipleSelection_(False)    # рівно одна модель за раз (баг «вибираються декілька»)
        table.setAllowsEmptySelection_(True); table.setAllowsColumnSelection_(False)
        table.setGridStyleMask_(2)                  # тонкі горизонтальні hairline між рядками (як у HTML)
        try: table.setGridColor_(NSColor.separatorColor())
        except Exception: pass
        table.setIntercellSpacing_(NSMakeSize(0, 0))
        cN = NSTableColumn.alloc().initWithIdentifier_("name"); cN.setWidth_(300)
        cS = NSTableColumn.alloc().initWithIdentifier_("size"); cS.setWidth_(80)
        cS.dataCell().setAlignment_(2); cS.dataCell().setTextColor_(NSColor.secondaryLabelColor())
        table.addTableColumn_(cN); table.addTableColumn_(cS)
        table.setDataSource_(self); table.setDelegate_(self)
        table.setTarget_(self); table.setDoubleAction_("libPick:")
        sc.setDocumentView_(table); self.lib_table = table
        self.lib_empty = self._albl("", gray=True); self.lib_empty.setHidden_(True)
        self.lib_detail = self._albl(
            "Подвійний клік — у поле «Завантажити».  HF → hf.co/repo:Q4_K_M",
            gray=True, size=11.0)
        lib_hdr = self._albl("Бібліотека моделей", gray=True, size=12.0)
        # ЄДИНА картка (як у HTML-мокапі): керування + пошук + сам список разом,
        # sep=False → без товстих ліній-роздільників між блоками всередині.
        lib_card = self._card([
            self._arow(self.lib_seg,
                       self._hstack_pair(self.lib_sortpop, self.lib_refresh_btn)),
            self.lib_search,
            sc], sep=False, gap=8)
        lib = self._vstack(7)
        for c in (lib_hdr, lib_card, self.lib_empty, self.lib_detail):
            lib.addArrangedSubview_(c); self._fillx(c, lib)
        # стан бібліотеки
        self.lib_all = []; self.lib_filtered = []
        self.lib_size_cache = {}; self.lib_size_pending = set()
        self._size_prefetch_busy = False
        self.lib_source = "hf"; self.lib_sort = "size"; self.lib_online = True
        # ЄДИНА підказка-джерело: pull_status (він же показує прогрес завантаження).
        # Дубль-хінт під карткою прибрано — дві однакові строчки не мали сенсу.
        page = self._page([active, gen, pull,
            self._group(mdir, "Стандартний шлях Ollama: ~/.ollama/models · "
                              "Після зміни — перезапусти Ollama в меню панелі."),
            lib] + self._ext_page_extras("models"))
        try:
            self.reload_models(); self._refresh_library()
        except Exception: pass
        return page

    @objc.python_method
    def _accent_css(self):
        """Системний акцент (NSColor.controlAccentColor) → rgb(...) для CSS-зміни --accent."""
        try:
            c = NSColor.controlAccentColor().colorUsingColorSpaceName_("NSCalibratedRGBColorSpace")
            r, g, b = int(c.redComponent() * 255), int(c.greenComponent() * 255), int(c.blueComponent() * 255)
            return f"rgb({r},{g},{b})"
        except Exception:
            return "#007AFF"

    @objc.python_method
    def _settings_state(self):
        """Поточний стан → словник для проштовхування у JS (заповнює контроли мокапа)."""
        cfg = load_cfg()
        p = self.panel
        loaded = ps_loaded()
        loaded_txt = "—  (RAM вільна)"
        if loaded:
            nm = loaded[0].split("  ")[0].strip(); sz = ram_size(loaded[0])
            loaded_txt = nm + (f"  ·  {sz}" if sz else "")
        ms = list_models()
        sel = self.sel_model if self.sel_model in ms else (pick_chat_model(ms) if ms else None)
        # термозахист: поточна температура — щоб людина бачила, від чого її береже тумблер
        try:
            import thermal as _th
            _t = _th.read_max()
        except Exception:
            _t = None
        thermal_now = ("Зараз: %.0f°C · пошук та індексація чекають, поки Mac охолоне" % _t
                       if _t is not None else
                       "Датчик температури недоступний на цьому Mac — пауза не спрацює")
        return {
            "theme": cfg.get("theme", "Авто"),
            "transp": int(cfg.get("transp", 70)),
            "autoLogin": bool(cfg.get("autostart_login")),
            "autoOllama": bool(cfg.get("autostart_ollama")),
            "autoTts": bool(cfg.get("autostart_tts")),
            "optFlash": bool(cfg.get("ollama_flash", True)),
            "optKv": bool(cfg.get("ollama_kv_q8", True)),
            "thermalOn": bool(cfg.get("thermal_on", True)),
            "thermalCool": int(cfg.get("thermal_cool_at", 92)),
            "thermalNow": thermal_now,
            "chatsDir": chats_dir(),
            "modelsDir": models_dir(),
            "voices": [voice_label(x) for x in refresh_voices()],
            "voiceIdx": VOICES.index(p.voice) if p.voice in VOICES else 0,
            "speed": float(getattr(p, "speed", 1.0)),
            "volume": float(getattr(p, "volume", 0.85)),
            "pause": float(getattr(p, "pause", 0.15)),
            "ttsMode": {"base": 0, "stream": 1, "realtime": 2}.get(tts_mode(), 0),
            "ramUnload": int(cfg.get("ram_unload", 5)),
            "devices": [n for (n, u) in ([("Системний за замовч.", None)] + audio_outputs())],
            "outIdx": 0,
            "models": ms or [],
            "selModel": sel,
            "loaded": loaded_txt,
            "token": int(cfg.get("num_predict", 1024)),
            "hotkeys": {k: fmt_hotkey(v) for k, v in cfg.get("hotkeys", DEFAULT_HOTKEYS).items()},
        }

    @objc.python_method
    def _inject_settings(self, html):
        """Вшиває системний акцент (CSS) + початковий стан (window.__STATE__) у HTML
        перед </head>, щоб binding-скрипт мокапа заповнив контроли реальними даними."""
        import json
        st = self._settings_state()
        # вибраний пристрій виводу за UID
        uids = [None] + [u for (n, u) in audio_outputs()]
        cur = getattr(self.panel, "out_device", None)
        st["outIdx"] = uids.index(cur) if cur in uids else 0
        inj = ("<style>:root{--accent:%s!important}</style>"
               "<script>window.__STATE__=%s;</script>") % (self._accent_css(), json.dumps(st))
        return html.replace("</head>", inj + "</head>", 1)

    @objc.python_method
    def _set_js(self, script):
        """Виконати JS у settings-webview (проштовхування стану назад у мокап)."""
        w = getattr(self, "set_web", None)
        if w is None: return
        AppHelper.callAfter(lambda: w.evaluateJavaScript_completionHandler_(script, None))

    @objc.python_method
    def _ui_action(self, body):
        """Диспетч повідомлень із settings-мокапа (міст HTML→Python). body = {a, v, key}."""
        try: a = str(body.objectForKey_("a") or "")
        except Exception: return
        v = body.objectForKey_("v")
        key = body.objectForKey_("key")
        cfg = load_cfg()
        if a == "theme":
            val = str(v); cfg["theme"] = val; save_cfg(cfg)
            try: apply_theme(val)
            except Exception: pass
        elif a == "transp":
            try: iv = int(v)
            except Exception: iv = 70
            cfg["transp"] = iv; save_cfg(cfg)
            # NB: тимчасово — alpha всього вікна (делікатно). Справжня прозорість лише фону
            # (текст лишається чітким) = vibrancy-підкладка, у стадії полірування.
            try: self.win.setAlphaValue_(max(0.78, 1.0 - iv / 100.0 * 0.22))
            except Exception: pass
        elif a == "autoLogin":
            on = bool(v); ok = set_login_item(on)
            cfg["autostart_login"] = bool(on and ok); save_cfg(cfg)
            if not ok:
                self._set_js("setSw('autoLogin',false)")
                rumps.notification("KobzarAI", "Не вдалося внести в автозапуск входу",
                                   "Додай вручну: Системні налаштування → Загальні → Елементи входу")
        elif a == "autoOllama": cfg["autostart_ollama"] = bool(v); save_cfg(cfg)
        elif a == "autoTts":    cfg["autostart_tts"] = bool(v); save_cfg(cfg)
        elif a == "optFlash":   cfg["ollama_flash"] = bool(v); save_cfg(cfg)
        elif a == "optKv":      cfg["ollama_kv_q8"] = bool(v); save_cfg(cfg)
        # термозахист: thermal.py читає config щоразу → діє одразу, без перезапуску
        # (і для Кобзаря, і для бібліотекаря Січі — у них спільний thermal.py)
        elif a == "thermalOn":  cfg["thermal_on"] = bool(v); save_cfg(cfg)
        elif a == "thermalCool":
            try: iv = max(80, min(105, int(v)))
            except Exception: iv = 92
            cfg["thermal_cool_at"] = iv
            cfg["thermal_resume_at"] = iv - 8    # продовжуємо на 8° нижче — щоб не смикало туди-сюди
            save_cfg(cfg)
        elif a == "chatsFinder": self.revealChatsDir_(None)
        elif a == "chatsFolder":
            p = NSOpenPanel.openPanel()
            p.setCanChooseDirectories_(True); p.setCanChooseFiles_(False)
            p.setAllowsMultipleSelection_(False); p.setPrompt_("Вибрати")
            if p.runModal() == 1:
                path = str(p.URLs()[0].path())
                cfg["chats_dir"] = path or None; save_cfg(cfg)
                self.sessions = load_chats() or [
                    {"title": "Чат 1", "history": [], "ts": time.time(),
                     "id": str(int(time.time() * 1000))}]
                self.cur = 0
                self._set_js("kobzar.setChatsDir(%s)" % json.dumps(chats_dir()))
        elif a == "uninstall": self.uninstallApp_(None)
        elif a == "hk":
            # запис хоткея: поки лишаємо нативний потік (NSEvent capture) — стадія далі
            pass

    # ---------- вкладка: ГОЛОС (лише озвучення) ----------

    # ---------- вкладка 3: міні-чат ----------
    @objc.python_method
    def _build_chat(self, v, CW, CH):
        # 26.09.2026: уся вкладка — ОДНА веб-сторінка (chatui.py): історія, шапка, стрічка,
        # ввід, меню @. Раніше тут жили 4 різнорідні шматки (таблиця + NSTextView + вебвʼю +
        # нативні плашки) — з різними шрифтами й відступами; звідси й «зібраний» вигляд.
        # Нативні атрибути чату (chat_input, hist_tbl, send_btn…) лишаються None.
        frame = NSMakeRect(LP_M, 8, CW - 2 * LP_M, CH - 12)
        cfg = WKWebViewConfiguration.alloc().init()
        try:
            ucc = cfg.userContentController()
            for nm in ("copy", "speak", "regen", "open", "ext", "chat"):
                ucc.removeScriptMessageHandlerForName_(nm)
                ucc.addScriptMessageHandler_name_(self, nm)
        except Exception:
            pass
        try:                                          # 30.09: відео/звук з диска без base64
            self._fh = _cf.FileSchemeHandler.alloc().init()
            cfg.setURLSchemeHandler_forURLScheme_(self._fh, _cf.SCHEME)
        except Exception:
            self._fh = None
        web = (_cf.KWebView or WKWebView).alloc().initWithFrame_configuration_(frame, cfg)
        if _cf.KWebView is not None:                  # файли з Finder ловимо нативно (справжній шлях, без ліміту)
            web.on_files = self._drop_files
            web.on_hover = lambda on: self._js("dropHint(%s)" % ("true" if on else "false"))
        web.setNavigationDelegate_(self)
        web.setAutoresizingMask_(18)
        web.setWantsLayer_(True)
        try:
            web.setValue_forKey_(False, "drawsBackground")
        except Exception:
            pass
        v.addSubview_(web); self.web = web
        self.chat_start_btn = None
        web.loadHTMLString_baseURL_(chat_html(), None)   # didFinish → _push_all

    @objc.python_method
    def _circle_sym(self, name, d, glyph, circle):
        """Двоколірний circle.fill-символ: чітка glyph-стрілка/квадрат поверх суцільного
        кола (як у мокапі — біла стрілка на синьому, не «вирізана» крізь тінт)."""
        base = NSImageSymbolConfiguration.configurationWithPointSize_weight_(float(d), 0.0)
        img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
        if not img:
            return None
        try:
            pal = NSImageSymbolConfiguration.configurationWithPaletteColors_([glyph, circle])
            cfg = base.configurationByApplyingConfiguration_(pal)
            img = img.imageWithSymbolConfiguration_(cfg) or img
            img.setTemplate_(False)         # палітра несе власні кольори → НЕ template
        except Exception:
            img = img.imageWithSymbolConfiguration_(base) or img
        return img

    # ---------- База знань (RAG) ----------
    @objc.python_method
    def _kb_db_path(self):
        return os.path.join(os.path.dirname(chats_dir()), "knowledge", "index.db")

    @objc.python_method
    def _kb_get(self):
        """Ліниво підняти джерело бази знань. Пріоритет: обраний ГОТОВИЙ індекс
        (read-only, нічого не переembedить) → інакше власна проіндексована тека.
        None → фіча недоступна (нема kb.py / джерела)."""
        if self._kb is not None:
            return self._kb
        try:
            import kb as _kbmod
            if self.kb_index:
                self._kb = _kbmod.open_index(self.kb_index, host=OLLAMA_HOST)
            elif self.kb_folder:
                self._kb = _kbmod.KB(self._kb_db_path(), host=OLLAMA_HOST)
            else:
                return None
        except Exception as e:
            try: rumps.notification("KobzarAI", "База знань недоступна", str(e)[:80])
            except Exception: pass
            return None
        return self._kb

    @objc.python_method
    def _kb_search(self, query):
        """Відібрані (не слабкі) фрагменти бази для запиту. None — пошук недоступний/впав
        (чат не має падати, але й «нічого не знайшов» тоді казати не можна); [] — справді нічого схожого."""
        kb = self._kb_get()
        if kb is None:
            return None
        try:
            import kb as _kbmod
            self._kb_chat_cool()
            hits = kb.search(query, k=6)
            return _kbmod.filter_hits(hits, cosine=getattr(kb, "cosine_scores", True))
        except Exception:
            return None

    @objc.python_method
    def _kb_retrieve(self, query, max_chars=2400):
        """Контекст для системного промту або "" (тихо, помилку ковтаємо)."""
        hits = self._kb_search(query)
        if not hits:
            return ""
        import kb as _kbmod
        return _kbmod.build_context(hits, max_chars)

    @objc.python_method
    def _kb_note(self, hits, used=None):
        """Що показати під відповіддю: {n, src:[{n: імʼя файлу, p: шлях (лише наявний файл)}]}.
        hits None → n=-1 (пошук не спрацював), [] → n=0 (нічого схожого)."""
        if hits is None:
            return {"n": -1, "src": []}
        used = hits if used is None else used
        src, seen = [], set()
        for h in used:
            path = h.get("path", "") or ""
            name = os.path.basename(path) or "джерело"
            if name in seen:
                continue
            seen.add(name)
            src.append({"n": name, "p": path if (os.path.sep in path and os.path.exists(path)) else ""})
        return {"n": len(used), "src": src}

    @objc.python_method
    def _kb_chat_cool(self):
        """Легкий термо-гейт перед пошуком у чаті (фоновий потік): лише аварійно, ≥100°C,
        не довше 8 с — щоб не морозити відповідь. Якщо пауза сталася — ЧЕСНО кажемо в чаті,
        а не мовчки висимо. Вимкнено тумблером / нема датчика → миттєво далі."""
        try:
            import thermal as _th
        except Exception:
            return
        shown = []

        def _wait(t, waited):
            if not shown:
                shown.append(1)
                self._js("note(%s)" % json.dumps(
                    "❄️ Mac перегрівся (%.0f°C) — пошук у базі на паузі кілька секунд, "
                    "щоб охолонути. Відповідь продовжиться сама." % t))
        try:
            _th.cooldown(cool_at=100, resume_at=95, max_cool=8, interval=2, on_wait=_wait)
        except Exception:
            pass

    def kbToggled_(self, sender):
        if not (self.kb_index or self.kb_folder):
            self._js("note('Спершу обери базу знань у Налаштування → Загальні')")
            self.select_tab(0)
            return
        self.kb_on = not self.kb_on
        cfg = load_cfg(); cfg["kb_on"] = self.kb_on; save_cfg(cfg)
        self._sync_kb()

    @objc.python_method
    def _sync_kb(self):
        self._push_toggles()
        self._refresh_chat_header()

    @objc.python_method
    def _kb_reindex(self, done=None):
        """Проіндексувати kb_folder у фоні. done(stats|None, err|None) на головному потоці."""
        if self._kb_busy:
            return
        folder = self.kb_folder
        if not folder:
            if done: AppHelper.callAfter(done, None, "не обрано теку")
            return
        self._kb_busy = True
        def run():
            err = None; stats = None
            try:
                import kb as _kbmod
                kb = _kbmod.KB(self._kb_db_path(), host=OLLAMA_HOST)
                self._kb = kb
                if not ollama_up():
                    self.panel._start_ollama()
                    for _ in range(20):
                        if ollama_up(): break
                        time.sleep(1)
                if not ollama_up():
                    raise _kbmod.KBEmbedUnavailable("Ollama не запущена")
                def _prog(done, total, phase):
                    AppHelper.callAfter(self._kb_prog, done, total, phase)
                def _cool(temp, waited):
                    AppHelper.callAfter(self._kb_cool, temp, waited)
                stats = kb.index(folder, progress=_prog, cooldown_cb=_cool)
            except Exception as e:
                err = str(e)
            finally:
                self._kb_busy = False
                if done: AppHelper.callAfter(done, stats, err)
        threading.Thread(target=run, daemon=True).start()

    @objc.python_method
    def _kb_prog(self, done, total, phase):
        """Прогрес індексації у рядок стану «База знань» (головний потік)."""
        lbl = getattr(self, "kb_status", None)
        if lbl is None:
            return
        if phase == "done":
            lbl.setStringValue_(self._kb_status_text())
        elif total:
            lbl.setStringValue_("Індексація… %d/%d файлів" % (done, total))

    @objc.python_method
    def _kb_cool(self, temp, waited):
        """Термо-пауза під час індексації — показуємо чесно, що це пауза, не обрив."""
        lbl = getattr(self, "kb_status", None)
        if lbl is None:
            return
        lbl.setStringValue_("❄️ Охолодження SoC %.0f°C — пауза %.0f с (індексація продовжиться)"
                            % (temp, waited))

    @objc.python_method
    def _sync_spk(self):
        """Стан автоозвучки → кнопка-динамік на сторінці чату."""
        self._push_toggles()

    @objc.python_method
    def _gen_ui(self, on):
        """Під час генерації кнопка надсилання стає «Зупинити» (на сторінці чату)."""
        self._generating = bool(on)
        self._js("setGen(%s)" % ("true" if on else "false"))

    # ---------- дії: голос/хоткеї ----------
    def voiceChanged_(self, sender):
        idx = sender.indexOfSelectedItem()
        v = VOICES[idx] if 0 <= idx < len(VOICES) else VOICES[0]   # підпис→серверний ключ
        self.panel.voice = v
        cfg = load_cfg(); cfg["voice"] = v; save_cfg(cfg)

    def speedChanged_(self, sender):
        sp = max(0.7, min(1.3, float(sender.floatValue())))
        self.panel.speed = sp
        if getattr(self, "speed_val", None) is not None:
            self.speed_val.setStringValue_(f"×{sp:.2f}")
        cfg = load_cfg(); cfg["speed"] = round(sp, 2); save_cfg(cfg)

    def pauseChanged_(self, sender):
        pz = max(0.0, min(0.6, float(sender.floatValue())))
        self.panel.pause = pz
        if getattr(self, "pause_val", None) is not None:
            self.pause_val.setStringValue_(f"{pz:.2f} с")
        cfg = load_cfg(); cfg["pause"] = round(pz, 2); save_cfg(cfg)

    def volumeChanged_(self, sender):
        vol = max(0.0, min(1.0, float(sender.floatValue())))
        self.panel.volume = vol
        if getattr(self, "vol_val", None) is not None:
            self.vol_val.setStringValue_(f"{int(round(vol * 100))}%")
        cfg = load_cfg(); cfg["volume"] = round(vol, 2); save_cfg(cfg)

    def outDeviceChanged_(self, sender):
        i = sender.indexOfSelectedItem()
        uids = getattr(self, "_out_uids", [None])
        uid = uids[i] if 0 <= i < len(uids) else None
        self.panel.out_device = uid                    # None=системний; UID→NSSound.setPlaybackDeviceIdentifier_
        cfg = load_cfg(); cfg["out_device"] = uid or ""; save_cfg(cfg)

    @objc.python_method
    def _preview_set(self, btn, title, red):
        # «Прослухати» акцентна; під час відтворення морфиться у червону «Зупинити»
        try:
            btn.setTitle_(title)
            btn.setBezelColor_(NSColor.systemRedColor() if red else accent_color())
        except Exception: pass

    def previewVoice_(self, sender):
        # повторний клік під час відтворення → СТОП
        if self.panel._state in ("synth", "playing", "paused"):
            self.panel.stop_speech(None)
            self._preview_set(sender, "Прослухати", False)
            return
        sample = ("Привіт. Це зразок мого голосу. "
                  "Перевіряю швидкість і паузу між реченнями. Один, два, три.")
        cold = not tts_up()                  # сервер лежить → буде холодний старт ~20 c
        self._preview_set(sender, "Запускаю голос…" if cold else "Зупинити", True)
        def run():
            shown_stop = [not cold]
            self.panel._speak(sample)
            # дочекатись завершення → повернути назву кнопки
            time.sleep(0.4)
            while self.panel._state in ("synth", "playing", "paused"):
                if not shown_stop[0] and self.panel._state == "playing":
                    shown_stop[0] = True     # звук пішов → дозволь СТОП
                    AppHelper.callAfter(self._preview_set, sender, "Зупинити", True)
                time.sleep(0.15)
            AppHelper.callAfter(self._preview_set, sender, "Прослухати", False)
        threading.Thread(target=run, daemon=True).start()

    def themeChanged_(self, sender):
        t = str(sender.titleOfSelectedItem())
        cfg = load_cfg(); cfg["theme"] = t; save_cfg(cfg)
        apply_theme(t)
        # підкладка прозорості — це заморожений CGColor на CALayer (не реагує на зміну
        # appearance). Без перерезолву він лишається кольором старої теми → білий текст
        # нової теми на світлій підкладці = невидимо. Перефарбувати під поточну тему.
        if getattr(self, "_glass", None) is not None:
            self._apply_transp(self._glass)
        self._reload_web()  # чат під нову тему

    def accentChanged_(self, sender):
        a = str(sender.titleOfSelectedItem())
        cfg = load_cfg(); cfg["accent"] = a; save_cfg(cfg)
        ac = accent_color()
        if self.accent_swatch is not None:
            self.accent_swatch.setFillColor_(ac)
        if self.seg is not None:
            try: self.seg.reaccent()                          # верхній перемикач теж перефарбувати
            except Exception: pass
        if self.send_btn is not None:
            try: self.send_btn.setContentTintColor_(ac)
            except Exception: pass
        # галочки → новий акцент (текст не чіпаємо)
        for cb in (getattr(self, "auto_login", None), getattr(self, "auto_oll", None),
                   getattr(self, "auto_tts", None), getattr(self, "opt_flash", None),
                   getattr(self, "opt_kv", None)):
            if cb is not None: self._acc_check(cb)
        self._sync_spk()                              # динамік — іконка, не чекбокс: тінт окремо
        if self.preview_btn is not None:
            try: self.preview_btn.setBezelColor_(ac)
            except Exception: pass
        for rg in getattr(self, "_all_rings", []):   # перемалювати акцентні кільця
            rg.setNeedsDisplay_(True)
        self._update_pull_btn()
        for sg in (self.lib_seg, getattr(self, "tts_mode", None)):
            if sg is None: continue
            if hasattr(sg, "reaccent"):
                sg.reaccent()
            else:
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

    def thermOnToggled_(self, sender):
        cfg = load_cfg(); cfg["thermal_on"] = bool(sender.state()); save_cfg(cfg)
        if getattr(self, "th_now", None) is not None: self.th_now.setStringValue_(self._therm_now_txt())

    def thermStep_(self, sender):
        i = max(0, min(len(THERM_OPTS) - 1, self.th_idx + int(sender.tag())))
        if i == self.th_idx: return
        self.th_idx = i
        self.th_num.setStringValue_("%d°C" % THERM_OPTS[i])
        cfg = load_cfg()
        cfg["thermal_cool_at"] = THERM_OPTS[i]
        cfg["thermal_resume_at"] = THERM_OPTS[i] - 8    # на 8° нижче — щоб не смикало туди-сюди
        save_cfg(cfg)
        if getattr(self, "th_now", None) is not None: self.th_now.setStringValue_(self._therm_now_txt())

    def ttsModeChanged_(self, sender):
        # 0=Базовий (стабільний) · 1=Стрім (конвеєр) · 2=Реалтайм (чат озвучує поки пише)
        m = {0: "base", 1: "stream", 2: "realtime"}.get(sender.selectedSegment(), "base")
        cfg = load_cfg(); cfg["tts_mode"] = m
        cfg["tts_stream"] = (m != "base")          # сумісність зі старим ключем
        save_cfg(cfg)

    def ttsIdleChanged_(self, sender):
        # індекс попапа → хвилини простою до вивантаження TTS (0 = ніколи)
        i = int(sender.indexOfSelectedItem())
        m = TTS_IDLE_MIN[i] if 0 <= i < len(TTS_IDLE_MIN) else 0
        cfg = load_cfg(); cfg["tts_idle_min"] = m; save_cfg(cfg)
        self.panel._tts_last_use = time.time()     # скинути лічильник, щоб не вбити одразу

    def autoLoginToggled_(self, sender):
        on = bool(sender.state())
        ok = set_login_item(on)            # реєстрація login-item лише за галочкою (явний opt-in)
        cfg = load_cfg(); cfg["autostart_login"] = on; save_cfg(cfg)
        if not ok:
            sender.setState_(0)
            cfg = load_cfg(); cfg["autostart_login"] = False; save_cfg(cfg)
            rumps.notification("KobzarAI", "Не вдалося внести в автозапуск входу",
                               "Додай вручну: Системні налаштування → Загальні → Елементи входу")

    def uninstallApp_(self, sender):
        """Повне видалення стека KobzarAI. Деструктив + незворотно → одне явне
        «впевнені?». Реально стирає окремий detached-скрипт (переживає вихід апки),
        бо апка не може стерти власний bundle, поки сама виконується."""
        app_path = None
        try:
            from AppKit import NSBundle
            app_path = NSBundle.mainBundle().bundlePath()
            if app_path and not str(app_path).endswith(".app"):
                app_path = None
        except Exception:
            app_path = None
        targets = ("• застосунок KobzarAI.app\n"
                   "• TTS-сервер (~/.local/styletts2-ua-server)\n"
                   "• панель і налаштування (~/.local/kobzarai)\n"
                   "• лаунчер Ollama (~/.ollama/start-ollama.sh)")
        if rumps.alert(
                title="Видалити KobzarAI повністю?",
                message="Впевнені? Це безповоротно зупинить сервіси й зітре:\n\n"
                        f"{targets}\n\n"
                        "Моделі на зовнішньому диску та сам Ollama (brew) "
                        "лишаться недоторканими.",
                ok="Видалити назавжди", cancel="Скасувати") != 1:
            return
        # знімаємо login-item ще з живої апки (SMAppService резолвить лише наявний bundle)
        try: set_login_item(False)
        except Exception: pass
        # detached-скрипт: чекає вихід апки → стирає файли → повідомляє
        apps = []
        if app_path: apps.append(str(app_path))
        apps += ["/Applications/KobzarAI.app",
                 os.path.expanduser("~/Applications/KobzarAI.app")]
        seen = []
        for a in apps:
            if a not in seen: seen.append(a)
        rm_apps = " ".join(shlex.quote(a) for a in seen)
        script = f"""#!/bin/bash
sleep 1.5
pkill -f 'ollama serve' 2>/dev/null
kill $(lsof -ti :{TTS_PORT}) 2>/dev/null
rm -rf {shlex.quote(TTS_DIR)}
rm -rf {shlex.quote(os.path.expanduser("~/.local/kobzarai"))}
rm -f {shlex.quote(os.path.expanduser("~/.ollama/start-ollama.sh"))}
rm -f /tmp/kobzarai.log
rm -rf {rm_apps}
osascript -e 'display notification "Застосунок, TTS-сервер і лаунчер Ollama видалено. Дякую, що користувались." with title "KobzarAI видалено"'
rm -f "$0"
"""
        try:
            sp = "/tmp/kobzarai_uninstall.sh"
            with open(sp, "w") as f: f.write(script)
            os.chmod(sp, 0o755)
            subprocess.Popen(["bash", sp], start_new_session=True)
        except Exception:
            rumps.alert(title="Не вдалося запустити видалення",
                        message="Спробуй ще раз або видали вручну: "
                                "/Applications/KobzarAI.app та ~/.local/kobzarai")
            return
        self.panel.quit_all(None)

    def windowDidBecomeKey_(self, n): self._reaccent_segments()
    def windowDidResignKey_(self, n):
        self._reaccent_segments()
    def windowDidResize_(self, n):
        try: self._scroll._layout_mask()
        except Exception: pass

    @objc.python_method
    def _reaccent_segments(self):
        for nm in ("seg", "tts_mode"):
            s = getattr(self, nm, None)
            if s is not None and hasattr(s, "setNeedsDisplay_"):
                try: s.setNeedsDisplay_(True)
                except Exception: pass

    def transpChanged_(self, sender):
        iv = int(sender.floatValue())
        cfg = load_cfg(); cfg["transp"] = iv; save_cfg(cfg)
        tv = getattr(self, "transp_val", None)
        if tv is not None:
            try: tv.setStringValue_("%d%%" % iv)
            except Exception: pass
        if getattr(self, "_glass", None) is not None:
            self._apply_transp(self._glass)

    @objc.python_method
    def _apply_transp(self, glass):
        """Прозорість «скла»: непрозора підкладка поверх блюру, alpha = 1−прозорість.
        0 = суцільний фон (як System Settings), 100 = максимум скла."""
        raw = max(0, min(100, int(load_cfg().get("transp", 35)))) / 100.0
        # справжнє скло вже прозоре — крива м'якша, повзунок керує ТІЛЬКИ молочним fill.
        frac = raw ** 0.55
        host = getattr(self, "_host", glass)
        fill = getattr(self, "_transp_fill", None)
        if fill is None:
            fill = NSView.alloc().initWithFrame_(host.bounds())
            fill.setWantsLayer_(True)
            fill.setAutoresizingMask_(18)
            host.addSubview_positioned_relativeTo_(fill, -1, None)  # NSWindowBelow — під контентом
            self._transp_fill = fill
        # windowBackgroundColor — динамічний; його треба резолвити САМЕ під поточною темою
        # вікна, інакше після зміни appearance дістанемо колір старої теми (CALayer його
        # заморожує). performAsCurrentDrawingAppearance гарантує резолв під новою темою.
        def paint():
            try:
                c = NSColor.windowBackgroundColor().colorUsingColorSpace_(NSColorSpace.sRGBColorSpace())
                # floor 0.15: навіть на «100% скла» лишається мінімум молока —
                # інакше secondary-текст тонув у шпалерах (нечитабельний UI)
                fill.layer().setBackgroundColor_(
                    NSColor.colorWithRed_green_blue_alpha_(
                        c.redComponent(), c.greenComponent(), c.blueComponent(),
                        max(0.15, 1.0 - frac)).CGColor())
            except Exception: pass
        def paint_all():
            paint()
            # справжнє скло: легкий tint для читабельності тексту на максимумі прозорості
            # (на повному склі без молока — трохи молочної плівки, як у системних віджетів).
            if _HAS_GLASS and hasattr(glass, "setTintColor_"):
                try:
                    is_dark = "Dark" in str(glass.effectiveAppearance().name())
                    base = 0.0 if is_dark else 1.0
                    a = 0.08 + 0.10 * frac      # більше скла → більше молока, щоб текст не тонув
                    glass.setTintColor_(NSColor.colorWithWhite_alpha_(base, a))
                except Exception: pass
            else:
                try:
                    if   frac >= 0.60: mat = NSVisualEffectMaterialHUDWindow
                    elif frac >= 0.30: mat = NSVisualEffectMaterialUnderWindowBackground
                    else:              mat = NSVisualEffectMaterialWindowBackground
                    glass.setMaterial_(mat)
                except Exception: pass
            tint = self._card_tint()      # картки — під поточну тему
            for c in self._cards:
                try: c.setFillColor_(tint)
                except Exception: pass
            ktint = self._keycap_tint()
            for c in getattr(self, "_keycaps", []):
                try: c.setFillColor_(ktint)
                except Exception: pass
        ap = glass.effectiveAppearance()
        if hasattr(ap, "performAsCurrentDrawingAppearance_"):
            ap.performAsCurrentDrawingAppearance_(paint_all)
        else:
            paint_all()

    def browseModelsDir_(self, sender):
        p = NSOpenPanel.openPanel()
        p.setCanChooseDirectories_(True); p.setCanChooseFiles_(False)
        p.setAllowsMultipleSelection_(False); p.setPrompt_("Вибрати")
        if p.runModal() == 1:
            url = p.URLs()[0]
            self.models_field.setStringValue_(str(url.path()))

    @objc.python_method
    def _kb_status_text(self):
        if self.kb_index:
            try:
                s = self._kb_get().stats()
                return "готовий індекс · %d фрагментів (без переіндексації)" % s.get("chunks", 0)
            except Exception:
                return "готовий індекс обрано"
        if not self.kb_folder:
            return "джерело не обрано"
        try:
            kb = self._kb_get()
            if kb is None:
                return "готово до індексації"
            s = kb.stats()
            if not s.get("chunks"):
                return "тека обрана — натисни «Проіндексувати»"
            when = ""
            if s.get("updated"):
                when = " · " + time.strftime("%d.%m %H:%M", time.localtime(s["updated"]))
            return "%d файлів · %d фрагментів%s" % (s["files"], s["chunks"], when)
        except Exception:
            return "готово до індексації"

    @objc.python_method
    def _kb_sync_controls(self):
        """Обрано готовий індекс → поле теки/папка/«Проіндексувати» неактивні
        (нема що індексувати — читаємо готове)."""
        own = not bool(self.kb_index)
        for w in (getattr(self, "kb_field", None), getattr(self, "kb_browse_btn", None),
                  getattr(self, "kb_index_btn", None)):
            if w is not None:
                try: w.setEnabled_(own)
                except Exception: pass

    def kbIndexChanged_(self, sender):
        i = int(sender.indexOfSelectedItem())
        paths = getattr(self, "_kb_index_paths", [""])
        self.kb_index = paths[i] if 0 <= i < len(paths) else ""
        self._kb = None                                # джерело змінилось → перепідняти
        cfg = load_cfg(); cfg["kb_index"] = self.kb_index; save_cfg(cfg)
        self.kb_status.setStringValue_(self._kb_status_text())
        self._kb_sync_controls()
        self._sync_kb()

    def browseKbDir_(self, sender):
        p = NSOpenPanel.openPanel()
        p.setCanChooseDirectories_(True); p.setCanChooseFiles_(False)
        p.setAllowsMultipleSelection_(False); p.setPrompt_("Вибрати")
        if p.runModal() == 1:
            path = str(p.URLs()[0].path())
            self.kb_folder = path
            self.kb_index = ""                         # перехід на власну теку → зняти готовий
            self._kb = None                            # тека змінилась → перепідняти KB
            cfg = load_cfg(); cfg["kb_folder"] = path; cfg["kb_index"] = ""; save_cfg(cfg)
            self.kb_field.setStringValue_(path)
            if getattr(self, "kb_index_pop", None) is not None:
                self.kb_index_pop.selectItemAtIndex_(0)
            self.kb_status.setStringValue_(self._kb_status_text())
            self._sync_kb()

    def reindexKb_(self, sender):
        path = str(self.kb_field.stringValue()).strip()
        if path and (path != self.kb_folder or self.kb_index):
            self.kb_folder = path; self.kb_index = ""; self._kb = None
            cfg = load_cfg(); cfg["kb_folder"] = path; cfg["kb_index"] = ""; save_cfg(cfg)
            if getattr(self, "kb_index_pop", None) is not None:
                self.kb_index_pop.selectItemAtIndex_(0)
        if not self.kb_folder:
            self.kb_status.setStringValue_("спершу обери теку")
            return
        self.kb_status.setStringValue_("індексація… (перший раз ~хвилина)")
        def done(stats, err):
            if err:
                self.kb_status.setStringValue_("помилка: " + err[:60])
            else:
                self.kb_status.setStringValue_(self._kb_status_text())
            self._sync_kb()
        self._kb_reindex(done)

    def browseChatsDir_(self, sender):
        p = NSOpenPanel.openPanel()
        p.setCanChooseDirectories_(True); p.setCanChooseFiles_(False)
        p.setAllowsMultipleSelection_(False); p.setPrompt_("Вибрати")
        if p.runModal() == 1:
            path = str(p.URLs()[0].path())
            cfg = load_cfg(); cfg["chats_dir"] = path or None; save_cfg(cfg)
            self.chats_field.setStringValue_(chats_dir())
            self.sessions = load_chats() or [
                {"title": "Чат 1", "history": [], "ts": time.time(),
                 "id": str(int(time.time() * 1000))}]
            self.cur = 0; self._reload_hist(); self._render_session()

    def revealChatsDir_(self, sender):
        d = chats_dir()
        try: os.makedirs(d, exist_ok=True)
        except Exception: pass
        subprocess.Popen(["open", d])

    def applyChatsDir_(self, sender):
        path = str(self.chats_field.stringValue()).strip()
        cfg = load_cfg(); cfg["chats_dir"] = path or None; save_cfg(cfg)
        self.chats_field.setStringValue_(chats_dir())
        self.sessions = load_chats() or [
            {"title": "Чат 1", "history": [], "ts": time.time(),
             "id": str(int(time.time() * 1000))}]
        self.cur = 0
        try: self._reload_hist(); self._render_session()
        except Exception: pass

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
    def unloadSlot_(self, sender):
        i = int(sender.tag())
        if 0 <= i < 2 and self._slot_models[i]: self.panel.unload_one(self._slot_models[i])
    def deleteModel_(self, sender): self.panel.delete_model(self.sel_model)

    def doPull_(self, sender):
        name = str(self.pull_field.stringValue()).strip()
        if name: self.panel.start_pull(name)

    def clearPull_(self, sender):
        self.pull_field.setStringValue_("")
        self._update_pull_btn()
        try: self.win.makeFirstResponder_(self.pull_field)
        except Exception: pass

    def cancelPull_(self, sender):
        self.panel.cancel_pull()

    # ── бібліотека моделей (Ollama / HuggingFace) ──
    # ── ЄДИНИЙ делегат на 2 таблиці (бібліотека + чати) → диспетч по tv. ──
    # Реалізація viewForTableColumn робить ОБИДВІ таблиці view-based, тож
    # бібліотеку теж малюємо комірками-view (не cell-based objectValue).
    def numberOfRowsInTableView_(self, tv):
        if tv is getattr(self, "lib_table", None):
            return len(getattr(self, "lib_filtered", []))
        return len(self.sessions)

    @objc.python_method
    def _lib_cell(self, col, row):
        rows = getattr(self, "lib_filtered", [])
        if not (0 <= row < len(rows)):
            return None
        r = rows[row]
        is_size = str(col.identifier()) == "size"
        f = NSTextField.alloc().init()
        f.setBezeled_(False); f.setDrawsBackground_(False)
        f.setEditable_(False); f.setSelectable_(False)
        f.cell().setLineBreakMode_(4)               # truncate tail
        f.setTranslatesAutoresizingMaskIntoConstraints_(False)
        if is_size:
            f.setAlignment_(2)                       # праворуч
            f.setFont_(NSFont.systemFontOfSize_(11.0))
            f.setTextColor_(NSColor.secondaryLabelColor())
            f.setStringValue_(self._size_for(r))
        else:
            f.setFont_(NSFont.systemFontOfSize_(12.0))
            f.setTextColor_(NSColor.labelColor())
            dl = r.get("dl")
            f.setStringValue_(f"{r['id']}    ↓{short_num(dl)}" if dl else r["id"])
        # контейнер на всю висоту рядка → поле центрується по вертикалі (інакше
        # h17-поле сиділо вгорі рядка 26 → «текст не відцентрований по плашці»).
        # бічний відступ 10 → текст лягає всередину заокругленої підсвітки (інсет 4).
        cell = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 80, 26))
        cell.setAutoresizingMask_(18)
        cell.addSubview_(f)
        padL = 0 if is_size else 10
        padR = 10 if is_size else 0
        NSLayoutConstraint.activateConstraints_([
            f.leadingAnchor().constraintEqualToAnchor_constant_(cell.leadingAnchor(), padL),
            f.trailingAnchor().constraintEqualToAnchor_constant_(cell.trailingAnchor(), -padR),
            f.centerYAnchor().constraintEqualToAnchor_(cell.centerYAnchor())])
        return cell

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
                    self._resort_if_size()       # видимий рядок отримав розмір → пересортувати
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
        self._update_pull_btn()
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
        self.lib_sort = ("size", "dl", "name")[max(0, sender.indexOfSelectedItem())]
        self._apply_lib_filter()

    @objc.python_method
    def _sel_lib_id(self):
        """id моделі під поточним виділенням (щоб тримати вибір на ТІЙ САМІЙ моделі
        крізь пересорти/reload — інакше індекс «з'їжджає» на іншу модель)."""
        tv = self.lib_table
        if tv is None:
            return None
        old = getattr(self, "lib_filtered", [])
        r = tv.selectedRow()
        return old[r]["id"] if 0 <= r < len(old) else None

    @objc.python_method
    def _restore_lib_sel(self, sel_id):
        tv = self.lib_table
        if tv is None or sel_id is None:
            return
        for i, r in enumerate(self.lib_filtered):
            if r["id"] == sel_id:
                tv.selectRowIndexes_byExtendingSelection_(
                    NSIndexSet.indexSetWithIndex_(i), False)
                return
        tv.deselectAll_(None)             # модель зникла зі списку → знімаємо виділення

    @objc.python_method
    def _apply_lib_filter(self):
        self._apply_lib_online_ui()
        sel_id = self._sel_lib_id()       # запам'ятати вибір ПЕРЕД пересортом
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
            rows.sort(key=sz)         # відомі розміри — за зростанням, невідомі — у кінець
        else:
            rows.sort(key=lambda r: -(r.get("dl") or 0))
        self.lib_filtered = rows
        if self.lib_table is not None:
            self.lib_table.reloadData()
            self._restore_lib_sel(sel_id)       # повернути виділення на ту саму модель
        self._update_lib_empty()
        if sk == "size" and self.lib_online:    # підтягнути розміри всіх рядків і пересортувати
            self._kick_size_prefetch(rows)

    @objc.python_method
    def _kick_size_prefetch(self, rows):
        """Послідовно (1 потік) тягне розміри рядків без кешу й періодично пересортовує —
        щоб дефолт «за розміром» реально показав найменші моделі першими."""
        if getattr(self, "_size_prefetch_busy", False):
            return
        pend = [r for r in rows if (r["kind"], r["id"]) not in self.lib_size_cache][:60]
        if not pend:
            return
        self._size_prefetch_busy = True
        def work():
            for i, r in enumerate(pend):
                key = (r["kind"], r["id"])
                if key in self.lib_size_cache:
                    continue
                try:
                    if r["kind"] == "hf":
                        nb, quant = fetch_hf_repo_size(r["id"])
                    else:
                        nb, quant = fetch_model_size(r["id"]), None
                except Exception:
                    nb, quant = 0, None
                def store(k=key, nb=nb, q=quant):
                    self.lib_size_cache[k] = (human_size(nb), q, nb or 0)
                AppHelper.callAfter(store)
                if (i + 1) % 12 == 0:           # періодичний ре-сорт під час підтягування
                    AppHelper.callAfter(self._resort_if_size)
            def finish():
                self._size_prefetch_busy = False
                self._resort_if_size()
            AppHelper.callAfter(finish)
        threading.Thread(target=work, daemon=True).start()

    @objc.python_method
    def _resort_if_size(self):
        if getattr(self, "lib_sort", None) == "size":
            self._apply_lib_filter()
        elif self.lib_table is not None:
            sel_id = self._sel_lib_id()       # лише оновити розміри — вибір не губити
            self.lib_table.reloadData()
            self._restore_lib_sel(sel_id)

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
            if os.environ.get("KOBZARAI_FORCE_OFFLINE"):   # тест-хук: імітація офлайну
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
        rumps.notification("KobzarAI", "Папку моделей збережено",
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
        if ms:
            self.model_pop.addItemsWithTitles_(ms)
        else:                                          # порожньо ≠ «нема»: розрізняй сервіс-офф
            self.model_pop.addItemsWithTitles_(
                ["(Ollama не запущена)" if not ollama_up() else "(моделей нема)"])
        pick = cur if cur in ms else pick_chat_model(ms)
        if pick:
            self.model_pop.selectItemWithTitle_(pick)
        self.sel_model = (str(self.model_pop.titleOfSelectedItem()) if ms else None)
        self._update_loaded()
        self._refresh_chat_header()

    @objc.python_method
    def _update_loaded(self, max_age=0):
        if self.loaded_lbl is None: return
        loaded = ps_loaded(max_age)
        names = [ln.split()[0] for ln in loaded][:2]
        cur_loaded = self.sel_model if self.sel_model in names else (names[0] if names else "")
        for i in range(2):
            ln = loaded[i] if i < len(loaded) else ""
            nm = names[i] if i < len(names) else ""
            self._slot_models[i] = nm
            hl = human_model_label(nm) if nm else ""
            self.slot_name[i].setStringValue_((f"{nm}  — {hl}" if hl else nm) if nm else "—  вільний")
            sz = ram_size(ln) if ln else ""
            self.slot_sub[i].setStringValue_("слот %d" % (i + 1) + (f" · {sz} у RAM" if sz else " · вільний"))
            self.slot_btn[i].setEnabled_(bool(nm))
        show2 = bool(names)                                # слот 2 — лише коли слот 1 зайнятий
        self.slot_row[1].setHidden_(not show2)
        if self._slot2_sep is not None: self._slot2_sep.setHidden_(not show2)
        if getattr(self, "th_now", None) is not None:      # темп. SoC живе поруч з оновленням RAM
            self.th_now.setStringValue_(self._therm_now_txt())
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
    def _refresh_chat_header(self, up=None, timer=False):
        # 26.09: шапка = лише те, що реально зайняте зараз: моделі в RAM + задачі доповнення.
        # timer=True — щосекундний тік: Ollama з кешу, і в сторінку шлемо лише коли щось змінилось.
        if self.web is None:
            return
        age = 3 if timer else 0
        items = []
        sig = json.dumps(self._chat_cmds())            # список команд змінився → оновити меню @
        if sig != getattr(self, "_cmds_sig", None):
            self._cmds_sig = sig; self._js("setCmds(%s)" % sig)
        ext = self._ext()
        if ext is not None:
            try: items.extend(ext.chips())
            except Exception: pass
        if not (ollama_up() if up is None else up):
            self._push_head({"down": True, "chips": items}, timer)
            return
        if not self.panel.current_model(max_age=15 if timer else 0):
            kb_only = self.kb_on and bool(self.kb_index or self.kb_folder)
            msg = ("Пошук по базі знань — без моделі" if kb_only else
                   "Нема чат-моделі — завантаж у вкладці «Моделі»")
            self._push_head({"chips": items, "msg": msg}, timer)
            return
        # 30.09: показуємо ВСІ моделі в памʼяті (раніше пошукова тихо ховалась і шапка брехала «одна»)
        loaded = ps_loaded(age)
        ram = ram_chips(loaded)
        if loaded and all(is_embed_model((r.split() or [""])[0]) for r in loaded):
            ram.append(("gray", "чат-модель ще не в памʼяті", "Завантажиться сама з першим запитом"))
        self._push_head({"chips": ram + items, "msg": "модель ще не завантажена"}, timer)

    @objc.python_method
    def _push_head(self, data, timer):
        js = "setHead(%s)" % json.dumps(data)
        if timer and js == getattr(self, "_head_last", None):
            return
        self._head_last = js
        self._js(js)

    def chatStartOllama_(self, sender):
        if ollama_up():
            self._refresh_chat_header(); return
        if not self.panel._start_ollama():
            self._refresh_chat_header(); return          # причина вже показана нотифікацією
        self._js("setHead({msg:'Ollama запускається…',chips:[]})")
        def poll():                                    # дочекатись підйому й оновити шапку
            for _ in range(20):
                time.sleep(1)
                if ollama_up(): break
            AppHelper.callAfter(self._refresh_chat_header)
        threading.Thread(target=poll, daemon=True).start()

    @objc.python_method
    def _set_dot(self, up):
        d = getattr(self, "chat_dot", None)
        if d is None or d.layer() is None: return
        c = NSColor.systemGreenColor() if up else NSColor.tertiaryLabelColor()
        d.layer().setBackgroundColor_(c.CGColor())

    @objc.python_method
    def _reload_hist(self):
        items = [{"t": x.get("title", ""), "ts": x.get("ts", 0)} for x in self.sessions]
        self._js("setHist(%s,%d)" % (json.dumps(items), self.cur))
        if 0 <= self.cur < len(self.sessions):
            self._js("setTitle(%s)" % json.dumps(self.sessions[self.cur].get("title", "")))

    # ── datasource/delegate бічного списку чатів ──
    def tableView_viewForTableColumn_row_(self, tv, col, row):
        if tv is getattr(self, "lib_table", None):
            return self._lib_cell(col, row)
        # двострічкова комірка: назва (semibold) + час (як «Topics» у Cherry)
        if not (0 <= row < len(self.sessions)): return None
        s = self.sessions[row]
        w = LP_SBW - 4
        cell = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, 46))
        title = NSTextField.alloc().initWithFrame_(NSMakeRect(11, 23, w - 20, 18))
        title.setBezeled_(False); title.setDrawsBackground_(False)
        title.setEditable_(False); title.setSelectable_(False)
        title.setFont_(NSFont.systemFontOfSize_weight_(13.0, 0.23))
        title.setTextColor_(NSColor.labelColor())
        title.setStringValue_(s["title"]); title.cell().setLineBreakMode_(4)  # truncate tail
        title.setAutoresizingMask_(2)
        sub = NSTextField.alloc().initWithFrame_(NSMakeRect(11, 6, w - 20, 13))
        sub.setBezeled_(False); sub.setDrawsBackground_(False)
        sub.setEditable_(False); sub.setSelectable_(False)
        sub.setFont_(NSFont.systemFontOfSize_(10.5))
        sub.setTextColor_(NSColor.secondaryLabelColor())
        sub.setStringValue_(rel_time(s.get("ts"))); sub.setAutoresizingMask_(2)
        cell.addSubview_(title); cell.addSubview_(sub)
        return cell

    def tableView_rowViewForRow_(self, tv, row):
        # заокруглена вставлена підсвітка (як список чатів → єдиний UI)
        if tv is getattr(self, "lib_table", None):
            return _LibRowView.alloc().initWithFrame_(NSMakeRect(0, 0, 400, 26))
        return ChatRowView.alloc().initWithFrame_(NSMakeRect(0, 0, LP_SBW, 46))

    def tableViewSelectionDidChange_(self, note):
        tbl = getattr(self, "hist_tbl", None)
        if tbl is None: return
        r = tbl.selectedRow()
        if 0 <= r < len(self.sessions) and r != self.cur:
            self.cur = r; self._render_session()

    # ── контекст-меню рядка чату (правий клік): перейменувати / очистити / видалити ──
    @objc.python_method
    def _chat_row_menu(self):
        m = NSMenu.alloc().init()
        for title, sel in (("Перейменувати…", "renameChat:"),
                           ("Очистити повідомлення", "clearMsgsChat:"),
                           (None, None),
                           ("Видалити чат", "deleteChat:")):
            if title is None:
                m.addItem_(NSMenuItem.separatorItem()); continue
            it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, sel, "")
            it.setTarget_(self); m.addItem_(it)
        return m

    @objc.python_method
    def _menu_row(self):
        # ціль правого кліку з нашого menuForEvent_ (без зміни активного чату);
        # фолбек на clickedRow/selectedRow
        r = getattr(self, "_ctx_row", -1)
        if r is not None and r >= 0:
            return r
        tbl = self.hist_tbl
        if tbl is None:
            return self.cur
        r = tbl.clickedRow()
        return r if r >= 0 else tbl.selectedRow()

    def renameChat_(self, sender):
        r = self._menu_row()
        if not (0 <= r < len(self.sessions)): return
        a = NSAlert.alloc().init()
        a.setMessageText_("Перейменувати чат")
        a.addButtonWithTitle_("Зберегти"); a.addButtonWithTitle_("Скасувати")
        fld = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 230, 24))
        fld.setStringValue_(self.sessions[r]["title"])
        a.setAccessoryView_(fld); a.window().setInitialFirstResponder_(fld)
        if a.runModal() == 1000:                       # NSAlertFirstButtonReturn
            t = str(fld.stringValue()).strip()
            if t:
                self.sessions[r]["title"] = t
                delete_chat_file(self.sessions[r])         # імʼя файлу слідує за назвою (для Finder)
                self.sessions[r].pop("_file", None)
                save_chat(self.sessions[r]); self._reload_hist()

    def clearMsgsChat_(self, sender):
        r = self._menu_row()
        if 0 <= r < len(self.sessions):
            self.sessions[r]["history"] = []
            save_chat(self.sessions[r])
            if r == self.cur: self._render_session()

    def deleteChat_(self, sender):
        r = self._menu_row()
        if not (0 <= r < len(self.sessions)): return
        keep = self.sessions[self.cur].get("id") if r != self.cur else None
        delete_chat_file(self.sessions[r])
        del self.sessions[r]
        if not self.sessions:
            self.sessions.append({"title": "Чат 1", "history": [], "ts": time.time(),
                                  "id": str(int(time.time() * 1000))})
        self.cur = min(self.cur, len(self.sessions) - 1)
        if keep is not None and self._sid_index(keep) >= 0:
            self.cur = self._sid_index(keep)
        self._reload_hist(); self._render_session()

    @objc.python_method
    def _archive_all_chats(self):
        """«Очистити всі чати» (26.09) — переносить файли в підтеку `_архів`
        замість hard-delete, щоб дію можна було відкотити руками з Finder.
        Сесія лишається з одним свіжим порожнім чатом."""
        d = chats_dir()
        arch = os.path.join(d, "_архів")
        try:
            os.makedirs(arch, exist_ok=True)
        except Exception:
            pass
        for s in list(self.sessions):
            f = s.get("_file")
            if not f:
                continue
            src = os.path.join(d, f)
            try:
                if os.path.exists(src):
                    dst = os.path.join(arch, f)
                    if os.path.exists(dst):
                        base, ext = os.path.splitext(f)
                        dst = os.path.join(arch, "%s-%d%s" % (base, int(time.time() * 1000), ext))
                    os.replace(src, dst)
            except Exception:
                pass
        self.sessions = [{"title": "Чат 1", "history": [], "ts": time.time(),
                          "id": str(int(time.time() * 1000))}]
        self.cur = 0
        self._reload_hist(); self._render_session()

    # ── дії зі сторінки чату (webkit.messageHandlers.chat) ──
    @objc.python_method
    def _chat_action(self, raw):
        try:
            o = json.loads(raw)
        except Exception:
            return
        a, i = o.get("a"), o.get("i", -1)
        if a == "send":
            self._send_text(str(o.get("t", "")), o.get("att") or [])
        elif a == "attPick":
            self._att_pick()
        elif a == "attData":
            self._att_data(str(o.get("name", "")), str(o.get("data", "")))
        elif a == "attDel":
            self._att_drop(str(o.get("id", "")))
        elif a == "attPaste":
            self._att_paste()
        elif a == "fileSave":
            self._file_save(str(o.get("p", "")))
        elif a == "fileReveal":
            p = str(o.get("p", ""))
            if os.path.exists(p): subprocess.Popen(["open", "-R", p], start_new_session=True)
        elif a == "filePrev":
            self._file_prev(str(o.get("p", "")))
        elif a == "stop":
            self.stopGen_(None)
        elif a == "sel":
            if 0 <= i < len(self.sessions) and i != self.cur:
                self.cur = i; self._render_session()
        elif a == "new":
            self.newChat_(None)
        elif a == "ren":
            self._rename_idx(i, str(o.get("t", "")))
        elif a in ("clr", "del"):
            self._ctx_row = i
            try:
                (self.clearMsgsChat_ if a == "clr" else self.deleteChat_)(None)
            finally:
                self._ctx_row = -1
        elif a == "clearAll":
            self._archive_all_chats()
        elif a == "kb":
            self.kbToggled_(None)
        elif a == "spk":
            self.autospeakToggled_(None)
        elif a == "ollama":
            self.chatStartOllama_(None)

    # ── вкладення (30.09) ──
    @objc.python_method
    def _att_pick(self):
        p = NSOpenPanel.openPanel()
        p.setCanChooseFiles_(True); p.setCanChooseDirectories_(False)
        p.setAllowsMultipleSelection_(True); p.setMessage_("Що додати до запиту?")

        def done(resp):
            if resp == 1:
                for u in p.URLs():
                    self._att_add(str(u.path()))
        try: p.beginSheetModalForWindow_completionHandler_(self.win, done)
        except Exception: done(1 if p.runModal() == 1 else 0)

    @objc.python_method
    def _att_add(self, src, name=None):
        """Файл → копія в теці вкладень → чіп у полі вводу. У потоці: копія й мініатюра не гальмують UI."""
        def work():
            try:
                if not os.path.isfile(src):
                    AppHelper.callAfter(self._js, "note('Папку не додати — обери файли')"); return
                dst = att_store(src, name)
                rec = {"id": "a%d" % int(time.time() * 1000000), "name": os.path.basename(dst),
                       "path": dst, "kind": att_kind(dst)}
                if not hasattr(self, "_atts"): self._atts = {}
                self._atts[rec["id"]] = rec
                view = att_view(rec); view["id"] = rec["id"]
                AppHelper.callAfter(self._js, "attAdded(%s)" % json.dumps(view))
            except Exception as e:
                AppHelper.callAfter(self._js, "note(%s)" % json.dumps("Не вдалося додати файл: " + str(e)[:60]))
        threading.Thread(target=work, daemon=True).start()

    @objc.python_method
    def _att_data(self, name, b64):
        """Файл, перетягнутий/вставлений у сторінку (байти з JS) → тимчасовий файл → як звичайне вкладення."""
        def work():
            try:
                raw = base64.b64decode(b64)
                tmp = tempfile.mkdtemp(prefix="kobzar-att-")
                p = os.path.join(tmp, os.path.basename(name) or "вставлене")
                if "." not in os.path.basename(p) and raw[:8] == b"\x89PNG\r\n\x1a\n": p += ".png"
                with open(p, "wb") as fh: fh.write(raw)
                self._att_add(p);
            except Exception as e:
                AppHelper.callAfter(self._js, "note(%s)" % json.dumps("Не вдалося додати файл: " + str(e)[:60]))
        threading.Thread(target=work, daemon=True).start()

    @objc.python_method
    def _drop_files(self, paths):
        """Нативне перетягування з Finder: справжні шляхи, без ліміту розміру."""
        for p in paths or []:
            if os.path.isdir(p):
                self._js("note('Папку не додати — перетягни файли з неї')")
            else:
                self._att_add(p)

    @objc.python_method
    def _att_paste(self):
        """Вставка (⌘V) великого файлу/картинки: лише ЧИТАЄМО буфер, нічого в нього не пишемо."""
        try:
            pb = NSPasteboard.generalPasteboard()
            fs = _cf.drop_paths(pb)
            if fs:
                self._drop_files(fs); return
            for typ, ext in (("public.png", ".png"), ("public.tiff", ".tiff"), ("public.jpeg", ".jpg")):
                data = pb.dataForType_(typ)
                if data is not None:
                    tmp = os.path.join(tempfile.mkdtemp(prefix="kobzar-att-"), "вставлене" + ext)
                    with open(tmp, "wb") as fh: fh.write(bytes(data))
                    self._att_add(tmp); return
            self._js("note('У буфері нема файлу чи картинки')")
        except Exception as e:
            self._js("note(%s)" % json.dumps("Не вдалося вставити: " + str(e)[:60]))

    @objc.python_method
    def _file_save(self, path):
        """«Зберегти оригінал»: вікно збереження (типово — Завантаження); побайтова копія, повна якість."""
        if not os.path.isfile(path):
            self._js("note('Файл не знайдено — зберегти нічого')"); return
        dl = os.path.expanduser("~/Downloads")

        def told(dst):
            d = os.path.dirname(dst)
            where = "Завантаження" if os.path.realpath(d) == os.path.realpath(dl) else (os.path.basename(d) or d)
            self._js("note(%s)" % json.dumps("Збережено в «%s»: %s" % (where, os.path.basename(dst))))

        def copy(dst=None):
            def work():
                try:
                    told(_cf.save_copy(path, dst, dl if dst is None else None))
                except Exception as e:
                    self._js("note(%s)" % json.dumps("Не вдалося зберегти: " + str(e)[:60]))
            threading.Thread(target=work, daemon=True).start()
        try:
            from AppKit import NSSavePanel
            sp = NSSavePanel.savePanel()
            sp.setNameFieldStringValue_(os.path.basename(path))
            sp.setDirectoryURL_(NSURL.fileURLWithPath_(dl))
            sp.setMessage_("Куди зберегти оригінал?")

            def done(resp):
                if resp == 1 and sp.URL() is not None:
                    copy(str(sp.URL().path()))
            sp.beginSheetModalForWindow_completionHandler_(self.win, done)
        except Exception:
            copy()                                   # нема вікна збереження — тиха копія в Завантаження з повідомленням

    @objc.python_method
    def _file_prev(self, path):
        """Текст для розгортання в чаті: перші ~40 рядків + повний (до 200 КБ). Лише текстові типи."""
        def work():
            try:
                if not os.path.isfile(path) or _cf.kind_of(path) not in _cf.TEXT_KINDS:
                    o = {"err": "Цей файл не можна переглянути тут — відкрий його кнопкою «Відкрити»"}
                else:
                    o = _cf.preview(path)
            except Exception as e:
                o = {"err": "Не вдалося прочитати файл: " + str(e)[:60]}
            self._js("filePrevSet(%s,%s)" % (json.dumps(path), json.dumps(o)))
        threading.Thread(target=work, daemon=True).start()

    @objc.python_method
    def _att_drop(self, aid):
        """Чіп прибрали до надсилання → видалити нашу копію (оригінал не чіпаємо)."""
        rec = getattr(self, "_atts", {}).pop(aid, None)
        if rec:
            try: os.remove(rec["path"])
            except Exception: pass

    @objc.python_method
    def _att_restore(self, atts):
        """Надсилання не відбулось → чіпи назад у поле (файли вже скопійовані)."""
        for a in atts or []:
            rec = dict(a, id="a%d" % int(time.time() * 1000000))
            if not hasattr(self, "_atts"): self._atts = {}
            self._atts[rec["id"]] = rec
            view = att_view(rec); view["id"] = rec["id"]
            self._js("attAdded(%s)" % json.dumps(view))

    @objc.python_method
    def _att_take(self, ids):
        """id чіпів → записи вкладень (забирає з очікуючих)."""
        out = []
        for i in ids or []:
            r = getattr(self, "_atts", {}).pop(str(i), None)
            if r: out.append({"name": r["name"], "path": r["path"], "kind": r["kind"]})
        return out

    @objc.python_method
    def _rename_idx(self, r, t):
        t = t.strip()
        if not (0 <= r < len(self.sessions)) or not t:
            return
        x = self.sessions[r]
        x["title"] = t
        delete_chat_file(x)                            # імʼя файлу слідує за назвою (для Finder)
        x.pop("_file", None)
        save_chat(x); self._reload_hist()

    @objc.python_method
    def _push_toggles(self):
        src = os.path.basename(self.kb_index or self.kb_folder or "")
        tip = ("База знань: увімкнено (%s)" % src) if self.kb_on else \
              ("База знань: вимкнено" + (" (%s)" % src if src else ", не обрано"))
        self._js("setToggles(%s)" % json.dumps(
            {"kb": bool(self.kb_on), "kbTip": tip, "spk": bool(self.autospeak_on)}))

    @objc.python_method
    def _push_all(self):
        """Сторінка чату щойно завантажилась → віддати їй увесь стан."""
        cmds = self._chat_cmds(); self._cmds_sig = json.dumps(cmds)
        ext = self._ext()
        if ext is not None:
            try: self._js(ext.page_js())
            except Exception: pass
        self._js("setBoot(%s)" % json.dumps({"ext": ext is not None, "cmds": cmds}))
        self._reload_hist(); self._push_toggles()
        self._gen_ui(getattr(self, "_generating", False))
        self._render_session(); self._refresh_chat_header()

    # ── міст копіювання з webview → NSPasteboard ──
    def userContentController_didReceiveScriptMessage_(self, ucc, msg):
        try:
            txt = msg.body()
            if txt is None: return
            name = str(msg.name())
            if name == "ui":
                self._ui_action(txt); return
            if name == "chat":
                self._chat_action(str(txt)); return
            if name == "speak":
                self.panel._speak(str(txt))               # озвучити цю відповідь
            elif name == "open":                          # відкрити файл-джерело з видачі бази знань
                p = str(txt)
                if p and os.path.exists(p):               # лише реальний наявний шлях
                    # .json/.log/… часто без зареєстрованого GUI-обробника — `open p` тоді
                    # мовчки нічого не робить → -t (текстовий редактор). Запускні типи
                    # (.app/.command/.sh…) не запускаємо — лише показуємо у Finder (chatfiles.open_cmd).
                    subprocess.Popen(_cf.open_cmd(p), start_new_session=True)
            elif name == "regen":
                self._regen_last()                        # «Ще раз» — перегенерувати
            elif name == "ext":                           # кнопки карток доповнення
                ext = self._ext()
                if ext is not None: ext.on_message(str(txt))
            else:                                         # copy
                pb = NSPasteboard.generalPasteboard()
                pb.clearContents()
                pb.setString_forType_(str(txt), "public.utf8-plain-text")
        except Exception:
            pass

    @objc.python_method
    def _regen_last(self):
        # «Ще раз»: прибрати останню відповідь AI і перегенерувати з тією ж історією.
        if getattr(self, "_generating", False):
            return
        model = self.panel.current_model()
        if not model:
            self._js("note('нема моделі')"); return
        if not ollama_up():
            self._js("note('Ollama не запущена')"); return
        sess = self.sessions[self.cur]
        h = sess["history"]
        if h and self._ext_owns(h[-1]):                   # відповідь доповнення — не Ollama
            self._js("note(%s)" % json.dumps(self._ext().regen_note())); return
        if h and h[-1]["role"] == "assistant":
            h.pop()                                       # викинути попередню відповідь
        if not (h and h[-1]["role"] == "user"):
            return                                        # нема запиту для регенерації
        save_chat(sess)
        self._render_session()                            # перемалювати без старої відповіді
        self._js("aiStart()")
        self.gen_cancel = threading.Event()
        self._gen_ui(True)
        threading.Thread(target=self._worker, args=(model, sess, self.gen_cancel),
                         daemon=True).start()

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
        if web is getattr(self, "set_web", None):
            # settings-сторінка завантажилась — тут проштовхуватимемо стан у JS (стадія 2+)
            self._settings_ready = True
            return
        self._web_ready = True
        q, self._js_queue = self._js_queue, []
        for s in q:
            web.evaluateJavaScript_completionHandler_(s, None)
        self._push_all()

    # ── 26.09: захист від WKWebView-контекстного «Reload» / будь-якого провалу навігації.
    # loadHTMLString-сторінка не має свого URL — системний Reload лишає її порожньою
    # НАЗАВЖДИ (didFinishNavigation тоді не приходить). JS вимикає сам пункт меню
    # (див. chatui.py, contextmenu), а тут — резервний рубіж: якщо навігація все ж
    # провалилась, самі перезавантажуємо сторінку й одразу проштовхуємо стан назад.
    def webView_didFailNavigation_withError_(self, web, nav, error):
        self._nav_failed(web)

    def webView_didFailProvisionalNavigation_withError_(self, web, nav, error):
        self._nav_failed(web)

    def webViewWebContentProcessDidTerminate_(self, web):
        # 30.09.2026: під свопом macOS вбиває веб-процес (jetsam) — чат лишається БІЛИМ
        # без жодної помилки навігації. Піднімаємо сторінку заново й малюємо історію.
        self._nav_failed(web)

    @objc.python_method
    def _nav_failed(self, web):
        if web is getattr(self, "set_web", None) or web is not getattr(self, "web", None):
            return
        self._reload_web()          # didFinish → _push_all відновить історію й поточний чат

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
        if not (0 <= self.cur < len(self.sessions)):   # cur міг з'їхати після пересорту/видалення
            self.cur = 0
        if not self.sessions:
            self._js("loadMsgs([])"); return
        sess = self.sessions[self.cur]
        arr = []
        for m in sess["history"]:
            if m["role"] == "user":
                u = {"r": "user", "c": m["content"]}
                if m.get("att"): u["att"] = [att_view(x) for x in m["att"]]
                if m.get("fn"): u["fn"] = m["fn"]
                arr.append(u)
            elif self._ext_owns(m):
                arr.append(self._ext().render(m))
            else:
                a = {"r": "ai", "c": m["content"]}
                if isinstance(m.get("kb"), dict): a["kb"] = m["kb"]
                arr.append(a)
        self._js("loadMsgs(%s)" % json.dumps(arr))
        self._js("setTitle(%s)" % json.dumps(sess.get("title", "")))
        ext = self._ext()
        if ext is not None:
            try: ext.restore_ui(sess)
            except Exception: pass

    @objc.python_method
    def _sid_index(self, sid):
        """Індекс сесії за стабільним id (−1 якщо нема). Рвʼязка чату йде за id, НЕ за
        позицією — інакше пересорт за часом (активний чат стрибає вгору) плутав cur і
        повідомлення потрапляли в чужий чат."""
        for i, s in enumerate(self.sessions):
            if s.get("id") == sid:
                return i
        return -1

    def newChat_(self, sender):
        sid = str(int(time.time() * 1000))
        # вставляємо ЗВЕРХУ (список — новіші вгорі), а не в кінець — інакше новий чат
        # опинявся внизу, а cur/рендер розходились
        self.sessions.insert(0, {"id": sid, "title": f"Чат {len(self.sessions) + 1}",
                                 "history": [], "ts": time.time()})
        self.cur = 0
        self._reload_hist(); self._render_session()

    def clearChat_(self, sender):
        # видалити поточний чат повністю (не просто очистити історію)
        if 0 <= self.cur < len(self.sessions):
            delete_chat_file(self.sessions[self.cur])
            del self.sessions[self.cur]
        if not self.sessions:
            self.sessions.append({"title": "Чат 1", "history": [], "ts": time.time(),
                                  "id": str(int(time.time() * 1000))})
        self.cur = min(self.cur, len(self.sessions) - 1)
        self._reload_hist(); self._render_session()

    def autospeakToggled_(self, sender):
        # динамік-кнопка: клік перемикає автоозвучку, колір віддзеркалює стан
        self.autospeak_on = not self.autospeak_on
        self._sync_spk()

    # пауза/стоп озвучки лишилися на хоткеях і в меню-барі (службовий рядок прибрано)
    def pauseSpeechBtn_(self, sender):
        self.panel.pause_speech(None)

    def stopSpeechBtn_(self, sender):
        self.panel.stop_speech(None)

    def sendOrStop_(self, sender):
        # одна кнопка: надсилання, а під час генерації — зупинка (морф ↑↔⏹)
        if getattr(self, "_generating", False):
            self.stopGen_(sender)
        else:
            self.sendChat_(sender)

    def stopGen_(self, sender):
        ev = self.gen_cancel
        if ev is not None:
            ev.set()

    def tokStep_(self, sender):
        i = max(0, min(len(TOKEN_OPTS) - 1, self.tok_idx + int(sender.tag())))
        if i == self.tok_idx: return
        self.tok_idx = i
        self.tok_num.setStringValue_(TOKEN_OPTS[i])
        cfg = load_cfg(); cfg["num_predict"] = int(TOKEN_OPTS[i]); save_cfg(cfg)

    def ctxStep_(self, sender):
        i = max(0, min(len(CTX_OPTS) - 1, self.ctx_idx + int(sender.tag())))
        if i == self.ctx_idx: return
        self.ctx_idx = i
        self.ctx_num.setStringValue_(CTX_OPTS[i])
        cfg = load_cfg(); cfg["num_ctx"] = int(CTX_OPTS[i]); save_cfg(cfg)

    def sendChat_(self, sender):
        pass                                   # 26.09: ввід живе на сторінці → _send_text

    @objc.python_method
    def _send_text(self, txt, att=None):
        txt = (txt or "").strip()
        if not txt: return
        atts = self._att_take(att)
        ext = self._ext()
        if ext is not None and not getattr(self, "_generating", False):
            cmd = ext.parse(txt)
            if cmd is not None:                       # команда доповнення: Ollama не потрібна
                ext.send(txt, cmd, atts); return
        model = self.panel.current_model()
        # Чат-моделі нема, але База знань увімкнена → чистий семантичний режим:
        # запит → ембед (bge-m3) → топ-фрагменти як відповідь, LLM не потрібна
        kb_only = (not model) and self.kb_on and bool(self.kb_index or self.kb_folder)
        if not model and not kb_only:
            self._att_restore(atts)
            self._js("inputRestore(%s)" % json.dumps(txt))
            self._js("note('Нема чат-моделі — завантаж у вкладці «Моделі»')"); return
        if not ollama_up():
            self._att_restore(atts)
            self._js("inputRestore(%s)" % json.dumps(txt))
            self._js("note('Ollama не запущена — кнопка «Запустити» вгорі')"); return
        if self.autospeak_on and tts_mode() == "realtime" and not self._ram_warned:
            warn = realtime_ram_risk()
            if warn:
                self._js("note(%s)" % json.dumps(warn))
                self._ram_warned = True
        sess = self.sessions[self.cur]
        sess.setdefault("id", str(int(time.time() * 1000)))
        sid = sess["id"]
        sess["ts"] = time.time()                       # час останньої активності → у список
        if not sess["history"]:
            sess["title"] = (txt[:20] + "…") if len(txt) > 20 else txt
        # активний чат піднімається вгору; cur тримаємо за id (не за старою позицією)
        self.sessions.sort(key=lambda s: s.get("ts", 0), reverse=True)
        self.cur = self._sid_index(sid)
        self._reload_hist()
        self._js("addUser(%s,%s)" % (json.dumps(txt), json.dumps([att_view(x) for x in atts])))
        if atts and kb_only:
            self._js("attNote(%s)" % json.dumps(["База знань не читає вкладення — файли не використано"]))
        self._js("aiStart()")
        sess["history"].append({"role": "user", "content": txt, **({"att": atts} if atts else {})})
        save_chat(sess)                                # фіксуємо на диск (чат вже існує)
        self.gen_cancel = threading.Event()
        self._gen_ui(True)                              # send → червоний стоп (⏹) на час генерації
        if kb_only:
            threading.Thread(target=self._kb_only_worker, args=(sess,), daemon=True).start()
        else:
            threading.Thread(target=self._worker, args=(model, sess, self.gen_cancel), daemon=True).start()

    @objc.python_method
    def _kb_only_worker(self, sess):
        """Чистий семантичний пошук без LLM (чат-моделі нема, kb_on=True):
        останній запит → ембед bge-m3 → топ-фрагменти прямо у відповідь."""
        try:
            last_user = next((m["content"] for m in reversed(sess["history"])
                              if m.get("role") == "user"), "")
            kb = self._kb_get()
            if kb is None:
                self._js("aiEnd()"); self._js("note('база знань недоступна')"); return
            hits = self._kb_search(last_user)
            if hits is None:
                self._js("aiEnd()"); self._js("note('пошук по базі не спрацював')"); return
            if not hits:
                full = "Нічого не знайшов у базі знань за цим запитом."
                self._js("aiAppend(%s)" % json.dumps(full))
            else:
                cards, parts = [], []
                for h in hits:
                    path = h.get("path", "") or ""
                    tag = os.path.basename(path) or "джерело"
                    snip = (h.get("text") or "").strip()
                    if len(snip) > 700:
                        snip = snip[:700] + "…"
                    # клікабельним робимо лише реальний наявний файл (архіви/memory = .md/.jsonl на диску)
                    clk = path if (os.path.sep in path and os.path.exists(path)) else ""
                    cards.append({"tag": tag, "text": snip, "path": clk})
                    parts.append("%s\n%s" % (tag, snip))
                full = "\n\n———\n\n".join(parts)
                self._js("aiHits(%s)" % json.dumps(cards))
            sess["history"].append({"role": "assistant", "content": full})
            if sess in self.sessions: save_chat(sess)   # видалений під час пошуку — не воскрешати
            self._js("aiEnd()")
        except Exception as e:
            self._js("aiEnd()")
            self._js("note(%s)" % json.dumps("пошук: " + str(e)[:80]))
        finally:
            AppHelper.callAfter(self._gen_ui, False)    # будь-який вихід → send назад у ↑

    @objc.python_method
    def _worker(self, model, sess, cancel=None):
        try:
            _cfg = load_cfg()
            np = int(_cfg.get("num_predict", 2048))
            nctx = int(_cfg.get("num_ctx", 4096))
            # відповіді доповнення у локальну модель не йдуть — лише її власна розмова
            messages = [{"role": m["role"], "content": m["content"]}
                        for m in sess["history"] if not self._ext_owns(m)]
            # 30.09: вкладення останнього запиту → текст/картинки в цей хід + чесні рядки під повідомленням.
            # Історію не мутуємо (у ній лишаються лише шляхи), раніші файли — лише назвою.
            last = sess["history"][-1] if sess["history"] else None
            if last is not None and last.get("role") == "user" and last.get("att"):
                import kb as _kbf
                fctx = _cf.local_context(last["att"], _kbf.context_budget(nctx),
                                         _cf.model_has_vision(model, OLLAMA_HOST), _cf.image_b64)
                extra = fctx["text"]
                if messages and messages[-1]["role"] == "user":
                    if extra: messages[-1]["content"] = (messages[-1]["content"] + "\n\n" + extra).strip()
                    if fctx["images"]: messages[-1]["images"] = fctx["images"]
                if fctx["notes"] and not last.get("fn"):
                    last["fn"] = fctx["notes"]
                    if sess in self.sessions: save_chat(sess)
                    self._js("attNote(%s)" % json.dumps(fctx["notes"]))
            # База знань: ретрів по останньому запиту → системний контекст спереду.
            # Не мутуємо збережену історію — лише те, що йде в модель цього разу.
            kb_note = None
            if self.kb_on:
                last_user = next((m["content"] for m in reversed(sess["history"])
                                  if m.get("role") == "user"), "")
                if last_user:
                    import kb as _kbmod
                    hits = self._kb_search(last_user)
                    used = _kbmod.select_for_context(hits, _kbmod.context_budget(nctx)) if hits else []
                    kb_note = self._kb_note(hits, used)
                    if used:
                        preamble = KB_PREAMBLE + _kbmod.build_context(used, _kbmod.context_budget(nctx))
                        # розмова + фрагменти мають вміститись у вікно контексту разом із відповіддю
                        left = int((nctx - min(np, nctx // 2)) * KB_CHARS_PER_TOKEN) - len(preamble)
                        messages = [{"role": "system", "content": preamble}] + \
                            _kbmod.trim_history(messages, max(1500, left))
            payload = json.dumps({"model": model, "messages": messages, "stream": True,
                                  "think": False,
                                  "options": {"num_predict": np, "num_ctx": nctx,
                                              "temperature": 0.6}}).encode()
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
            akb = {"kb": kb_note} if kb_note else {}
            if stopped:
                if full:
                    sess["history"].append({"role": "assistant", "content": full, **akb})
                    if sess in self.sessions: save_chat(sess)   # видалений під час генерації — не воскрешати
                if full and kb_note: self._js("aiKb(%s)" % json.dumps(kb_note))
                self._js("aiEnd()")
                self._js("note('зупинено')")
                return
            if not full:
                hint = ("порожньо — модель лише «думає». Обери у вкладці «Моделі» "
                        "gemma3:4b або instruct-2507") if thought else "порожня відповідь"
                self._js("aiAppend(%s)" % json.dumps(hint))
                self._js("aiEnd()")
                return
            sess["history"].append({"role": "assistant", "content": full, **akb})
            if sess in self.sessions: save_chat(sess)   # видалений під час генерації — не воскрешати
            if kb_note: self._js("aiKb(%s)" % json.dumps(kb_note))
            self._js("aiEnd()")
            if self.autospeak_on and not realtime:     # base/stream — озвучити по завершенні
                AppHelper.callAfter(lambda: self.panel._speak(full))
        except Exception as e:
            # закрити realtime-чергу і тут — інакше synth_loop висить на q.get вічно,
            # стан застрягає у «synth», а пауза крутить _pause_pending у порожнечу
            try:
                if realtime: self.panel._live_end(live_gen)
            except Exception: pass
            self._js("aiEnd()")
            self._js("note(%s)" % json.dumps("помилка: " + str(e)[:80]))
        finally:
            AppHelper.callAfter(self._gen_ui, False)    # будь-який вихід → send назад у ↑


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
        self._update_loaded(max_age=3)
        if self._chat_built and self._chat_host is not None and not self._chat_host.isHidden():
            self._refresh_chat_header(up=up, timer=True)    # 26.09: плашки RAM/черги чатів живі


class Panel(rumps.App):
    def __init__(self):
        super().__init__("KobzarAI", quit_button=None)
        try:
            NSApplication.sharedApplication().setActivationPolicy_(1)  # accessory (без док-іконки)
        except Exception: pass
        # назва+іконка для Dock (коли вікно відкрите стаємо Foreground)
        try:
            NSProcessInfo.processInfo().setProcessName_("KobzarAI")
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
        # 🔴 збережений голос НЕ скидаємо, навіть якщо його нема в поточному списку:
        # на старті сервер ще може не відповідати (список = фолбек із 4 імен), і
        # стара логіка мовчки перекидала людину на перший голос, губивши вибір.
        saved = cfg.get("voice")
        self.voice = saved if saved else VOICES[0]
        try: self.speed = max(0.7, min(1.3, float(cfg.get("speed", 1.0))))
        except Exception: self.speed = 1.0
        try: self.pause = max(0.0, min(0.6, float(cfg.get("pause", 0.15))))
        except Exception: self.pause = 0.15
        try: self.volume = max(0.0, min(1.0, float(cfg.get("volume", 0.85))))
        except Exception: self.volume = 0.85
        self.out_device = cfg.get("out_device") or None      # UID пристрою виводу; None=системний
        self._snd = None
        self._speak_gen = 0
        self._state = "idle"
        self._pause_pending = False   # пауза, натиснута під час синтезу → застосувати на старті відтворення
        self._tts_active = 0          # >0 поки конвеєр озвучення живий → health-таймер не чіпає _state/_snd
        self._tts_last_use = time.time()   # коли востаннє синтезували → для авто-вивантаження по простою
        self._live = None
        self._live_buf = ""
        self._live_nflush = 0
        self._tts_starting = False
        self._tts_was_up = False        # стан TTS попереднього тіку (детект краху)
        self._tts_miss = 0              # поспіль промахів /health (дебаунс хибного краху)
        self._tts_unloaded = False      # True = НАВМИСНО вивантажений по простою (не крах)
        self._tts_logpath = os.path.expanduser("~/.local/kobzarai/logs/tts.log")
        self._tts_restart_at = 0.0      # анти-флуд: не рестартувати частіше, ніж раз/15с
        self._oll_was_up = None         # стан Ollama попереднього тіку (детект самопадіння)
        self._oll_miss = 0              # поспіль промахів ollama_up (дебаунс хибного краху)
        self._oll_stopped = False       # True = зупинена НАВМИСНО (тогл юзера) → watchdog мовчить
        self._oll_restart_at = 0.0      # анти-флуд: не рестартувати частіше, ніж раз/30с
        self._settings = None
        self._chat = None
        self._cooling = None            # стан термо-паузи з thermal.py (будь-який процес) → трей
        self.menu = [
            "mem_line", "thermal_line",
            rumps.MenuItem("Модель у RAM:"), "loaded_line", "loaded_line2", "loaded_line3", None,
            "hdr_voice",
            "speak_sel", "speak_clip", "tts_pause", "tts_stop", None,
            "hdr_services",
            "ollama_toggle", "ollama_reason", "unload_models", "tts_toggle", None,
            "chat_open", "settings", *_browser_chat_menu(), None,
            "quit",
        ]
        # Постійний підпис-причина під «Запустити Ollama»: без callback → завжди сірий
        # (неклікабельний), сховано доти, доки причина не настане (керується у refresh).
        self.menu["ollama_reason"].title = ""
        self.menu["ollama_reason"]._menuitem.setHidden_(True)
        self.menu["thermal_line"].title = ""
        self.menu["thermal_line"]._menuitem.setHidden_(True)   # видно лише під час термо-паузи
        for _k in ("loaded_line2", "loaded_line3"):            # 2-га/3-тя модель в RAM: спершу сховані
            self.menu[_k].title = ""
            self.menu[_k]._menuitem.setHidden_(True)
        self._sym_cache = {}  # кеш SF Symbol-іконок меню (template, під колір тексту меню)
        # секційні заголовки — нативний стиль: жирний дрібний напис вторинним кольором,
        # без callback (сірий/неклікабельний). Без ASCII-рамки «— … —».
        self._menu_header(self.menu["hdr_voice"], "Озвучення")
        self._menu_header(self.menu["hdr_services"], "Сервіси")
        self.menu["unload_models"].title = "Вивантажити LLM з RAM"
        self._set_menu_sym(self.menu["unload_models"], "arrow.down.circle")
        self.menu["speak_clip"].title = "Озвучити буфер обміну"
        self.menu["speak_sel"].title = "Озвучити виділене"
        self.menu["tts_pause"].title = "Пауза / продовжити"
        self.menu["tts_stop"].title = "Стоп озвучку"
        self.menu["chat_open"].title = "Чат…"
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
        if "browser_chats" in self.menu:
            self.menu["browser_chats"].title = "Браузерні чати…"
            self.menu["browser_chats"].set_callback(self.open_browser_chats)
        self.menu["quit"].set_callback(self.quit_all)
        self.hotkeys = Hotkeys(self); self.hotkeys.start()
        self.timer = rumps.Timer(self.refresh, 1); self.timer.start()
        self._log("APP LAUNCH")
        self._apply_autostart(cfg)

    def _apply_autostart(self, cfg):
        # Лише за явним opt-in у Налаштуваннях; запуск при ВІДКРИТТІ панелі, НЕ системний демон.
        try:
            if cfg.get("autostart_ollama") and not ollama_up():
                self._start_ollama()   # без диска тихо поверне False; причину видно в меню
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
                # ембед-моделі (bge-m3 тощо) не вміють generate → гріємо через /api/embed
                if is_embed_model(name):
                    ep, body = "embed", {"model": name, "input": " ", "keep_alive": "30m"}
                else:
                    ep, body = "generate", {"model": name, "prompt": "", "keep_alive": "30m"}
                urllib.request.urlopen(urllib.request.Request(
                    f"http://{OLLAMA_HOST}/api/{ep}",
                    json.dumps(body).encode(),
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
        self._pull_cancel.clear()
        threading.Thread(target=self._do_pull, args=(name,), daemon=True).start()

    def cancel_pull(self):
        self._pull_cancel.set()

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
                if getattr(s, "pull_cancel_btn", None) is not None:
                    s.pull_cancel_btn.setHidden_(pct is None)
            AppHelper.callAfter(go)
        status(f"Завантаження {short}…"); bar(0)
        try:
            payload = json.dumps({"model": name, "stream": True}).encode()
            req = urllib.request.Request(f"http://{OLLAMA_HOST}/api/pull", payload,
                                         {"Content-Type": "application/json"})
            last = -100
            with urllib.request.urlopen(req, timeout=7200) as resp:
                for line in resp:
                    if self._pull_cancel.is_set():
                        status("Скасовано"); bar(None); return
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

    def open_browser_chats(self, _):
        if not _browser_chat_menu():
            return
        if self._settings is None:
            self._settings = SettingsWindow.alloc().initWithPanel_(self)
        index = self._settings._ext_tab_index("browser")
        if index is not None:
            self._settings.show()
            self._settings.select_tab(index)

    def open_chat(self, _):
        if self._settings is None:
            self._settings = SettingsWindow.alloc().initWithPanel_(self)
        self._settings.show()
        self._settings.select_tab(3)

    def current_model(self, max_age=0):
        """Яку модель кличе чат просити відповідь. НЕ падати назад на випадкову
        встановлену модель, коли користувач свідомо обрав ембед (26.09 фікс: раніше
        вибір bge-m3 при увімкненій Базі знань все одно тягнув gemma з диска — RAG-only
        режим ніхто не просив)."""
        s = self._settings
        sel = s.sel_model if s is not None else None
        if sel:
            return None if is_embed_model(sel) else sel   # ембед обрано свідомо → в чат не пускати
        # нічого явно не обрано: спершу чат-модель, що вже сидить у RAM
        loaded = pick_chat_model([r.split()[0] for r in ps_loaded(max_age) if r.split()])
        if loaded:
            return loaded
        kb_on = bool(s is not None and getattr(s, "kb_on", False))
        if kb_on:
            return None   # База знань увімкнена — не піднімати LLM з диска сама, лишити RAG-only
        return pick_chat_model(list_models(max_age))

    def _update_activation(self):
        vis = ((self._settings is not None and self._settings.is_open)
               or (self._chat is not None and self._chat.is_open))
        try: NSApp.setActivationPolicy_(0 if vis else 1)  # Dock коли є вікно, інакше трей
        except Exception: pass

    def _menu_header(self, item, text):
        """Секційний заголовок меню: жирний дрібний напис вторинним кольором."""
        try:
            from AppKit import NSAttributedString, NSForegroundColorAttributeName, \
                NSFontAttributeName
            ats = NSAttributedString.alloc().initWithString_attributes_(
                text, {NSFontAttributeName: NSFont.boldSystemFontOfSize_(11.0),
                       NSForegroundColorAttributeName: NSColor.secondaryLabelColor()})
            item._menuitem.setAttributedTitle_(ats)
        except Exception:
            item.title = text

    def _menu_img(self, name, point=13.0):
        """Кешований SF Symbol для пункту меню (template → під колір тексту меню)."""
        img = self._sym_cache.get(name)
        if img is None:
            img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
            if img is not None:
                try:
                    cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(point, 5)
                    img = img.imageWithSymbolConfiguration_(cfg) or img
                except Exception:
                    pass
                img.setTemplate_(True)
            self._sym_cache[name] = img
        return img

    def _paint_ram_lines(self, loaded):
        """Меню трея: усі моделі в RAM (до 3) окремими сірими рядками."""
        head, rows = ram_menu_lines(loaded)
        self.menu["Модель у RAM:"].title = head
        for i, key in enumerate(("loaded_line", "loaded_line2", "loaded_line3")):
            it = self.menu[key]
            if i < len(rows):
                it.title = rows[i]; it._menuitem.setHidden_(False)
            else:
                it.title = ""; it._menuitem.setHidden_(True)

    def _set_menu_sym(self, item, name):
        try: item._menuitem.setImage_(self._menu_img(name))
        except Exception: pass

    def _set_icon(self, up, tts):
        try:
            if self._state == "synth":     name, tint = ("pause.fill" if self._pause_pending else "hourglass"), True
            elif self._state == "playing": name, tint = "waveform", True
            elif self._state == "paused":  name, tint = "pause.fill", True
            elif self._cooling:            name, tint = "thermometer.snowflake", True
            else:
                name = "cpu.fill" if up else "cpu"
                tint = tts
            btn = self._nsapp.nsstatusitem.button()
            img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, "KobzarAI")
            if not img:
                return
            if tint:
                c = NSImageSymbolConfiguration.configurationWithHierarchicalColor_(
                    NSColor.systemCyanColor() if name == "thermometer.snowflake" else NSColor.systemOrangeColor())
                img = img.imageWithSymbolConfiguration_(c) or img
                img.setTemplate_(False)
            else:
                img.setTemplate_(True)
            btn.setImage_(img); self.title = ""
        except Exception: pass

    def refresh(self, _):
        up = ollama_up(); free, swap = mem(); tts = tts_up()
        # детект самопадіння/підняття Ollama (юзер: «лама сама випала, чому?»)
        if self._oll_was_up is not None and up != self._oll_was_up:
            self._log("Ollama " + ("UP" if up else
                      ("DOWN (зупинена тоглом)" if self._oll_stopped else "DOWN (впала сама)")))
        self._oll_was_up = up
        # WATCHDOG Ollama (дзеркало TTS-watchdog нижче, задача task_20260715_001):
        # падає сама (OOM на 8ГБ) і без цього лишалась лежати до ручного тоглу,
        # тоді як TTS сам піднімався — звідси картина «TTS живий, Ollama мовчить».
        # Рестарт лише якщо: autostart_ollama увімкнено, зупинка НЕ навмисна,
        # ≥3 промахи поспіль (дебаунс), не частіше 1×/30с (не зациклитись на OOM-флапі).
        if not up:
            self._oll_miss += 1
        else:
            self._oll_miss = 0
        if (not up and not self._oll_stopped and self._oll_miss >= 3
                and load_cfg().get("autostart_ollama")
                and time.time() - self._oll_restart_at > 30):
            self._oll_restart_at = time.time()
            if self._start_ollama():
                self._log("WATCHDOG: Ollama лежить → рестарт")
        if self._tts_starting and tts:
            self._tts_starting = False; self._tts_unloaded = False
        # WATCHDOG (бег-сейф): сервер БУВ живий, а тепер впав, і це НЕ навмисне
        # вивантаження по простою й НЕ розігрів → це КРАХ. Логуємо причину (хвіст
        # tts.log) і, якщо autostart_tts увімкнено, тихо піднімаємо назад (не частіше
        # 1×/15с, щоб не зациклитись на OOM-флапі).
        # Дебаунс: один промах /health НЕ є крахом. Під час активної озвучки
        # (synth/playing/paused) single-Flask зайнятий і health законно лагає під
        # swap → промахи там ІГНОРУЄМО зовсім, інакше watchdog піднімав 2-й сервер
        # і ось це й валило памʼять. Крах визнаємо лише як ≥3 промахи поспіль у
        # стані спокою.
        if not tts:
            self._tts_miss += 1
        else:
            self._tts_miss = 0
        busy = self._state in ("synth", "playing", "paused")
        if (self._tts_was_up and not tts and not self._tts_starting
                and not self._tts_unloaded and not busy and self._tts_miss >= 3):
            crash_t = time.strftime('%Y-%m-%d %H:%M:%S')
            self._tts_log(f"CRASH detected at {crash_t} ({self._tts_miss}× /health miss; "
                          f"not idle-unload, not synth). free RAM {free}% swap {swap}M")
            now = time.time()
            if (load_cfg().get("autostart_tts") and now - self._tts_restart_at > 15):
                self._tts_restart_at = now
                self._tts_log("WATCHDOG: autostart_tts on → restarting server.")
                self._start_tts_server()
        # авто-вивантаження TTS з RAM по простою (лише коли не озвучуємо)
        idle_m = tts_idle_min()
        if (idle_m > 0 and tts and not self._tts_starting and self._state == "idle"
                and time.time() - self._tts_last_use > idle_m * 60):
            # ВАЖЛИВО: НЕ вбиваємо сервер (`kill lsof :5050` валив увесь Flask →
            # наступна озвучка = холодний старт ~20с). Шлемо /unload → звільняє
            # лише модель, Flask лишається живий, теплий старт ~секунди.
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{TTS_PORT}/unload",
                                             data=b"", method="POST")
                urllib.request.urlopen(req, timeout=4)
                ok = True
            except Exception as ex:
                self._tts_log(f"idle /unload failed: {ex}")
                ok = False
            self._tts_last_use = time.time()
            if ok:
                rumps.notification("TTS", "Модель вивантажено з RAM (простій)",
                                   f"{idle_m} хв без озвучки · сервер активний, голос підхопиться миттєво")
        # ПРИМІТКА (01.07.2026): пробував додати ескалацію — kill+рестарт Flask при
        # подвійному простої, щоб забрати залишок ~0.5-1ГБ, що /unload не звільняє
        # (C-алокатор лишає його поки живий процес). ВІДКОЧЕНО: це той самий kill-Flask
        # підхід, який 22.06.2026 вже був і давав ~20с холодний старт наступної озвучки —
        # саме заради усунення цього й зробили /unload-only фікс 24.06 (див.
        # issue_kobzarai_tts_crash). Залишок ~0.5-1ГБ — прийнятна ціна за миттєвий голос
        # після простою; не переоформлювати без нового рішення користувача.
        # Латч: «сервер бачили живим». True ставимо коли health відповів; під час
        # серії промахів НЕ скидаємо (інакше дебаунс краху ламається — was_up впаде
        # в False після 1-го промаху й крах ніколи не визнається). Скидаємо лише
        # коли крах підтверджено/сервер навмисно вивантажено.
        if tts:
            self._tts_was_up = True
        elif (self._tts_miss >= 3 and not busy) or self._tts_unloaded:
            self._tts_was_up = False
        # Скидаємо «завислий playing» ЛИШЕ коли жоден конвеєр не живий — інакше таймер
        # ловив проміжок між шматками (стан ще playing, шматок догрався) і занулював
        # _snd посеред читання → пауза переставала реагувати.
        if (self._tts_active == 0 and self._state == "playing"
                and self._snd is not None and not self._snd.isPlaying()):
            self._state = "idle"; self._snd = None
        self._cooling = None
        try:
            import thermal as _th
            self._cooling = _th.pause_state()
        except Exception: pass
        tl = self.menu["thermal_line"]
        if self._cooling:
            c = self._cooling
            tl.title = "Охолодження: %s на паузі · %.0f°C → %.0f°C" % (
                c.get("who", "ембед"), c.get("t", 0), c.get("ra", 0))
            self._set_menu_sym(tl, "thermometer.snowflake")
        tl._menuitem.setHidden_(not self._cooling)
        self._set_icon(up, tts)
        hk = load_cfg().get("hotkeys", {})
        def _ch(act):
            c = fmt_hotkey(hk.get(act)); return "" if c == "—" else c
        try: sw = float(swap)
        except Exception: sw = 0.0
        self.menu["mem_line"].title = f"RAM вільно {free}% · swap {swap}M"
        self._set_menu_sym(self.menu["mem_line"], "exclamationmark.triangle") if sw > 3000 \
            else self.menu["mem_line"]._menuitem.setImage_(None)
        set_menu_title(self.menu["speak_sel"], "Озвучити виділене", _ch("speak_sel"))
        set_menu_title(self.menu["speak_clip"], "Озвучити буфер обміну", _ch("speak_clip"))
        set_menu_title(self.menu["tts_stop"], "Стоп озвучку", _ch("tts_stop"))
        self.menu["ollama_toggle"].title = "Зупинити Ollama" if up else "Запустити Ollama"
        self._set_menu_sym(self.menu["ollama_toggle"], "stop.fill" if up else "play.fill")
        # Підпис-причина прямо під кнопкою: видно ЛИШЕ коли Ollama лежить І диск з
        # моделями відсутній (саме тоді start-ollama.sh тихо вмирає). Якщо Ollama жива
        # АБО диск на місці — ховаємо, щоб не «заліпало».
        reason = self.menu["ollama_reason"]
        blocker = None if up else ollama_blocker()
        if blocker:
            reason.title = blocker[0]
            self._set_menu_sym(reason, "exclamationmark.triangle")
            reason._menuitem.setHidden_(False)
        else:
            reason._menuitem.setHidden_(True)
        if self._tts_starting:
            self.menu["tts_toggle"].title = "Голос запускається…"
            self._set_menu_sym(self.menu["tts_toggle"], "hourglass")
        else:
            self.menu["tts_toggle"].title = "Зупинити голос (TTS)" if tts else "Запустити голос (TTS)"
            self._set_menu_sym(self.menu["tts_toggle"], "stop.fill" if tts else "play.fill")
        self._paint_ram_lines(ps_loaded(3))
        if self._state == "synth":
            p, sym = ("Продовжити (стартує на паузі)", "play.fill") if self._pause_pending \
                else ("Синтез…", "hourglass")
        elif self._state == "playing": p, sym = "Пауза", "pause.fill"
        elif self._state == "paused":  p, sym = "Продовжити", "play.fill"
        else: p, sym = "Пауза / продовжити", "pause.fill"
        set_menu_title(self.menu["tts_pause"], p, _ch("tts_pause"))
        self._set_menu_sym(self.menu["tts_pause"], sym)
        active = self._state in ("synth", "playing", "paused")
        self.menu["tts_stop"].set_callback(self.stop_speech if active else None)
        self.menu["tts_pause"].set_callback(
            self.pause_speech if self._state in ("synth", "playing", "paused") else None)
        self.menu["unload_models"].set_callback(self.unload_models if loaded else None)
        if self._settings is not None:
            self._settings.refresh(up)

    # --- Ollama ---
    def _start_ollama(self):
        """Старт Ollama з перевіркою диска. start-ollama.sh при відсутній папці моделей
        тихо робить exit 0 (fire-and-forget Popen → панель не дізнається про провал).
        Тому перевіряємо доступність тут і ЯВНО кажемо юзеру, якщо диск відпав."""
        blocker = ollama_blocker()
        if blocker:
            # 🔴 Раніше тут був голий `return False`: людина тиснула «Запустити
            # Ollama» і НІЧОГО не відбувалось — ні вікна, ні помилки. Причина
            # лежала рядком у меню, яке закривається в мить кліку, тобто її
            # фактично не існувало. Той самий урок уже стоїть у _start_tts_server
            # десятьма екранами нижче — сюди його не донесли.
            rumps.alert(title="Ollama не запускається", message=blocker[1])
            return False
        # start_new_session: відв'язати від процес-групи апки, інакше launchd
        # прибирає Ollama разом із KobzarAI при кожному перезапуску панелі
        # (TTS-лаунчер це вже робить — тут було пропущено)
        subprocess.Popen(["bash", START_OLLAMA], start_new_session=True)
        self._oll_stopped = False       # будь-який старт знімає «навмисну зупинку»
        return True

    def toggle_ollama(self, _):
        if ollama_up():
            # позначити як НАВМИСНУ зупинку, інакше watchdog у refresh() підніме назад
            self._oll_stopped = True
            sh("pkill -f 'ollama serve'"); notify("KobzarAI", "Ollama зупинена", "")
        elif self._start_ollama(): notify("KobzarAI", "Ollama запускається…", "")

    def unload_models(self, _):
        for r in ps_loaded(): sh(f"{OLLAMA} stop {shlex.quote(r.split()[0])}")
        rumps.notification("Ollama", "Моделі вивантажено з RAM", "сервер далі працює")

    # --- TTS сервер ---
    def toggle_tts(self, _):
        if tts_up():
            sh(f"kill $(lsof -ti :{TTS_PORT})")
            self._tts_starting = False
            # КРИТ.: позначити як НАВМИСНУ зупинку, інакше watchdog у refresh()
            # бачить «port :5050 dead» і піднімає сервер назад (юзер мусив клікати
            # стоп кілька разів наввипередки). _start_tts_server скидає цей прапорець.
            self._tts_unloaded = True
            self._tts_was_up = False
            self._tts_miss = 0
            rumps.notification("TTS", "Сервер зупинено", "")
        else:
            self._start_tts_server()
            rumps.notification("TTS", "Сервер запускається…", "перша загрузка ~20с (torch+модель)")

    def _log(self, msg):
        """Загальний лог застосунку → ~/.local/kobzarai/logs/app.log (події сервісів,
        крахи, відкриття вікон). Щоб видно було «що відбувається», коли щось падає само."""
        try:
            p = os.path.expanduser("~/.local/kobzarai/logs/app.log")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            try:    # м'яка ротація
                if os.path.exists(p) and os.path.getsize(p) > 1_000_000:
                    with open(p, "r", errors="replace") as f:
                        tail = f.readlines()[-2000:]
                    with open(p, "w") as f:
                        f.writelines(tail)
            except Exception: pass
            free, swap = mem()
            with open(p, "a") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}  "
                        f"(free {free}% swap {swap}M)\n")
        except Exception:
            pass

    def _tts_log(self, msg):
        """Краш-трейс/події TTS → tts.log І дзеркало у загальний app.log."""
        self._log("TTS: " + msg)
        try:
            p = getattr(self, "_tts_logpath", None) or os.path.expanduser(
                "~/.local/kobzarai/logs/tts.log")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "a") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        except Exception:
            pass

    def _start_tts_server(self):
        # Установка з --no-tts не кладе TTS-сервер. Без цієї перевірки панель
        # намагалась запустити неіснуючий start-tts.sh, і людина бачила вічне
        # «Запускаю голос…» без жодного пояснення. Підпис і стан мають бути
        # зв'язані кодом, а не сподіванням, що людина пам'ятає свій прапорець.
        if not os.path.isfile(f"{TTS_DIR}/start-tts.sh"):
            self._tts_starting = False
            rumps.alert(
                title="Озвучку не встановлено",
                message="Кит ставився з --no-tts, тому голосового сервера тут немає.\n\n"
                        "Щоб додати озвучку, виконай у теці KobzarAI:\n"
                        "    ./setup.sh\n\n"
                        "Керування Ollama і База знань працюють без неї.")
            return
        self._tts_unloaded = False     # явний старт скидає позначку «навмисно вивантажено»
        # Лок проти подвійного старту: start-tts.sh уже гардить по lsof :5050,
        # але _tts_starting не дає панелі плодити паралельні bash поки сервер гріється.
        if getattr(self, "_tts_starting", False) and tts_up():
            return
        self._tts_starting = True
        # mps ВІДКОЧЕНО (01.07.2026): дав 2-4× швидший синтез, АЛЕ vmmap показав реальний
        # Physical Footprint ~3.9-4.1 ГБ (Metal/GPU-буфери НЕ видно в `ps` RSS, тому перша
        # перевірка це проґавила) — на 8 ГБ це дорожче за виграш у швидкості, саме воно
        # душило машину в своп. Дефолт знову cpu; TTS_DEVICE з оточення й далі перекриває,
        # якщо колись захочеться увімкнути вручну на машині з більшим запасом RAM.
        srv_env = {**os.environ,
                   "TTS_DEVICE": os.environ.get("TTS_DEVICE", "cpu"),
                   "PYTORCH_ENABLE_MPS_FALLBACK": "1"}
        # КРИТ.: output server.py раніше йшов у /dev/null → причину крахів (OOM/трейс)
        # неможливо було прочитати. Тепер пишемо у app-scoped лог (НЕ чіпаючи спільний
        # з Cherry start-tts.sh). Тримаємо хвіст: при старті лишаємо ~2000 рядків.
        try:
            logdir = os.path.expanduser("~/.local/kobzarai/logs")
            os.makedirs(logdir, exist_ok=True)
            logpath = os.path.join(logdir, "tts.log")
            self._tts_logpath = logpath
            try:    # м'яка ротація: щоб лог не ріс безмежно
                if os.path.exists(logpath) and os.path.getsize(logpath) > 1_000_000:
                    with open(logpath, "r", errors="replace") as f:
                        tail = f.readlines()[-2000:]
                    with open(logpath, "w") as f:
                        f.writelines(tail)
            except Exception: pass
            lf = open(logpath, "a", buffering=1)
            lf.write(f"\n===== TTS START {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
            lf.flush()
            subprocess.Popen(["bash", f"{TTS_DIR}/start-tts.sh"],
                             stdout=lf, stderr=subprocess.STDOUT, start_new_session=True,
                             env=srv_env)
            lf.close()          # дочірній процес вже задублював fd собі — батьківський більше не потрібен
        except Exception:
            if 'lf' in locals():
                try: lf.close()
                except Exception: pass
            subprocess.Popen(["bash", f"{TTS_DIR}/start-tts.sh"], start_new_session=True,
                             env=srv_env)

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
                              "pause": getattr(self, "pause", 0.15),
                              "group_chars": TTS_GROUP_CHARS}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{TTS_PORT}/v1/audio/speech",
                                     payload, {"Content-Type": "application/json"})
        audio = urllib.request.urlopen(req, timeout=120).read()
        self._tts_last_use = time.time()          # скидаємо лічильник простою
        if gen != self._speak_gen: return None
        # попередній temp-WAV на цей момент уже дограв (_play_sound синхронний,
        # повертається лише після завершення шматка) — можна прибрати, інакше
        # накопичуються в /tmp без обмеження
        prev = getattr(self, "_last_tmp_wav", None)
        if prev:
            try: os.remove(prev)
            except Exception: pass
        f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False); f.write(audio); f.close()
        self._last_tmp_wav = f.name
        snd = NSSound.alloc().initWithContentsOfFile_byReference_(f.name, True)
        if snd is not None:
            try: snd.setVolume_(float(getattr(self, "volume", 1.0)))
            except Exception: pass
            try: snd.setPlaybackDeviceIdentifier_(getattr(self, "out_device", None))  # None=системний
            except Exception: pass
        return snd

    def _play_sound(self, snd, gen):
        """Програти й дочекатися кінця, поважаючи паузу/стоп. False = скасовано."""
        if gen != self._speak_gen: return False
        self._snd = snd; snd.play()
        if self._pause_pending:                 # пауза озброєна під час синтезу — стартуємо вже на паузі
            self._pause_pending = False
            try: snd.pause()
            except Exception: pass
            self._state = "paused"
        else:
            self._state = "playing"
        # play() повертає одразу, isPlaying() ще не True кілька мс — без цього
        # очікування перший же опит нижче бачив False і шматок мовчки проскакував
        # (на довгих текстах багато шматків → читання «обривалося»).
        t0 = time.time()
        while not snd.isPlaying() and self._state != "paused":
            if gen != self._speak_gen:
                try: snd.stop()
                except Exception: pass
                return False
            if time.time() - t0 > 1.0: break    # звук міг бути порожній/миттєвий — не зависаємо
            time.sleep(0.01)
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
        chunks = split_blocks(text[:TTS_MAX_CHARS]) or [text[:700]]
        def run():
            pool = NSAutoreleasePool.alloc().init()
            self._tts_active += 1
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
                self._tts_active -= 1; del pool
        threading.Thread(target=run, daemon=True).start()

    def _speak_stream(self, text, gen):
        """Конвеєр ①: продюсер синтезує наступний шматок у фоні, поки плеєр грає
        поточний → майже миттєвий старт, без дірок між реченнями. База не чіпається."""
        chunks = split_stream(text[:TTS_MAX_CHARS]) or [text[:700]]
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
            self._tts_active += 1
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
                    pz = getattr(self, "pause", 0.0)
                    if not first and pz > 0:           # явна пауза між шматками; 0 = без тиші
                        t_end = time.time() + pz
                        while time.time() < t_end:
                            if gen != self._speak_gen: return
                            time.sleep(0.04)
                    first = False
                    if not self._play_sound(snd, gen): return
                self._state = "idle"
            except Exception as ex:
                self._state = "idle"; rumps.notification("TTS", "Помилка", str(ex)[:80])
            finally:
                self._tts_active -= 1; del pool
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
        self._live_buf = ""        # батчинг: копимо речення, синтезуємо шматками
        self._live_nflush = 0      # перший шматок малий (швидкий старт), далі більший
        sq = _q.Queue(maxsize=4)   # готові звуки — синтез біжить НАПЕРЕД програвання
        SND_END = object()

        # СИНТЕЗ: тягне текст від LLM, синтезує й кладе готовий звук у sq.
        # Працює поки грає попередній шматок → нема паузи "на синтез наступного".
        def synth_loop():
            pool = NSAutoreleasePool.alloc().init()
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
                    while gen == self._speak_gen:       # put, що прокидається на скасування
                        try: sq.put(snd, timeout=0.2); break
                        except _q.Full: continue
            finally:
                sq.put(SND_END); del pool

        # ПРОГРАВАННЯ: грає готові звуки впритул. Між ними — лише явна пауза (0 = 0).
        def play_loop():
            pool = NSAutoreleasePool.alloc().init()
            first = True
            self._tts_active += 1
            try:
                while True:
                    if gen != self._speak_gen: return
                    try: snd = sq.get(timeout=0.2)
                    except _q.Empty: continue
                    if snd is SND_END: break
                    if gen != self._speak_gen: return
                    pz = getattr(self, "pause", 0.0)
                    if not first and pz > 0:           # жодної підлоги: 0 = без тиші
                        t_end = time.time() + pz
                        while time.time() < t_end:
                            if gen != self._speak_gen: return
                            time.sleep(0.04)
                    first = False
                    if not self._play_sound(snd, gen): return
                self._state = "idle"
            except Exception:
                self._state = "idle"
            finally:
                self._tts_active -= 1; del pool
        threading.Thread(target=synth_loop, daemon=True).start()
        threading.Thread(target=play_loop, daemon=True).start()
        return gen

    def _live_flush(self, gen):
        """Злити накопичений буфер у чергу синтезу одним шматком."""
        live = getattr(self, "_live", None)
        if not (live and live[0] == gen and gen == self._speak_gen):
            self._live_buf = ""; return
        buf = (getattr(self, "_live_buf", "") or "").strip()
        self._live_buf = ""
        if buf:
            live[1].put(buf)
            self._live_nflush = getattr(self, "_live_nflush", 0) + 1

    def _live_feed(self, gen, sentence):
        live = getattr(self, "_live", None)
        if not (live and live[0] == gen and gen == self._speak_gen):
            return
        sentence = (sentence or "").strip()
        if not sentence:
            return
        self._live_buf = (self._live_buf + " " + sentence).strip() if getattr(self, "_live_buf", "") else sentence
        # РЕАЛТАЙМ > згладжування: перше речення — одразу (миттєвий старт), далі
        # зливаємо лише зовсім короткі фрагменти (<50), повноцінні речення йдуть негайно.
        thresh = 1 if getattr(self, "_live_nflush", 0) == 0 else 50
        if len(self._live_buf) >= thresh:
            self._live_flush(gen)

    def _live_end(self, gen):
        live = getattr(self, "_live", None)
        if live and live[0] == gen:
            self._live_flush(gen)                      # залишок буфера
            live[1].put(live[2])                       # END-сентинел

    def speak_clipboard(self, _): self._speak(sh("pbpaste"))

    def speak_selection(self, _):
        txt = ax_selection() or selection_via_clipboard()
        self._speak(txt)

    def pause_speech(self, _):
        if self._state == "synth":              # ще синтезуємо — озброюємо/знімаємо відкладену паузу
            self._pause_pending = not self._pause_pending
            return
        if self._snd is None:
            # конвеєр живий, але між шматками звуку ще нема → відкладена пауза на наступний
            if self._tts_active: self._pause_pending = not self._pause_pending
            return
        if self._state == "playing":
            if self._snd.isPlaying():
                if self._snd.pause(): self._state = "paused"
            elif self._tts_active:              # шматок догрався, наступний ще не стартував
                self._pause_pending = not self._pause_pending
        elif self._state == "paused":
            if self._snd.resume(): self._state = "playing"

    def stop_speech(self, _):
        self._speak_gen += 1            # скасувати будь-який синтез, що ще триває
        self._pause_pending = False
        if self._snd is not None:
            try: self._snd.stop()
            except Exception: pass
        self._snd = None; self._state = "idle"
        prev = getattr(self, "_last_tmp_wav", None)
        if prev:
            try: os.remove(prev)
            except Exception: pass
            self._last_tmp_wav = None

    def quit_all(self, _):
        self.stop_speech(None)
        for r in ps_loaded(): sh(f"{OLLAMA} stop {shlex.quote(r.split()[0])}")
        sh("pkill -f 'ollama serve'")
        sh(f"kill $(lsof -ti :{TTS_PORT})")
        rumps.quit_application()


if __name__ == "__main__":
    _p = Panel()
    if os.environ.get("KOBZARAI_OPEN_SETTINGS"):  # тест-хук: одразу показати Налаштування
        def _open_once(t):
            t.stop(); _p.open_settings(None)
            if os.environ.get("KOBZARAI_CHAT_DEMO") and _p._settings:
                s = _p._settings
                s.sessions[0]["title"] = "Три кольори"
                s.sessions[0]["ts"] = time.time()
                s.sessions[0]["history"] = [
                    {"role": "user", "content": "Привіт! Назви три кольори українською."},
                    {"role": "assistant", "content": "Звісно: червоний, зелений та синій."}]
                s.sessions.append({"title": "Рецепт борщу", "ts": time.time() - 86400,
                    "history": [{"role": "user", "content": "Як зварити борщ?"},
                    {"role": "assistant", "content": "1. Бульйон.\n2. Засмажка.\n3. Капуста + картопля."}]})
                s.sessions.append({"title": "Python-питання", "ts": time.time() - 5 * 86400,
                                   "history": []})
                s._reload_hist(); s._render_session()
            _sv = os.environ.get("KOBZARAI_SCROLLTEST")   # тест-хук: проскролити на N px
            if _sv and _p._settings and _p._settings._scroll is not None:
                def _do_scroll(t2):
                    t2.stop()
                    try:
                        clip = _p._settings._scroll.contentView()
                        o = clip.bounds().origin
                        clip.scrollToPoint_((o.x, float(_sv)))
                        _p._settings._scroll.reflectScrolledClipView_(clip)
                        _ls = os.environ.get("KOBZARAI_LIBSEL")   # тест-хук: виділити рядок бібліотеки
                        lt = getattr(_p._settings, "lib_table", None)
                        if _ls and lt is not None:
                            from Foundation import NSIndexSet
                            lt.selectRowIndexes_byExtendingSelection_(
                                NSIndexSet.indexSetWithIndex_(int(_ls)), False)
                    except Exception as e:
                        print("scrolltest err", e)
                rumps.Timer(_do_scroll, 1.5).start()
        rumps.Timer(_open_once, 1).start()
    _p.run()
