#!/bin/bash
# KobzarAI — діагностика встановленої копії.
#
#   ./doctor.sh          перевірити і сказати, що не так
#   ./doctor.sh --fix    полагодити те, що лагодиться безпечно
#
# Навіщо (22.08.2026, після першої чужої установки):
# інсталятор чесно ставив Ollama і клав моделі в ~/.ollama/models, а панель
# шукала їх на диску автора. Кнопка «Запустити Ollama» мовчки не робила НІЧОГО:
# єдиний натяк лежав рядком у меню, яке закривається в мить кліку. Людина бачила
# застосунок, який просто не працює, і не мала жодного способу спитати «чому».
# Перевстановлення теж не рятувало: setup.sh нічого не звіряв — він ставив
# заново поверх, і те, що вже поламалось, лишалось поламаним.
#
# 🔴 Правило, заради якого це існує: інсталятор, що вміє ставити, і інсталятор,
#    що вміє ЛАГОДИТИ ВСТАНОВЛЕНЕ, — це різні програми. Друга тут.
set -uo pipefail

FIX=0
[ "${1:-}" = "--fix" ] && FIX=1
[ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ] && { sed -n '2,20p' "$0"; exit 0; }

REPO="$(cd "$(dirname "$0")" && pwd)"
PANEL_DIR="$HOME/.local/kobzarai"
TTS_DIR="$HOME/.local/styletts2-ua-server"
LAUNCHER="$HOME/.ollama/start-ollama.sh"
CFG="$PANEL_DIR/config.json"

PROBLEMS=0; FIXED=0
ok()    { printf '  ✅ %s\n' "$1"; }
warn()  { printf '  ⚠️  %s\n' "$1"; }
bad()   { printf '  🔴 %s\n' "$1"; PROBLEMS=$((PROBLEMS+1)); }
fixed() { printf '  🔧 полагоджено: %s\n' "$1"; FIXED=$((FIXED+1)); }
head_() { printf '\n\033[1m%s\033[0m\n' "$1"; }

echo "KobzarAI — перевірка встановленої копії"
echo "репо: $REPO"

# ── 1. Залізо й Python ────────────────────────────────────────────────
head_ "1. Основа"
[ "$(uname -m)" = "arm64" ] && ok "Apple Silicon" || bad "не Apple Silicon — панель не підтримується"

PANEL_PY="$PANEL_DIR/.venv/bin/python"
if [ -x "$PANEL_PY" ]; then
  ok "оточення панелі: $("$PANEL_PY" -V 2>&1)"
  # 🔴 Саме тут ламався меню-бар: venv на системному 3.9 збирав кривий pyobjc,
  #    апка стартувала й не малювала іконку — без жодної помилки.
  MISSING="$("$PANEL_PY" - <<'PY' 2>/dev/null
mods = ["rumps", "objc", "AppKit", "WebKit"]
print(" ".join(m for m in mods if not __import__("importlib.util", fromlist=["x"]).find_spec(m)))
PY
)"
  if [ -z "$MISSING" ]; then ok "меню-бар: rumps + pyobjc на місці"
  else bad "у панелі немає модулів: $MISSING → меню-бар не з'явиться"; fi
else
  bad "немає оточення панелі ($PANEL_PY) — панель не встановлена"
fi

# ── 2. Файли панелі й розбіжність із репо ─────────────────────────────
head_ "2. Що саме встановлено (а не що мало бути)"
DRIFT=0
for f in panel.py kb.py make_icon.py; do
  if [ ! -f "$PANEL_DIR/$f" ]; then
    bad "$f відсутній у $PANEL_DIR"; DRIFT=1
  elif ! cmp -s "$REPO/panel/$f" "$PANEL_DIR/$f"; then
    warn "$f у встановленій копії ВІДРІЗНЯЄТЬСЯ від репо (стара версія або ручна правка)"; DRIFT=1
  fi
done
[ "$DRIFT" = 0 ] && ok "файли панелі збігаються з репо"
if [ "$DRIFT" = 1 ] && [ "$FIX" = 1 ]; then
  cp "$REPO/panel/panel.py" "$REPO/panel/kb.py" "$REPO/panel/make_icon.py" "$PANEL_DIR/" 2>/dev/null \
    && rm -rf "$PANEL_DIR/ui" && cp -R "$REPO/panel/ui" "$PANEL_DIR/ui" \
    && fixed "файли панелі перезаписано з репо (перезапусти KobzarAI.app)"
