#!/usr/bin/env python3
"""OpenAI-сумісний TTS-сервер для Cherry Studio.
- Українська -> StyleTTS2 (patriotyk): голос filatov (single) + 31 голос multispeaker, перемикання через `voice`.
- Англійська/латиниця -> edge-tts (нейроголос Microsoft), бо StyleTTS2 англійську не тягне.
- Мова визначається автоматично за текстом. Один endpoint: POST /v1/audio/speech.
Памʼять береже: тримає в RAM лише ОДНУ StyleTTS2-модель (single АБО multi), свопить при зміні.
"""
import asyncio
import gc
import glob
import io
import os
import re
import subprocess
import tempfile
import threading
from unicodedata import normalize

from flask import Flask, request, Response, jsonify
import numpy as np
import torch
import soundfile as sf
import edge_tts
from num2words import num2words
from ipa_uk import ipa
from styletts2_inference.models import StyleTTS2
from ukrainian_word_stress import Stressifier, StressSymbol

HERE = os.path.dirname(os.path.abspath(__file__))
DEVICE = os.getenv("TTS_DEVICE", "cpu")
SAMPLE_RATE = 24000
DEFAULT_UA_VOICE = "filatov"
EN_VOICE = os.getenv("EN_VOICE", "en-US-AriaNeural")

SINGLE_HF = "patriotyk/styletts2_ukrainian_single"
MULTI_HF = "patriotyk/styletts2_ukrainian_multispeaker"

stressify = Stressifier()
_lock = threading.Lock()

# --- стилі голосів ---
single_style = torch.load(os.path.join(HERE, "filatov.pt"), map_location=DEVICE)
multi_styles = {}
for p in glob.glob(os.path.join(HERE, "voices", "*.pt")):
    name = os.path.splitext(os.path.basename(p))[0]
    multi_styles[name] = torch.load(p, map_location=DEVICE)
MULTI_NAMES = sorted(multi_styles.keys())

# --- менеджер моделей: лише одна в RAM ---
_loaded = {"kind": None, "model": None}


def get_model(kind):
    """kind: 'single' | 'multi'. Тримає в памʼяті лише одну модель."""
    if _loaded["kind"] == kind and _loaded["model"] is not None:
        return _loaded["model"]
    if _loaded["model"] is not None:
        _loaded["model"] = None
        gc.collect()
    hf = SINGLE_HF if kind == "single" else MULTI_HF
    print(f"[styletts] loading {kind} model...", flush=True)
    m = StyleTTS2(hf_path=hf, device=DEVICE)
    _loaded["kind"] = kind
    _loaded["model"] = m
    print(f"[styletts] {kind} ready.", flush=True)
    return m


def resolve_voice(v):
    """Повертає (kind, style, style_for_multi_name). filatov -> single, інакше шукає у multispeaker."""
    if not v:
        return "single", single_style
    v = v.strip()
    low = v.lower()
    if low in ("filatov", "alloy", "echo", "onyx", "default"):
        return "single", single_style
    # точний збіг
    if v in multi_styles:
        return "multi", multi_styles[v]
    # збіг без регістру / частковий (за прізвищем чи імʼям)
    for name in MULTI_NAMES:
        if name.lower() == low:
            return "multi", multi_styles[name]
    for name in MULTI_NAMES:
        if low in name.lower():
            return "multi", multi_styles[name]
    return "single", single_style  # фолбек


# --- мовний роутинг ---
def is_english(text):
    cyr = len(re.findall(r"[Ѐ-ӿ]", text))
    lat = len(re.findall(r"[A-Za-z]", text))
    return lat > cyr  # переважно латиниця -> англійська


