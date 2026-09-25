"""thermal.py — термо-гейт для важких локальних задач KobzarAI (реіндекс бази знань).

ЧОМУ: індексація великої теки ганяє bge-m3 через Ollama пачками без пауз — на
пасивному MacBook Air SoC розігрівається за 100°C.
Рішення таке саме, як на Писарі (guard.py + soctemp): читаємо температуру SoC через
IOHIDEventSystem (той самий шлях, що Stats/macmon — БЕЗ sudo/пароля) і, якщо гаряче,
СТАВИМО ПРОЦЕС НА ПАУЗУ до охолодження. На відміну від guard.py ми НІКОЛИ не вбиваємо
задачу — реіндекс має дійти до кінця, лише повільніше. Пауза, не обрив.

ПОРТАТИВНІСТЬ: якщо температуру прочитати не вдалось (не Apple Silicon, нема сенсорів,
нема pyobjc) — усе тихо стає no-op, і індексація йде як завжди. Апка не ламається в
того, хто просто її завантажив. Модуль імпортується ліниво і в try/except.

Пороги (°C) — консервативніші за Писаря, бо реіндекс крутиться на пасивному Air без
підставки-кулера: пауза при 92, продовження при 84, стеля однієї паузи 240 с.
Перевизначаються через env: KOBZAR_COOL_AT / KOBZAR_RESUME_AT / KOBZAR_MAX_COOL.
"""
import json
import os
import time

# ── читач температури SoC через IOHIDEventSystem (копія логіки soctemp Писаря) ──
_read_impl = None


def _build_reader():
    """Одноразово збирає ctypes-міст до IOKit. Повертає callable -> {sensor: °C} або None."""
    import ctypes
    import ctypes.util
    import objc
    from CoreFoundation import kCFStringEncodingUTF8

    iokit = ctypes.CDLL(ctypes.util.find_library("IOKit"))
    cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))

    kIOHIDEventTypeTemperature = 15
    kHIDPage_AppleVendor = 0xFF00
    kHIDUsage_AppleVendor_TemperatureSensor = 0x0005

    cf.CFDictionaryCreateMutable.restype = ctypes.c_void_p
    cf.CFNumberCreate.restype = ctypes.c_void_p
    cf.CFNumberCreate.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFArrayGetCount.restype = ctypes.c_long
    cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
    cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
    cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
    cf.CFDictionarySetValue.argtypes = [ctypes.c_void_p] * 3

    iokit.IOHIDEventSystemClientCreate.restype = ctypes.c_void_p
    iokit.IOHIDEventSystemClientCreate.argtypes = [ctypes.c_void_p]
    iokit.IOHIDEventSystemClientSetMatching.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    iokit.IOHIDEventSystemClientCopyServices.restype = ctypes.c_void_p
    iokit.IOHIDEventSystemClientCopyServices.argtypes = [ctypes.c_void_p]
    iokit.IOHIDServiceClientCopyProperty.restype = ctypes.c_void_p
    iokit.IOHIDServiceClientCopyProperty.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    iokit.IOHIDServiceClientCopyEvent.restype = ctypes.c_void_p
    iokit.IOHIDServiceClientCopyEvent.argtypes = [ctypes.c_void_p, ctypes.c_int64,
                                                  ctypes.c_int32, ctypes.c_int64]
    iokit.IOHIDEventGetFloatValue.restype = ctypes.c_double
    iokit.IOHIDEventGetFloatValue.argtypes = [ctypes.c_void_p, ctypes.c_int32]

    def _cfstr(s):
        return cf.CFStringCreateWithCString(None, s.encode(), kCFStringEncodingUTF8)

    def _cfnum(n):
        v = ctypes.c_int32(n)
        return cf.CFNumberCreate(None, 3, ctypes.byref(v))

    def read():
        m = cf.CFDictionaryCreateMutable(
            None, 0,
            ctypes.byref(ctypes.c_void_p.in_dll(cf, "kCFTypeDictionaryKeyCallBacks")),
            ctypes.byref(ctypes.c_void_p.in_dll(cf, "kCFTypeDictionaryValueCallBacks")))
        cf.CFDictionarySetValue(m, _cfstr("PrimaryUsagePage"), _cfnum(kHIDPage_AppleVendor))
        cf.CFDictionarySetValue(m, _cfstr("PrimaryUsage"),
                                _cfnum(kHIDUsage_AppleVendor_TemperatureSensor))
        client = iokit.IOHIDEventSystemClientCreate(None)
        iokit.IOHIDEventSystemClientSetMatching(client, m)
        services = iokit.IOHIDEventSystemClientCopyServices(client)
        if not services:
            return {}
        out = {}
        for i in range(cf.CFArrayGetCount(services)):
            sc = cf.CFArrayGetValueAtIndex(services, i)
            name_ref = iokit.IOHIDServiceClientCopyProperty(sc, _cfstr("Product"))
            name = objc.objc_object(c_void_p=ctypes.c_void_p(name_ref)) if name_ref else None
            ev = iokit.IOHIDServiceClientCopyEvent(sc, kIOHIDEventTypeTemperature, 0, 0)
            if ev:
                val = iokit.IOHIDEventGetFloatValue(ev, kIOHIDEventTypeTemperature << 16)
                out[str(name) if name else "sensor%d" % i] = round(val, 1)
        return out

    return read