fi

if [ -d "$REPO/.git" ]; then
  BEHIND="$(git -C "$REPO" rev-list --count HEAD..@{u} 2>/dev/null || echo "?")"
  AHEAD="$(git -C "$REPO" rev-list --count @{u}..HEAD 2>/dev/null || echo "?")"
  if [ "$BEHIND" = "?" ]; then warn "гілка не має upstream — оновлення git-ом не перевірити"
  elif [ "$BEHIND" != "0" ]; then warn "репо відстає від origin на $BEHIND комітів → git pull && ./setup.sh"
  else ok "оновлень з origin немає"; fi
  # 22.08.2026: «на рівні з origin» друкувалось і тоді, коли локально висіли
  # незапушені коміти — тобто перевірка мовчки ховала роботу, яка є лише на цій
  # машині. Перевірка, що не бачить половини стану, гірша за відсутню.
  if [ "$AHEAD" != "?" ] && [ "$AHEAD" != "0" ]; then
    warn "локально $AHEAD незапушених комітів — вони існують ТІЛЬКИ на цій машині"
  fi
fi

# ── 3. Ollama ─────────────────────────────────────────────────────────
head_ "3. Ollama"
OLLAMA_BIN=""
for c in "$(command -v ollama 2>/dev/null)" /opt/homebrew/bin/ollama /usr/local/bin/ollama \
         /Applications/Ollama.app/Contents/Resources/ollama; do
  [ -n "$c" ] && [ -x "$c" ] && { OLLAMA_BIN="$c"; break; }
done
if [ -n "$OLLAMA_BIN" ]; then ok "CLI знайдено: $OLLAMA_BIN"
else bad "Ollama не встановлена (ні в PATH, ні в homebrew, ні як Ollama.app) → brew install ollama"; fi

if curl -sf --max-time 3 http://localhost:11434/api/tags >/dev/null 2>&1; then
  ok "сервер відповідає на 11434"
  if curl -sf --max-time 3 http://localhost:11434/api/tags | grep -q "bge-m3"; then
    ok "модель пошуку bge-m3 на місці"
  else
    bad "bge-m3 не завантажена → семантичний пошук працювати не буде"
    if [ "$FIX" = 1 ] && [ -n "$OLLAMA_BIN" ]; then
      "$OLLAMA_BIN" pull bge-m3 </dev/null && fixed "bge-m3 завантажено"
    fi
  fi
else
  warn "сервер не запущений (це нормально, якщо ти його не піднімав)"
fi

# 🔴 Той самий корінь, що вбив панель у чужій машині: шлях до моделей.
MODELS="$HOME/.ollama/models"
if [ -f "$CFG" ]; then
  CHOSEN="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('models_dir') or '')" "$CFG" 2>/dev/null || echo "")"
  [ -n "$CHOSEN" ] && MODELS="$CHOSEN"
fi
if [ -d "$MODELS/manifests" ]; then ok "тека моделей читається: $MODELS"
elif [ -d "$HOME/.ollama/models/manifests" ]; then
  bad "панель налаштована на $MODELS, а моделі лежать у ~/.ollama/models"
  if [ "$FIX" = 1 ] && [ -f "$CFG" ]; then
    python3 - "$CFG" <<'PY' && fixed "config.json: models_dir прибрано, панель візьме стандартну теку"
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d.pop("models_dir", None)
json.dump(d, open(p, "w"), ensure_ascii=False, indent=2)
PY
  fi
else
  warn "теки моделей не видно ($MODELS) — Ollama ще нічого не качала"
fi

if [ -x "$LAUNCHER" ]; then ok "лаунчер на місці: $LAUNCHER"
else
  bad "немає лаунчера $LAUNCHER — кнопка «Запустити Ollama» не спрацює"
  if [ "$FIX" = 1 ]; then
    mkdir -p "$HOME/.ollama" && cp "$REPO/panel/start-ollama.sh" "$LAUNCHER" \
      && chmod +x "$LAUNCHER" && fixed "лаунчер відновлено"
  fi