# --- вербалізація: числа -> слова, абревіатури -> по літерах, символи ---
_UA_LETTER = {
    "а": "а", "б": "бе", "в": "ве", "г": "ге", "ґ": "ґе", "д": "де", "е": "е",
    "є": "є", "ж": "же", "з": "зе", "и": "и", "і": "і", "ї": "ї", "й": "йот",
    "к": "ка", "л": "ел", "м": "ем", "н": "ен", "о": "о", "п": "пе", "р": "ер",
    "с": "ес", "т": "те", "у": "у", "ф": "еф", "х": "ха", "ц": "це", "ч": "че",
    "ш": "ша", "щ": "ща", "ю": "ю", "я": "я",
}
# абревіатури, що читаються як слово (НЕ по літерах)
_READ_AS_WORD = {"НАТО", "ЮНЕСКО", "ЗНО", "ВНЗ", "СНІД", "ДОТ", "ДзвО"}
_SYM = {"%": " відсотків", "№": " номер ", "§": " параграф ", "&": " і ",
        "₴": " гривень", "$": " доларів", "€": " євро", "°": " градусів",
        "/": " слеш ", "@": " ет ", "_": " ", "~": " ",
        "=": " дорівнює ", "+": " плюс ", "×": " помножити ", "÷": " поділити ",
        "±": " плюс-мінус ", "…": ".", "•": ". ", "→": " ", "←": " ", "—": ", "}


# модель пише markdown — приберемо розмітку, лишимо чистий текст для озвучки
def strip_markdown(t):
    t = re.sub(r"```.*?```", " ", t, flags=re.S)          # блоки коду
    t = re.sub(r"`([^`]*)`", r"\1", t)                    # інлайн-код
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)        # [текст](url) -> текст
    t = re.sub(r"[*]{1,3}([^*]+)[*]{1,3}", r"\1", t)      # **жирний**/*курсив*
    t = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", t)           # # заголовки
    t = re.sub(r"(?m)^\s*[-*+]\s+", "", t)                # маркери списку
    t = re.sub(r"(?m)^\s*>\s?", "", t)                    # цитати
    t = t.replace("*", "").replace("`", "")               # залишкові зірочки/беки
    return t


def _spell_abbr(m):
    w = m.group()
    if w in _READ_AS_WORD:
        return w.capitalize()
    return "-".join(_UA_LETTER.get(c.lower(), c) for c in w)


def _num_word(m):
    try:
        return num2words(int(m.group()), lang="uk")
    except Exception:
        return m.group()


def _num_decimal(m):
    # 2.3 / 2,3 -> "два кома три" (крапка/кома в числі вимовляється)
    a, b = re.split(r"[.,]", m.group(), maxsplit=1)
    try:
        return num2words(int(a), lang="uk") + " кома " + num2words(int(b), lang="uk")
    except Exception:
        return m.group()


def verbalize_ua(t):
    for s, r in _SYM.items():
        t = t.replace(s, r)
    # 2-5 великих кириличних літер поспіль -> читати по літерах (ДПА -> де-пе-а)
    t = re.sub(r"\b[А-ЯҐЄІЇ]{2,5}\b", _spell_abbr, t)
    # десяткові ПЕРШІ (інакше \d+ зʼїсть крапку): 2.3 -> два кома три
    t = re.sub(r"\d+[.,]\d+", _num_decimal, t)
    # цілі числа -> слова
    t = re.sub(r"\d+", _num_word, t)
    return t


