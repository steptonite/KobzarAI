#!/bin/bash
# Kobzar — інсталятор в одну команду. Відтворює робочий розклад:
#   ~/.local/localai-panel/        панель + .venv
#   ~/.local/styletts2-ua-server/  TTS-сервер + .venv
#   ~/.ollama/start-ollama.sh      лаунчер Ollama
# Не качає голоси й моделі (це окремо — див. кінець) і не чіпає дозволи.
set -e

# 1. Тільки Apple Silicon
if [ "$(uname -m)" != "arm64" ]; then
  echo "✗ Kobzar — лише macOS на Apple Silicon (M1/M2/M3…). Перервано."
  exit 1
fi
command -v python3 >/dev/null || { echo "✗ Потрібен python3 (brew install python@3.12)"; exit 1; }

REPO="$(cd "$(dirname "$0")" && pwd)"
PANEL_DIR="$HOME/.local/localai-panel"
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
"$TTS_DIR/.venv/bin/python" -c "import nltk; nltk.download('averaged_perceptron_tagger_eng'); nltk.download('cmudict')" 2>/dev/null || true

# 5. Лаунчер Ollama
mkdir -p "$HOME/.ollama"
cp "$REPO/panel/start-ollama.sh" "$HOME/.ollama/start-ollama.sh"
chmod +x "$HOME/.ollama/start-ollama.sh"

cat <<EOF

✓ Базу встановлено. Лишилось вручну:
  1) Голоси (обовʼязково для озвучки): постав *.pt у $TTS_DIR/voices/
       з HuggingFace — patriotyk (див. README → Подяки).
  2) Хоча б одна модель Ollama:   ollama pull qwen3:4b
  3) (опц.) диск моделей на SSD:   export LOCALAI_DISK="/Volumes/ТвійSSD"
  4) Запуск панелі:
       $PANEL_DIR/.venv/bin/python $PANEL_DIR/panel.py
     При першому старті дай дозвіл Accessibility (для хоткеїв і читання виділеного).
EOF
