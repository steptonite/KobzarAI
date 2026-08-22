#!/bin/bash
# KobzarAI — інсталятор в одну команду. Відтворює робочий розклад:
#   ~/.local/kobzarai/             панель + .venv
#   ~/.local/styletts2-ua-server/  TTS-сервер + .venv + голоси
#   ~/.ollama/start-ollama.sh      лаунчер Ollama
# Голоси й нормалізаційні ресурси тягне сам. Ваги StyleTTS2 й моделі Ollama —
# завантажуються при першому використанні (моделі — твоїм `ollama pull`).
set -e

# Прапорці (див. README):
#   --no-tts   пропустити українську озвучку (torch + голоси ≈ кілька ГБ і довго).
#              Потрібна панель Ollama і більше нічого — це твій режим.
#   --embed    одразу завантажити bge-m3 — модель семантичного пошуку.
#              Бери, якщо ставиш Кобзаря під Second Brain Kit.
WITH_TTS=1; WITH_EMBED=0
while [ $# -gt 0 ]; do
  case "$1" in
    --no-tts) WITH_TTS=0; shift ;;
    --embed)  WITH_EMBED=1; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Невідомий аргумент: $1" >&2; exit 2 ;;
  esac
done

# 1. Тільки Apple Silicon
if [ "$(uname -m)" != "arm64" ]; then
  echo "✗ KobzarAI — лише macOS на Apple Silicon (M1/M2/M3…). Перервано."
  exit 1
fi

REPO="$(cd "$(dirname "$0")" && pwd)"
PANEL_DIR="$HOME/.local/kobzarai"
TTS_DIR="$HOME/.local/styletts2-ua-server"

# 2. Залежності — ставимо самі, щоб користувач нічого не готував руками.
#    Homebrew (може спитати пароль Mac — це нормально), Python 3.12, Ollama.
if ! command -v brew >/dev/null; then
  echo "→ Немає Homebrew — встановлюю (може запитати пароль Mac)…"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  for p in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$p" ] && eval "$("$p" shellenv)"; done
fi
command -v brew >/dev/null || { echo "✗ Homebrew не встановився. Постав вручну: https://brew.sh, потім запусти ./setup.sh знову."; exit 1; }

# 🔴 Мовчазний фолбек на системний python3 (це 3.9) робив venv, у якому pyobjc
#    або не ставиться, або ставиться кривим — і апка потім не малює меню-бар.
#    Урок Pysar: перевіряти ВЕРСІЮ, а не наявність. Порядок не «найновіший»:
#    колеса pyobjc відстають від свіжого CPython.
PY=""
for CAND in "$(brew --prefix)/opt/python@3.12/bin/python3.12" \
            "$(brew --prefix)/opt/python@3.13/bin/python3.13" \
            "$(brew --prefix)/opt/python@3.11/bin/python3.11"; do
  [ -x "$CAND" ] && { PY="$CAND"; break; }
done
if [ -z "$PY" ]; then
  echo "→ Встановлюю Python 3.12…"; brew install python@3.12
  PY="$(brew --prefix)/opt/python@3.12/bin/python3.12"
fi
if [ ! -x "$PY" ] || ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)'; then
  echo "✗ Потрібен Python 3.11+ від Homebrew, а знайдено: $("${PY:-python3}" -V 2>&1)"
  echo "  Системний python3 (3.9) не підходить: на ньому pyobjc не збереться і меню-бар не з'явиться."
  echo "  Постав вручну:  brew install python@3.12   — і запусти ./setup.sh знову."
  exit 1
fi
echo "→ Python: $("$PY" -V) ($PY)"

# 🔴 Нативний Ollama.app (з ollama.com) кладе CLI повз PATH. Без цієї перевірки
#    brew ставив ДРУГУ копію, і дві Ollama билися за порт 11434 та ~/.ollama/models.
if command -v ollama >/dev/null; then
  :