# --- StyleTTS2 синтез (укр) ---
# --- клітики: службові слова, які в українській НЕ несуть наголосу ---
# Stressifier зі словника б'є акут у КОЖНЕ слово (19 з 21 на типовій фразі) →
# рівномірний удар по всьому підряд, немає слабких складів, на тлі яких сильні
# звучали б сильними. Це чується як монотонність/карбування. Знімаємо акут
# з односкладових службових слів; багатоскладові («тільки», «навіть», «однак»)
# мають власний наголос і НЕ чіпаються. Двозначні («та», «то») теж не чіпаємо —
# вони бувають займенниками. Ручний `+` завжди перемагає цей фільтр.
_ACUTE = StressSymbol.CombiningAcuteAccent
CLITICS = {
    # прийменники
    "в", "у", "з", "зі", "із", "на", "до", "від", "од", "за", "під", "над",
    "при", "про", "для", "без", "крізь", "повз", "по", "о", "об", "між",
    # сполучники
    "і", "й", "а", "чи", "що", "як", "бо", "хоч", "ніж",
    "щоб", "аби", "але", "коли", "якщо", "хоча", "проте", "адже",
    # частки
    "не", "ні", "б", "би", "ж", "же", "аж", "хай", "нехай",
    # 🔴 «це» — найризикованіше в списку: у потоці («це не так», «це вже»)
    # воно слабке, але як підмет («Це — головне») наголос потрібен.
    # Якщо десь з'їсть акцент — став `+` вручну, він сильніший за фільтр.
    "це",
}


def _manual_stressed(text):
    """Слова, у яких акут стоїть ВРУЧНУ (з `+`) — їх фільтр не чіпає."""
    return {w.replace(_ACUTE, "").lower() for w in text.split() if _ACUTE in w}


def _unstress_clitics(text, manual=frozenset()):
    """Прибрати акут зі службових слів, крім наголошених вручну."""
    out = []
    for w in text.split(" "):
        bare = w.replace(_ACUTE, "")
        key = bare.strip(".,!?:;»«\"()—-").lower()
        if key in CLITICS and key not in manual:
            w = bare
        out.append(w)
    return " ".join(out)


def _split_commas(text, min_chars=14):
    """Розрізати РЕЧЕННЯ по комах, зберігаючи кому в кінці шматка.

    Кома лишається на місці навмисно: шматок, що закінчується комою, модель
    веде з незавершеною (неспадною) інтонацією — саме тому не можна різати
    так, як ріжуться речення (там у кінець дописується крапка = спад).
    Куски коротші за min_chars зліплюються з сусідом: на огризку в 3-4 склади
    синтез дає власний холодний старт і чути «сходинку».
    Вмикається лише коли comma_pause > 0 ⇒ дефолт (Кобзар/Cherry) не зачеплений."""
    raw = re.split(r"(?<=,)\s+", text)
    out = []
    for piece in raw:
        if out and len(out[-1]) < min_chars:
            out[-1] += " " + piece
        else:
            out.append(piece)
    if len(out) > 1 and len(out[-1]) < min_chars:
        # 🔴 НЕ `out[-2] += " " + out.pop()`: індекс цілі рахується ДО обчислення
        # правої частини, а pop() коротшає список ⇒ на двох шматках запис іде в
        # неіснуючий -2 (IndexError). Спершу знімаємо хвіст, потім доклеюємо.
        tail = out.pop()
        out[-1] += " " + tail
    return out


def _normalize(wav, target_dbfs=-16.0, ceiling_dbfs=-1.0):
    """Підняти гучність до цільового RMS і придавити піки м'яким лімітером.

    ЧОМУ RMS, а не пік: пікова нормалізація нічого не дає — один клац на -0.1 dB
    і трек лишається тихим. Соцмережі слухають середню гучність (≈ -14 LUFS),
    тому тягнемо RMS, а піки згинаємо tanh'ом. Просте масштабування «до піку»
    після підйому вбило б увесь виграш."""
    rms = float(np.sqrt(np.mean(np.square(wav))))
    if rms <= 1e-6:
        return wav
    wav = wav * (10.0 ** ((target_dbfs - 20.0 * np.log10(rms)) / 20.0))
    ceil = 10.0 ** (ceiling_dbfs / 20.0)
    knee = ceil * 0.7
    over = np.abs(wav) > knee
    if over.any():
        mag = np.abs(wav[over])
        wav[over] = np.sign(wav[over]) * (knee + (ceil - knee) * np.tanh((mag - knee) / (ceil - knee)))
    return wav.astype("float32")