def read_max():
    """Найгарячіший сенсор SoC, °C. None якщо прочитати неможливо (не Apple Silicon,
    нема сенсорів, нема pyobjc) — виклик має трактувати None як «гейт вимкнено»."""
    global _read_impl
    if _read_impl is None:
        try:
            _read_impl = _build_reader()
        except Exception:
            _read_impl = False          # позначка «недоступно», більше не пробуємо
    if not _read_impl:
        return None
    try:
        t = _read_impl()
        return max(t.values()) if t else None
    except Exception:
        return None


# ── налаштування гейта: env (ручний оверрайд) → config.json Кобзаря (тумблер UI) → дефолт ──
# Так термо-гейт ПІДПОРЯДКОВАНИЙ Кобзарю: увімк/вимк і пороги задає UI (config.json).
# Без Кобзаря/файлу діють env і дефолти. Читаємо config щоразу → зміни в UI без перезапуску.
_CFG_PATH = os.path.expanduser("~/.local/kobzarai/config.json")

# Дефолти консервативні для ПАСИВНОГО Air. MacBook Pro зі своїм кулером — юзер або
# підіймає пороги, або вимикає гейт зовсім (thermal_on:false у config.json / UI Кобзаря).
DEF_COOL_AT, DEF_RESUME_AT, DEF_MAX_COOL = 92.0, 84.0, 240.0
COOL_AT, RESUME_AT, MAX_COOL = DEF_COOL_AT, DEF_RESUME_AT, DEF_MAX_COOL  # сумісність зі старим кодом


def _cfg():
    try:
        with open(_CFG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _pick(cfg, cfg_key, env_key, default):
    """env (ручний оверрайд) → config.json (тумблер UI) → дефолт."""
    v = os.environ.get(env_key, "")
    if v:
        try:
            return float(v)
        except ValueError:
            pass
    c = cfg.get(cfg_key)
    if c is not None:
        try:
            return float(c)
        except (TypeError, ValueError):
            pass
    return default


def enabled(cfg=None):
    """Гейт увімкнено? config.json thermal_on (тумблер UI Кобзаря) → env
    KOBZAR_THERMAL_ON → дефолт True. Машина зі своїм активним охолодженням → юзер вимикає."""
    cfg = _cfg() if cfg is None else cfg
    c = cfg.get("thermal_on")
    if c is not None:
        return bool(c)
    return os.environ.get("KOBZAR_THERMAL_ON", "").lower() not in ("0", "false", "no", "off")


# Стан паузи — файл, який читає трей Кобзаря (іконка ❄️ + рядок у меню). Файл, а не пуш:
# пауза може йти в БУДЬ-ЯКОМУ процесі (реіндекс Кобзаря, бібліотекар Січі в сесіях Claude).
_STATE = os.path.expanduser("~/.local/kobzarai/logs/thermal_pause.json")


def _state_write(t, ra):
    try:
        os.makedirs(os.path.dirname(_STATE), exist_ok=True)
        who = "бібліотекар" if "librarian" in os.path.basename(__import__("sys").argv[0] or "") else "ембед"
        tmp = _STATE + ".%d" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"t": t, "ra": ra, "ts": time.time(), "pid": os.getpid(), "who": who}, f)
        os.replace(tmp, _STATE)
    except Exception:
        pass


