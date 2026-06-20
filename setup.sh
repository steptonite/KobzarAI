#!/bin/bash
# KobzarAI — інсталятор в одну команду. Відтворює робочий розклад:
#   ~/.local/kobzarai/             панель + .venv
#   ~/.local/styletts2-ua-server/  TTS-сервер + .venv + голоси
#   ~/.ollama/start-ollama.sh      лаунчер Ollama
# Голоси й нормалізаційні ресурси тягне сам. Ваги StyleTTS2 й моделі Ollama —
# завантажуються при першому використанні (моделі — твоїм `ollama pull`).
set -e

# 1. Тільки Apple Silicon
if [ "$(uname -m)" != "arm64" ]; then
  echo "✗ KobzarAI — лише macOS на Apple Silicon (M1/M2/M3…). Перервано."
  exit 1
fi
command -v python3 >/dev/null || { echo "✗ Потрібен python3 (brew install python@3.12)"; exit 1; }

REPO="$(cd "$(dirname "$0")" && pwd)"
PANEL_DIR="$HOME/.local/kobzarai"
TTS_DIR="$HOME/.local/styletts2-ua-server"

# 2. Ollama
if ! command -v ollama >/dev/null; then
  if command -v brew >/dev/null; then echo "→ Встановлюю Ollama…"; brew install ollama
  else echo "⚠ Немає Ollama й Homebrew — постав Ollama вручну: https://ollama.com"; fi
fi

# 3. Панель
echo "→ Панель → $PANEL_DIR"
mkdir -p "$PANEL_DIR"
cp "$REPO/panel/panel.py" "$REPO/panel/make_icon.py" "$PANEL_DIR/"
python3 -m venv "$PANEL_DIR/.venv"
"$PANEL_DIR/.venv/bin/pip" install -q --upgrade pip
"$PANEL_DIR/.venv/bin/pip" install -q -r "$REPO/panel/requirements.txt"

# 4. TTS-сервер
echo "→ TTS-сервер → $TTS_DIR (тягне torch — буде довго)"
mkdir -p "$TTS_DIR/voices"
cp "$REPO/tts-server/server.py" "$REPO/tts-server/start-tts.sh" "$REPO/tts-server/requirements.txt" "$TTS_DIR/"
python3 -m venv "$TTS_DIR/.venv"
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

# 5. Лаунчер Ollama
mkdir -p "$HOME/.ollama"
cp "$REPO/panel/start-ollama.sh" "$HOME/.ollama/start-ollama.sh"
chmod +x "$HOME/.ollama/start-ollama.sh"

# 6. Іконка + застосунок KobzarAI.app (клікабельний, як звичайна програма)
echo "→ Іконка та KobzarAI.app…"
"$PANEL_DIR/.venv/bin/python" "$PANEL_DIR/make_icon.py" >/dev/null 2>&1 || true
APP_DIR="/Applications"; [ -w "$APP_DIR" ] || APP_DIR="$HOME/Applications"
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

Лишилось:
  1) Хоча б одна модель Ollama:   ollama pull qwen3:4b
  2) (опц.) моделі на зовнішньому SSD:   export KOBZARAI_DISK="/Volumes/ТвійSSD"
  3) Запусти KobzarAI з Launchpad (або open "$APP").
  4) При першому старті дай дозвіл Accessibility (хоткеї + читання виділеного):
     Системні налаштування → Конфіденційність і безпека → Доступність → +KobzarAI
EOF