def split_to_parts(text, group_chars=20):
    """group_chars — мінімальна довжина накопиченого шматка, перш ніж дозволити
    розріз на межі речення. Дефолт 20 = поточна поведінка (Cherry без змін).
    KobzarAI шле більше (~150-220) → довші спани синтезу = менше стиків = менше
    рваності й природніший інтонаційний контур усередині спана."""
    text = re.sub(r"(\w+[^.,!:?\-])\n", r"\1. ", text)
    text = text.replace("\n", " ")
    split_symbols = ".?!:"
    parts = [""]
    index = 0
    last = len(text) - 1
    for i, s in enumerate(text):
        parts[index] += s
        if s in split_symbols and i < last and text[i + 1] == " ":
            if group_chars and len(parts[index]) <= group_chars:
                continue
            index += 1
            parts.append("")
    return parts


def _fade_edges(wav, ms=12):
    """Лінійний fade-in/out по краях сегмента → прибирає КЛІК на стиках
    (тверда склейка хвиль давала стрибок амплітуди = «скрип/кріп»)."""
    n = int(SAMPLE_RATE * ms / 1000.0)
    if wav.size < 2 * n or n < 1:
        return wav
    ramp = np.linspace(0.0, 1.0, n, dtype="float32")
    wav = wav.copy()
    wav[:n] *= ramp
    wav[-n:] *= ramp[::-1]
    return wav


def _trim_quiet(wav, thr=0.012, pad_ms=8):
    """Зрізати тихий «холодний старт» istftnet на краях сегмента —
    саме там сидить низьке «джуу»/«блюмк». Лишаємо невеликий запас."""
    idx = np.where(np.abs(wav) > thr)[0]
    if idx.size == 0:
        return wav
    pad = int(SAMPLE_RATE * pad_ms / 1000.0)
    a = max(0, idx[0] - pad)
    b = min(wav.size, idx[-1] + pad)
    return wav[a:b]


_HP_SOS = None


def _highpass(wav, cut=65.0):
    """Прибрати DC + суб-бас гул (низьке «джуу») — не чіпає голос."""
    global _HP_SOS
    if _HP_SOS is None:
        from scipy.signal import butter
        _HP_SOS = butter(2, cut / (SAMPLE_RATE / 2.0), btype="high", output="sos")
    from scipy.signal import sosfilt
    return sosfilt(_HP_SOS, wav).astype("float32")


def _ua_array(text, kind, style, speed, pause=0.15, group_chars=20,
              comma_pause=0.0, norm_db=None):
    """Синтез укр -> float32 numpy @24k, або None.
    pause — секунди тиші МІЖ реченнями (керована «дихалка», плавна склейка).
    group_chars — таргет довжини спана (див. split_to_parts); дефолт 20 = як було.
    comma_pause — секунди тиші на КОМІ всередині речення; 0 = вимкнено (дефолт).
    speed — число АБО список чисел по реченнях (останнє значення тягнеться далі):
        дає сповільнення там, де воно логічне (фінальна думка), без окремих запитів.
    norm_db — цільовий RMS у dBFS (напр. -16); None = не чіпати гучність."""
    model = get_model(kind)
    sil = np.zeros(int(max(0.0, pause) * SAMPLE_RATE), dtype="float32")
    csil = np.zeros(int(max(0.0, comma_pause) * SAMPLE_RATE), dtype="float32")
    speeds = speed if isinstance(speed, (list, tuple)) else [speed]
    result = []
    for part_i, t in enumerate(split_to_parts(text, group_chars)):
        sp_speed = float(speeds[min(part_i, len(speeds) - 1)])
        t = t.strip().replace('"', "")
        if not t:
            continue
        t = t.replace("+", StressSymbol.CombiningAcuteAccent)
        t = normalize("NFKC", t)
        t = re.sub(r"[᠆‐‑‒–—―⁻₋−⸺⸻]", "-", t)
        if t[-1] not in ".?!:-":
            t += "."
        t = re.sub(r" - ", ": ", t)
        t = verbalize_ua(t)
        manual = _manual_stressed(t)            # слова, наголошені вручну через `+`
        t = stressify(t)
        t = _unstress_clitics(t, manual)        # зняти акут зі службових слів
        spans = _split_commas(t) if csil.size else [t]
        first_in_part = True
        for span in spans:
            ps = ipa(span)
            if not ps:
                continue
            tokens = model.tokenizer.encode(ps)
            wav = model(tokens, speed=sp_speed, s_prev=style).cpu().numpy().astype("float32")
            wav = _trim_quiet(wav)              # зрізати холодний старт vocoder'а
            wav = _fade_edges(wav)              # згладити краї → без кліку на стику
            if result:
                # МІЖ реченнями — pause, МІЖ комами всередині речення — comma_pause
                gap = sil if first_in_part else csil
                if gap.size:
                    result.append(gap)
            result.append(wav)
            first_in_part = False
    if not result:
        return None
    out = np.concatenate(result).astype("float32")
    out = _highpass(out)                        # DC + суб-бас гул геть
    return _normalize(out, norm_db) if norm_db is not None else out