fi

# ── 4. Озвучка ────────────────────────────────────────────────────────
head_ "4. Озвучка (TTS)"
if [ ! -d "$TTS_DIR" ]; then
  warn "TTS не встановлено (ставили з --no-tts). Додати: ./setup.sh"
else
  TTS_PY="$TTS_DIR/.venv/bin/python"
  [ -x "$TTS_PY" ] && ok "оточення TTS: $("$TTS_PY" -V 2>&1)" || bad "немає $TTS_PY"
  # 🔴 Верифікації ваг не було зовсім: snapshot_download міг обірватись, і людина
  #    отримувала «встановлено», а озвучка мовчала без жодного пояснення.
  [ -f "$TTS_DIR/filatov.pt" ] && ok "модель filatov.pt на місці" \
    || bad "немає $TTS_DIR/filatov.pt — озвучка не заговорить (завантаження обірвалось)"
  VOICES="$(ls "$TTS_DIR/voices/"*.pt 2>/dev/null | wc -l | tr -d ' ')"
  [ "${VOICES:-0}" -gt 0 ] && ok "голосів: $VOICES" || bad "тека voices/ порожня — нічим озвучувати"
  if [ -x "$TTS_PY" ]; then
    T_MISSING="$("$TTS_PY" - <<'PY' 2>/dev/null
import importlib.util as u
print(" ".join(m for m in ["torch", "nltk", "flask"] if not u.find_spec(m)))
PY
)"
    [ -z "$T_MISSING" ] && ok "залежності TTS на місці" || bad "у TTS немає: $T_MISSING"
  fi
  if curl -sf --max-time 3 http://localhost:5050/ >/dev/null 2>&1; then ok "TTS-сервер відповідає на 5050"
  else warn "TTS-сервер не запущений (нормально, якщо не піднімав)"; fi
fi

# ── 5. Чужі шляхи й персональні дані ──────────────────────────────────
head_ "5. Чи не приїхало чуже"
# 🔴 Пряма вимога: збірка не має відрізнятись від GitHub і не має тягнути
#    персональні дані автора. Перевіряємо ФАКТ, а не наміри.
# 🔴 Коментарі НЕ рахуються. Перший захід підсвічував власні пояснювальні рядки
#    («дефолтом тут стояв /Volumes/ExternalSSD») і кричав про діру, якої вже нема.
#    Перевірка, що бреше, дорівнює відсутній перевірці — її перестають читати.
LEAKS="$(python3 - "$REPO" <<'PY' 2>/dev/null
import re, sys
from pathlib import Path
root = Path(sys.argv[1])
bad = re.compile(r"/Volumes/|/Users/[a-z]+")
hits = []
for sub in ("panel", "tts-server"):
    for f in (root / sub).rglob("*"):
        if f.suffix not in {".py", ".sh", ".html", ".json"} or not f.is_file():
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith(("#", "//", "<!--", "*")):
                continue
            if bad.search(line):
                hits.append(f"{f.relative_to(root)}:{n}: {stripped[:70]}")
print("\n".join(hits))
PY
)"
if [ -z "$LEAKS" ]; then ok "у коді немає ні шляхів чужих дисків, ні домашніх тек"
else
  bad "шляхи конкретної машини у коді:"
  echo "$LEAKS" | sed 's/^/       /'
fi

# ── 6. Застосунок ─────────────────────────────────────────────────────
head_ "6. Застосунок"
APP=""
for a in "$HOME/Applications/KobzarAI.app" "/Applications/KobzarAI.app"; do
  [ -d "$a" ] && { APP="$a"; break; }
done
[ -n "$APP" ] && ok "KobzarAI.app: $APP" || warn "KobzarAI.app не знайдено — запускати доведеться скриптом"

# ── Підсумок ──────────────────────────────────────────────────────────
echo
if [ "$PROBLEMS" = 0 ]; then
  echo "✅ Проблем не знайдено."
else
  echo "🔴 Проблем: $PROBLEMS"
  [ "$FIX" = 0 ] && echo "   Спробувати полагодити автоматично:  ./doctor.sh --fix"
fi
[ "$FIXED" -gt 0 ] && echo "🔧 Полагоджено цим запуском: $FIXED"
exit 0
