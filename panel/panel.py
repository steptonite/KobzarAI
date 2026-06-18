#!/usr/bin/env python3
# LocalAI Panel — menu-bar керування Ollama + TTS + RAM + глобальні хоткеї. Без автозапуску, ручний СТОП.
import os, subprocess, tempfile, threading, time, urllib.request, json
import rumps
import objc
from AppKit import (NSImage, NSSound, NSWindow, NSBackingStoreBuffered,
    NSWindowStyleMaskTitled, NSWindowStyleMaskClosable, NSTextField, NSPopUpButton,
    NSButton, NSView, NSApp, NSColor, NSImageSymbolConfiguration, NSApplication,
    NSWorkspace, NSPasteboard)
from Foundation import NSObject, NSAutoreleasePool, NSMakeRect
from PyObjCTools import AppHelper

# Зовнішній диск з моделями Ollama. Задай свій через env LOCALAI_DISK,
# напр.: export LOCALAI_DISK="/Volumes/MySSD"
APA = os.environ.get("LOCALAI_DISK", "/Volumes/ExternalSSD")
OLLAMA = "/opt/homebrew/bin/ollama"
MODELS_DIR = f"{APA}/ollama-models"
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
    e = dict(os.environ); e["OLLAMA_MODELS"] = MODELS_DIR
    if env: e.update(env)
    try: return subprocess.run(cmd, shell=True, capture_output=True, text=True, env=e, timeout=20).stdout.strip()
    except Exception as ex: return f"ERR {ex}"


def ollama_up():
    try: urllib.request.urlopen(f"http://{OLLAMA_HOST}/api/version", timeout=2); return True
    except Exception: return False


def tts_up():
    try: urllib.request.urlopen(f"http://127.0.0.1:{TTS_PORT}/health", timeout=2); return True
    except Exception: return False


def mem():
    free = sh("memory_pressure 2>/dev/null | sed -n 's/.*free percentage: \\([0-9]*\\)%.*/\\1/p'")
    swap = sh("sysctl -n vm.swapusage 2>/dev/null | sed -n 's/.*used = \\([0-9.]*\\)M.*/\\1/p'")
    return free or "?", swap or "?"


def ps_loaded():
    out = sh(f"{OLLAMA} ps 2>/dev/null")
    return [l for l in out.splitlines()[1:] if l.strip()]


def list_models():
    out = sh(f"{OLLAMA} list 2>/dev/null")
    return [l.split()[0] for l in out.splitlines()[1:] if l.strip()]


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


# --- вікно налаштувань: голос + перепризначення хоткеїв ---
class SettingsWindow(NSObject):
    def initWithPanel_(self, panel):
        self = objc.super(SettingsWindow, self).init()
        if self is None:
            return None
        self.panel = panel
        self.win = None
        self.hk_btns = {}
        return self

    @objc.python_method
    def show(self):
        if self.win is None:
            self._build()
        NSApp.activateIgnoringOtherApps_(True)
        self.win.makeKeyAndOrderFront_(None)
        self.refresh()

    @objc.python_method
    def _label(self, text, x, y, w):
        f = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, 20))
        f.setStringValue_(text); f.setBezeled_(False); f.setDrawsBackground_(False)
        f.setEditable_(False); f.setSelectable_(False)
        self.win.contentView().addSubview_(f)
        return f

    @objc.python_method
    def _build(self):
        W, H = 380, 290
        self.win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable, NSBackingStoreBuffered, False)
        self.win.setTitle_("LocalAI — Налаштування")
        self.win.center()
        self._label("Голос:", 20, H - 45, 80)
        pop = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(100, H - 48, 260, 26), False)
        pop.addItemsWithTitles_(VOICES)
        if self.panel.voice in VOICES:
            pop.selectItemWithTitle_(self.panel.voice)
        pop.setTarget_(self); pop.setAction_("voiceChanged:")
        self.win.contentView().addSubview_(pop)

        self._label("Хоткеї (клік «Записати» → натисни комбо, Esc — скасувати):", 20, H - 80, 350)
        y = H - 110
        for i, (act, label) in enumerate(HK_LABELS):
            self._label(label, 20, y, 160)
            cur = NSTextField.alloc().initWithFrame_(NSMakeRect(180, y, 70, 20))
            cur.setBezeled_(False); cur.setDrawsBackground_(False)
            cur.setEditable_(False); cur.setSelectable_(False)
            self.win.contentView().addSubview_(cur)
            self.hk_btns[act] = cur
            rec = NSButton.alloc().initWithFrame_(NSMakeRect(255, y - 4, 80, 26))
            rec.setTitle_("Записати"); rec.setBezelStyle_(1); rec.setTag_(i)
            rec.setTarget_(self); rec.setAction_("recordHK:")
            self.win.contentView().addSubview_(rec)
            clr = NSButton.alloc().initWithFrame_(NSMakeRect(335, y - 4, 30, 26))
            clr.setTitle_("✕"); clr.setBezelStyle_(1); clr.setTag_(i)
            clr.setTarget_(self); clr.setAction_("clearHK:")
            self.win.contentView().addSubview_(clr)
            y -= 34

    def voiceChanged_(self, sender):
        v = sender.titleOfSelectedItem()
        self.panel.voice = v
        cfg = load_cfg(); cfg["voice"] = v; save_cfg(cfg)

    def recordHK_(self, sender):
        act = HK_LABELS[sender.tag()][0]
        self.panel.hotkeys.recording = act

    def clearHK_(self, sender):
        act = HK_LABELS[sender.tag()][0]
        cfg = load_cfg(); hk = cfg.get("hotkeys", dict(DEFAULT_HOTKEYS))
        hk[act] = None; cfg["hotkeys"] = hk; save_cfg(cfg)
        self.panel.hotkeys.reload()

    @objc.python_method
    def refresh(self):
        if self.win is None:
            return
        hk = load_cfg().get("hotkeys", DEFAULT_HOTKEYS)
        rec = self.panel.hotkeys.recording
        for act, fld in self.hk_btns.items():
            fld.setStringValue_("натисни…" if rec == act else fmt_hotkey(hk.get(act)))