def _state_clear():
    try:
        with open(_STATE, encoding="utf-8") as f:
            if json.load(f).get("pid") != os.getpid():
                return                              # чужу паузу не чіпаємо
        os.remove(_STATE)
    except Exception:
        pass


def pause_state(max_age=12.0):
    """Для трея: dict стану, якщо зараз хтось на термо-паузі (свіжий запис), інакше None.
    Застарілий файл (процес упав посеред паузи) ігнорується за віком."""
    try:
        with open(_STATE, encoding="utf-8") as f:
            d = json.load(f)
        return d if time.time() - float(d.get("ts", 0)) < max_age else None
    except Exception:
        return None


def cooldown(cool_at=None, resume_at=None, max_cool=None, interval=3.0, on_wait=None):
    """Якщо SoC гарячий (≥cool_at) — БЛОКУЄ поточний потік (спить), поки не охолоне до
    resume_at або поки не мине max_cool. НІКОЛИ не вбиває процес — лише пауза.

    on_wait(temp, waited_s) викликається періодично під час паузи (для UI-статусу).
    Повертає (сек_у_паузі, пікова_температура). Якщо гейт не спрацював або датчик
    недоступний — (0.0, temp|0.0), і викликач просто працює далі.
    """
    cfg = _cfg()
    if not enabled(cfg):                        # гейт вимкнено в UI → без пауз, працюємо далі
        return 0.0, (read_max() or 0.0)
    ca = cool_at if cool_at is not None else _pick(cfg, "thermal_cool_at", "KOBZAR_COOL_AT", DEF_COOL_AT)
    ra = resume_at if resume_at is not None else _pick(cfg, "thermal_resume_at", "KOBZAR_RESUME_AT", DEF_RESUME_AT)
    mc = max_cool if max_cool is not None else _pick(cfg, "thermal_max_cool", "KOBZAR_MAX_COOL", DEF_MAX_COOL)
    t = read_max()
    if t is None or t < ca:
        return 0.0, (t or 0.0)
    start = time.time()
    peak = t
    while time.time() - start < mc:
        _state_write(t, ra)
        if on_wait:
            try:
                on_wait(t, time.time() - start)
            except Exception:
                pass
        time.sleep(interval)
        t = read_max()
        if t is None:                 # датчик зник посеред паузи — не блокуємо назавжди
            break
        peak = max(peak, t)
        if t <= ra:
            break
    _state_clear()
    return time.time() - start, peak


if __name__ == "__main__":
    mt = read_max()
    if mt is None:
        print("температуру прочитати не вдалось (не Apple Silicon / нема сенсорів)")
    else:
        cfg = _cfg()
        ca = _pick(cfg, "thermal_cool_at", "KOBZAR_COOL_AT", DEF_COOL_AT)
        ra = _pick(cfg, "thermal_resume_at", "KOBZAR_RESUME_AT", DEF_RESUME_AT)
        print("найгарячіший сенсор SoC: %.1f°C  гейт=%s  (пауза≥%.0f → продовження≤%.0f)"
              % (mt, "увімк" if enabled(cfg) else "ВИМК", ca, ra))