def synth_ua(text, kind, style, speed, pause=0.15, group_chars=20,
             comma_pause=0.0, norm_db=None):
    audio = _ua_array(text, kind, style, speed, pause, group_chars,
                      comma_pause, norm_db)
    if audio is None:
        return None
    buf = io.BytesIO()
    sf.write(buf, audio, SAMPLE_RATE, format="WAV", subtype="PCM_16")
    return ("audio/wav", buf.getvalue())


# --- edge-tts синтез (англ) ---
def synth_en(text, speed):
    rate = f"{int(round((speed - 1) * 100)):+d}%"

    async def run():
        com = edge_tts.Communicate(text, EN_VOICE, rate=rate)
        b = bytearray()
        async for ch in com.stream():
            if ch["type"] == "audio":
                b.extend(ch["data"])
        return bytes(b)

    return ("audio/mpeg", asyncio.run(run()))


def _en_array(text, speed):
    """edge-tts -> float32 numpy @24k (декод mp3 через системний afconvert)."""
    _, mp3 = synth_en(text, speed)
    src = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    src.write(mp3); src.close()
    dst = src.name[:-4] + ".wav"
    try:
        subprocess.run(["/usr/bin/afconvert", "-f", "WAVE", "-d",
                        f"LEI16@{SAMPLE_RATE}", src.name, dst],
                       check=True, capture_output=True)
        audio, _sr = sf.read(dst, dtype="float32")
    finally:
        for p in (src.name, dst):
            try: os.remove(p)
            except OSError: pass
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return audio


# --- EN -> якісна укр-фонетика через g2p_en (ARPABET) + буквені назви для акронімів ---
# мапа фонем ARPABET -> кирилиця (англ. вимова укр. літерами)
_ARPA_UA = {
    "AA": "а", "AE": "е", "AH": "а", "AO": "о", "AW": "ау", "AY": "ай", "EH": "е",
    "ER": "ер", "EY": "ей", "IH": "і", "IY": "і", "OW": "оу", "OY": "ой", "UH": "у",
    "UW": "у", "B": "б", "CH": "ч", "D": "д", "DH": "д", "F": "ф", "G": "ґ",
    "HH": "г", "JH": "дж", "K": "к", "L": "л", "M": "м", "N": "н", "NG": "нґ",
    "P": "п", "R": "р", "S": "с", "SH": "ш", "T": "т", "TH": "т", "V": "в",
    "W": "в", "Y": "й", "Z": "з", "ZH": "ж",
}
# назви англ. літер укр. вимовою (для акронімів: TTS -> ті-ті-ес)
_EN_LETTER = {
    "a": "ей", "b": "бі", "c": "сі", "d": "ді", "e": "і", "f": "еф", "g": "джі",
    "h": "ейч", "i": "ай", "j": "джей", "k": "кей", "l": "ел", "m": "ем", "n": "ен",
    "o": "оу", "p": "пі", "q": "кю", "r": "ар", "s": "ес", "t": "ті", "u": "ю",
    "v": "ві", "w": "дабл-ю", "x": "екс", "y": "вай", "z": "зет",
}
_g2p = None