class Panel(rumps.App):
    def __init__(self):
        super().__init__("AI", quit_button=None)
        try:
            NSApplication.sharedApplication().setActivationPolicy_(1)  # accessory (без док-іконки)
        except Exception: pass
        try:
            from ApplicationServices import AXIsProcessTrustedWithOptions
            AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": True})
        except Exception: pass
        cfg = load_cfg()
        if "hotkeys" not in cfg:
            cfg["hotkeys"] = DEFAULT_HOTKEYS; save_cfg(cfg)
        self.voice = cfg.get("voice") if cfg.get("voice") in VOICES else VOICES[0]
        self._snd = None
        self._state = "idle"
        self._tts_starting = False
        self._settings = None
        self.menu = [
            "mem_line", None,
            "ollama_toggle", "unload_models",
            rumps.MenuItem("Завантажено в RAM:"), "loaded_line", None,
            ("Моделі на диску", []), None,
            "tts_toggle",
            rumps.MenuItem("— Озвучення —"),
            "speak_clip", "speak_sel", "tts_pause", "tts_stop", None,
            "settings", "quit",
        ]
        self.menu["unload_models"].title = "Вивантажити моделі з RAM"
        self.menu["speak_clip"].title = "Озвучити буфер обміну"
        self.menu["speak_sel"].title = "Озвучити виділене"
        self.menu["tts_pause"].title = "Пауза / продовжити"
        self.menu["tts_stop"].title = "Стоп озвучку"
        self.menu["settings"].title = "Налаштування…"
        self.menu["quit"].title = "Вийти (зупинити Ollama + TTS)"
        self.menu["ollama_toggle"].set_callback(self.toggle_ollama)
        self.menu["unload_models"].set_callback(self.unload_models)
        self.menu["tts_toggle"].set_callback(self.toggle_tts)
        self.menu["speak_clip"].set_callback(self.speak_clipboard)
        self.menu["speak_sel"].set_callback(self.speak_selection)
        self.menu["tts_pause"].set_callback(self.pause_speech)
        self.menu["tts_stop"].set_callback(self.stop_speech)
        self.menu["settings"].set_callback(self.open_settings)
        self.menu["quit"].set_callback(self.quit_all)
        self._fill_static()
        self.hotkeys = Hotkeys(self); self.hotkeys.start()
        self.timer = rumps.Timer(self.refresh, 1); self.timer.start()

    def _fill_static(self):
        mm = self.menu["Моделі на диску"]
        for m in list_models():
            mm.add(rumps.MenuItem(m, callback=self.noop))

    def noop(self, _): pass

    def open_settings(self, _):
        if self._settings is None:
            self._settings = SettingsWindow.alloc().initWithPanel_(self)
        self._settings.show()

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
        self.menu["mem_line"].title = f"RAM вільно {free}% · swap {swap}M"
        self.menu["ollama_toggle"].title = "■ Зупинити Ollama" if up else "▶ Запустити Ollama"
        if self._tts_starting:
            self.menu["tts_toggle"].title = "⏳ Голос запускається…"
        else:
            self.menu["tts_toggle"].title = "■ Зупинити голос (TTS)" if tts else "▶ Запустити голос (TTS)"
        loaded = ps_loaded()
        self.menu["loaded_line"].title = "   " + (loaded[0].split("  ")[0].strip() if loaded else "(нічого — RAM вільна)")
        if self._state == "synth":   p = "⏳ Синтез…"
        elif self._state == "playing": p = "❚❚ Пауза"
        elif self._state == "paused":  p = "▶ Продовжити"
        else: p = "Пауза / продовжити"
        self.menu["tts_pause"].title = p
        if self._settings is not None:
            self._settings.refresh()

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
    def _speak(self, text):
        text = (text or "").strip()
        if not text: rumps.notification("TTS", "Порожньо", ""); return
        self.stop_speech(None)
        self._state = "synth"
        def run():
            pool = NSAutoreleasePool.alloc().init()
            try:
                if not self._wait_tts():
                    self._state = "idle"; rumps.notification("TTS", "Сервер не піднявся", ""); return
                payload = json.dumps({"model": "styletts2-ua", "input": text[:2000], "voice": self.voice}).encode()
                req = urllib.request.Request(f"http://127.0.0.1:{TTS_PORT}/v1/audio/speech",
                                             payload, {"Content-Type": "application/json"})
                audio = urllib.request.urlopen(req, timeout=120).read()
                f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False); f.write(audio); f.close()
                snd = NSSound.alloc().initWithContentsOfFile_byReference_(f.name, True)
                if snd is None:
                    self._state = "idle"; rumps.notification("TTS", "Не зміг відтворити", ""); return
                try: snd.setPlaybackDeviceIdentifier_(None)
                except Exception: pass
                self._snd = snd; self._state = "playing"; snd.play()
            except Exception as ex:
                self._state = "idle"; rumps.notification("TTS", "Помилка", str(ex)[:80])
            finally:
                del pool
        threading.Thread(target=run, daemon=True).start()

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
    Panel().run()
