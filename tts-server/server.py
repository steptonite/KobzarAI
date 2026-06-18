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
        "/": " слеш ", "@": " ет ", "#": " решітка ", "_": " ", "~": " тильда "}


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


def verbalize_ua(t):
    for s, r in _SYM.items():
        t = t.replace(s, r)
    # 2-5 великих кириличних літер поспіль -> читати по літерах (ДПА -> де-пе-а)
    t = re.sub(r"\b[А-ЯҐЄІЇ]{2,5}\b", _spell_abbr, t)
    # цілі числа -> слова (роки/кількості); десяткові читаються частинами
    t = re.sub(r"\d+", _num_word, t)
    return t


# --- StyleTTS2 синтез (укр) ---
def split_to_parts(text, group=True):
    text = re.sub(r"(\w+[^.,!:?\-])\n", r"\1. ", text)
    text = text.replace("\n", " ")
    split_symbols = ".?!:"
    parts = [""]
    index = 0
    last = len(text) - 1
    for i, s in enumerate(text):
        parts[index] += s
        if s in split_symbols and i < last and text[i + 1] == " ":
            if group and len(parts[index]) <= 20:
                continue
            index += 1
            parts.append("")
    return parts


def _ua_array(text, kind, style, speed):
    """Синтез укр -> float32 numpy @24k, або None."""
    model = get_model(kind)
    result = []
    for t in split_to_parts(text):
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
        t = stressify(t)
        ps = ipa(t)
        if ps:
            tokens = model.tokenizer.encode(ps)
            wav = model(tokens, speed=speed, s_prev=style)
            result.append(wav)
    if not result:
        return None
    return torch.concatenate(result).cpu().numpy().astype("float32")


def synth_ua(text, kind, style, speed):
    audio = _ua_array(text, kind, style, speed)
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
        if len(w) >= 2 and w.isupper():       # TTS, API, RAM -> по літерах
            return _spell_en_acronym(w)
        return _en_phonetic(w)
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
    try:
        speed = float(data.get("speed", 1.0))
    except (TypeError, ValueError):
        speed = 1.0
    if not text:
        return jsonify({"error": "empty input"}), 400
    ua_speed = max(0.7, min(1.3, speed))
    # Один голос StyleTTS2: латиниця -> якісна укр-фонетика (g2p), кирилиця -> вербалізація.
    text = latin_to_ua(text)
    try:
        with _lock:
            kind, style = resolve_voice(data.get("voice"))
            out = synth_ua(text, kind, style, ua_speed)
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


if __name__ == "__main__":
    print(f"[styletts] {len(MULTI_NAMES)} multispeaker voices + filatov. Lazy model load.", flush=True)
    app.run(host="127.0.0.1", port=5050, threaded=True)