def _g2p_lazy():
    global _g2p
    if _g2p is None:
        from g2p_en import G2p
        _g2p = G2p()
    return _g2p


def _spell_en_acronym(w):
    return "-".join(_EN_LETTER.get(c.lower(), c) for c in w)


def _en_word_like(w):
    """ALL-CAPS: читати як слово (NVIDIA, LEGO, NASA) чи по літерах (TTS, API)?
    Чиста евристика вимовності — БЕЗ списків слів (їх безмежно).
    Слово, якщо: довжина>=4, є голосні (>=25%), нема 4+ приголосних поспіль."""
    lw = w.lower()
    if len(w) < 4:                              # US, API, GPU, USB -> по літерах
        return False
    vowels = sum(c in "aeiouy" for c in lw)
    if vowels == 0 or vowels / len(lw) < 0.25:  # HTML, HTTP, NVMe -> по літерах
        return False
    if re.search(r"[^aeiouy]{4,}", lw):         # 4+ приголосних поспіль = не вимовне
        return False
    return True


def _en_phonetic(text):
    """Англ. слова -> укр. фонетика. Суцільні великі (акроніми) -> по літерах."""
    g = _g2p_lazy()
    out = []
    for p in g(text):
        if p == " ":
            out.append(" ")
        elif p and p[0].isalpha():
            ph = "".join(c for c in p if c.isalpha())  # зняти цифру наголосу
            out.append(_ARPA_UA.get(ph, ""))
        else:
            out.append(p)  # пунктуація
    return "".join(out)


def latin_to_ua(text):
    def repl(m):
        w = m.group()
        if len(w) >= 2 and w.isupper() and not _en_word_like(w):
            return _spell_en_acronym(w)       # TTS, API, USB -> по літерах
        return _en_phonetic(w)                # слова + вимовні скорочення (NVIDIA) -> як слово
    return re.sub(r"[A-Za-z]+", repl, text)


# --- сегментація мішаного тексту по письму (кирилиця/латиниця) ---
def script_runs(text):
    """Розбиває на суцільні відрізки 'ua'(є кирилиця) / 'en'(лише латиниця).
    Цифри, пунктуація, пробіли липнуть до поточного відрізка."""
    runs = []
    cur_kind, cur = None, ""
    for tok in re.findall(r"\s+|\S+", text):
        if tok.isspace():
            cur += tok
            continue
        if re.search(r"[Ѐ-ӿ]", tok):
            k = "ua"
        elif re.search(r"[A-Za-z]", tok):
            k = "en"
        else:
            k = cur_kind or "ua"      # нейтральний токен -> поточна мова
        if cur_kind is None:
            cur_kind = k
        if k != cur_kind:
            runs.append((cur_kind, cur)); cur, cur_kind = tok, k
        else:
            cur += tok
    if cur.strip():
        runs.append((cur_kind or "ua", cur))
    return runs


def synth_mixed(text, kind, style, ua_speed, en_speed):
    """Мішаний UA+EN: кожен відрізок своїм рушієм, склейка в один WAV."""
    parts = []
    for k, seg in script_runs(text):
        seg = seg.strip()
        if not seg:
            continue
        if k == "en":
            parts.append(_en_array(seg, en_speed))
        else:
            a = _ua_array(seg, kind, style, ua_speed)
            if a is not None:
                parts.append(a)
    if not parts:
        return None
    audio = np.concatenate(parts).astype("float32")
    buf = io.BytesIO()
    sf.write(buf, audio, SAMPLE_RATE, format="WAV", subtype="PCM_16")
    return ("audio/wav", buf.getvalue())