elif [ -d "/Applications/Ollama.app" ] || [ -x "/usr/local/bin/ollama" ]; then
  echo "→ Ollama вже стоїть як окремий застосунок — другу копію не ставлю."
  echo "  Якщо він конфліктуватиме з панеллю: лиши щось одне (застосунок АБО brew-сервіс)."
  export PATH="/usr/local/bin:$PATH"
else
  echo "→ Встановлюю Ollama…"; brew install ollama
fi

# 3. Панель
echo "→ Панель → $PANEL_DIR"
mkdir -p "$PANEL_DIR"
cp "$REPO/panel/panel.py" "$REPO/panel/make_icon.py" "$REPO/panel/kb.py" "$PANEL_DIR/"
rm -rf "$PANEL_DIR/ui"; cp -R "$REPO/panel/ui" "$PANEL_DIR/ui"
"$PY" -m venv "$PANEL_DIR/.venv"
"$PANEL_DIR/.venv/bin/pip" install -q --upgrade pip
"$PANEL_DIR/.venv/bin/pip" install -q -r "$REPO/panel/requirements.txt"

# 4. TTS-сервер (пропускається з --no-tts)
if [ "$WITH_TTS" = 1 ]; then
  echo "→ TTS-сервер → $TTS_DIR (тягне torch — буде довго)"
  mkdir -p "$TTS_DIR/voices"
  cp "$REPO/tts-server/server.py" "$REPO/tts-server/start-tts.sh" "$REPO/tts-server/requirements.txt" "$TTS_DIR/"
  "$PY" -m venv "$TTS_DIR/.venv"
  "$TTS_DIR/.venv/bin/pip" install -q --upgrade pip
  "$TTS_DIR/.venv/bin/pip" install -q -r "$TTS_DIR/requirements.txt"
  echo "→ Ресурси нормалізації (nltk для g2p_en)…"
  "$TTS_DIR/.venv/bin/python" -c "import nltk; nltk.download('averaged_perceptron_tagger_eng'); nltk.download('cmudict')" 2>/dev/null || true
  echo "→ Голоси (patriotyk/styletts2-ukrainian: filatov + voices/)…"
  "$TTS_DIR/.venv/bin/python" - "$TTS_DIR" <<'PY'
import sys
from huggingface_hub import snapshot_download
snapshot_download(repo_id="patriotyk/styletts2-ukrainian", repo_type="space",
                    allow_patterns=["filatov.pt", "voices/*.pt"], local_dir=sys.argv[1])
print("  голоси завантажено")
PY
else
  echo "→ Озвучку пропущено (--no-tts). Додати пізніше: ./setup.sh"
fi

# 5. Лаунчер Ollama
mkdir -p "$HOME/.ollama"
cp "$REPO/panel/start-ollama.sh" "$HOME/.ollama/start-ollama.sh"
chmod +x "$HOME/.ollama/start-ollama.sh"

# 6. Модель семантичного пошуку (--embed)
if [ "$WITH_EMBED" = 1 ]; then
  echo "→ Модель пошуку bge-m3 (~1.2 ГБ)…"
  # pull потребує живого сервера; якщо він уже піднятий — чужий процес не чіпаємо.
  OWN_SERVE=0
  if ! ollama list >/dev/null 2>&1; then
    ollama serve >/tmp/kobzarai-ollama-setup.log 2>&1 &
    OWN_SERVE=$!
    for _ in $(seq 1 30); do ollama list >/dev/null 2>&1 && break; sleep 1; done
  fi
  ollama pull bge-m3 </dev/null || echo "  ⚠️ bge-m3 не завантажилась — доробиш кнопкою в панелі"
  [ "$OWN_SERVE" != 0 ] && kill "$OWN_SERVE" 2>/dev/null || true
fi

# 7. Іконка + застосунок KobzarAI.app (клікабельний, як звичайна програма)
echo "→ Іконка та KobzarAI.app…"
"$PANEL_DIR/.venv/bin/python" "$PANEL_DIR/make_icon.py" >/tmp/kobzarai-icon.log 2>&1 || \
  echo "  ⚠️ генератор іконки не відпрацював (деталі: /tmp/kobzarai-icon.log) — беру запасний шлях"