app = Flask(__name__)


@app.route("/v1/audio/speech", methods=["POST"])
def speech():
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("input") or "").strip()
    raw_speed = data.get("speed", 1.0)
    try:
        # список = різна швидкість по реченнях (фінал повільніше); число = як було
        if isinstance(raw_speed, (list, tuple)) and raw_speed:
            speed = [max(0.7, min(1.3, float(v))) for v in raw_speed]
        else:
            speed = float(raw_speed)
    except (TypeError, ValueError):
        speed = 1.0
    try:
        pause = float(data.get("pause", 0.15))
    except (TypeError, ValueError):
        pause = 0.15
    try:
        group_chars = int(data.get("group_chars", 20))
    except (TypeError, ValueError):
        group_chars = 20
    try:
        comma_pause = float(data.get("comma_pause", 0.0))
    except (TypeError, ValueError):
        comma_pause = 0.0
    norm_db = data.get("norm_db")
    try:
        norm_db = None if norm_db is None else max(-30.0, min(-6.0, float(norm_db)))
    except (TypeError, ValueError):
        norm_db = None
    if not text:
        return jsonify({"error": "empty input"}), 400
    ua_speed = speed if isinstance(speed, list) else max(0.7, min(1.3, speed))
    pause = max(0.0, min(0.6, pause))
    comma_pause = max(0.0, min(0.4, comma_pause))
    group_chars = max(10, min(400, group_chars))   # 20=як було (Cherry); KobzarAI шле більше
    # Прибрати markdown -> латиниця в укр-фонетику (g2p) -> вербалізація кирилиці.
    text = strip_markdown(text)
    text = latin_to_ua(text)
    try:
        with _lock:
            kind, style = resolve_voice(data.get("voice"))
            out = synth_ua(text, kind, style, ua_speed, pause, group_chars,
                           comma_pause, norm_db)
            if out is None:
                return jsonify({"error": "nothing to synthesize"}), 400
            mime, audio = out
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return Response(audio, mimetype=mime)


@app.route("/v1/voices", methods=["GET"])
@app.route("/voices", methods=["GET"])
def voices():
    return jsonify({
        "default": DEFAULT_UA_VOICE,
        "single": ["filatov"],
        "multispeaker": MULTI_NAMES,
        "english_fallback": EN_VOICE,
    })


@app.route("/v1/models", methods=["GET"])
def models():
    return jsonify({"object": "list", "data": [{"id": "tts-1", "object": "model"}]})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "engine": "styletts2+edge", "loaded": _loaded["kind"],
                    "voices_multi": len(MULTI_NAMES)})


@app.route("/unload", methods=["POST"])
@app.route("/v1/unload", methods=["POST"])
def unload():
    """Звільнити модель з RAM, лишивши Flask живим (idle-вивантаження).
    Додано для KobzarAI: idle тепер не вбиває сервер, а лише скидає модель —
    наступний синтез її перевантажить (теплий старт ~секунди, не cold ~20с)."""
    was = _loaded["kind"]
    _loaded["kind"] = None
    _loaded["model"] = None
    gc.collect()
    try:
        if DEVICE == "mps":
            torch.mps.empty_cache()
        elif DEVICE == "cuda":
            torch.cuda.empty_cache()
    except Exception:
        pass
    print(f"[styletts] model unloaded (was {was}); server stays up.", flush=True)
    return jsonify({"status": "unloaded", "was": was})


if __name__ == "__main__":
    print(f"[styletts] {len(MULTI_NAMES)} multispeaker voices + filatov. Lazy model load.", flush=True)
    app.run(host="127.0.0.1", port=5050, threaded=True)