# Запасний шлях без Pillow: зібрати .icns із готового icon.png системними sips/iconutil.
if [ ! -f "$PANEL_DIR/app.icns" ] && [ -f "$REPO/panel/icon.png" ]; then
  ICONSET="$(mktemp -d)/app.iconset"; mkdir -p "$ICONSET"
  for SZ in 16 32 64 128 256 512; do
    sips -z $SZ $SZ "$REPO/panel/icon.png" --out "$ICONSET/icon_${SZ}x${SZ}.png" >/dev/null 2>&1
    sips -z $((SZ*2)) $((SZ*2)) "$REPO/panel/icon.png" --out "$ICONSET/icon_${SZ}x${SZ}@2x.png" >/dev/null 2>&1
  done
  iconutil -c icns "$ICONSET" -o "$PANEL_DIR/app.icns" >/dev/null 2>&1 && echo "  ✓ іконку зібрано запасним шляхом"
fi
# KOBZARAI_APP_DIR — щоб установку можна було прогнати в ізольованому HOME,
# не чіпаючи /Applications живої машини. Без неї тест ламає робочу копію.
APP_DIR="${KOBZARAI_APP_DIR:-/Applications}"; [ -w "$APP_DIR" ] || APP_DIR="$HOME/Applications"
mkdir -p "$APP_DIR"
APP="$APP_DIR/KobzarAI.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
[ -f "$PANEL_DIR/app.icns" ] && cp "$PANEL_DIR/app.icns" "$APP/Contents/Resources/app.icns"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>ua.kobzarai.panel</string>
  <key>CFBundleName</key><string>KobzarAI</string>
  <key>CFBundleDisplayName</key><string>KobzarAI</string>
  <key>CFBundleExecutable</key><string>KobzarAI</string>
  <key>CFBundleIconFile</key><string>app</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>LSUIElement</key><true/>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
</dict></plist>
PLIST

# Лаунчер: БЕЗ exec (інакше macOS 26 не малює меню-бар-іконку, FB21015611).
# Запускає копію python-бінарника всередині bundle → Dock-ідентичність = KobzarAI.
cat > "$APP/Contents/MacOS/KobzarAI" <<'LAUNCH'
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
BIN="$DIR/KobzarAI-bin"
VENV="$HOME/.local/kobzarai/.venv/bin/python"
if [ ! -x "$BIN" ]; then            # створюємо bundle-бінарник при першому запуску
  FW="$("$VENV" -c 'import sys,os;print(os.path.join(sys.base_prefix,"Resources","Python.app","Contents","MacOS","Python"))' 2>/dev/null)"
  [ -x "$FW" ] && cp "$FW" "$BIN" && codesign --force --sign - "$BIN" 2>/dev/null
fi
[ -x "$BIN" ] || BIN="$VENV"
export __PYVENV_LAUNCHER__="$VENV"
export __CFBundleIdentifier="ua.kobzarai.panel"
"$BIN" "$HOME/.local/kobzarai/panel.py" >/tmp/kobzarai.log 2>&1 &
wait
LAUNCH
chmod +x "$APP/Contents/MacOS/KobzarAI"

cat <<EOF

✓ Готово. KobzarAI.app → $APP
  озвучка: $([ "$WITH_TTS" = 1 ] && echo "встановлена" || echo "пропущена (--no-tts)")
  bge-m3:  $([ "$WITH_EMBED" = 1 ] && echo "завантажена" || echo "не завантажувалась")

Далі — два кроки мишкою:
  1) Запусти KobzarAI з Launchpad.
  2) Коли macOS попросить — дозволь Accessibility (для хоткеїв і читання виділеного).

Модель завантажиш кнопкою в самому застосунку. Все інше теж у меню — терміналу більше не треба.
EOF
