#!/bin/bash
# Лаунчер Ollama для панелі. Скопіюй у ~/.ollama/start-ollama.sh (саме там його шукає панель).
# Папку моделей і прапори оптимізації задає UI панелі (config.json).
# 🔴 22.08.2026: дефолтом тут стояв /Volumes/ExternalSSD — зовнішній диск АВТОРА.
# На чужій машині цей шлях не існує, скрипт мовчки робив exit 0, і Ollama не
# піднімалась — при тому, що setup.sh уже поклав моделі в ~/.ollama/models.
# Дефолт = стандартна папка Ollama. Зовнішній диск — свідомий вибір (KOBZARAI_DISK).
CFG="$HOME/.local/kobzarai/config.json"
if [ -n "${KOBZARAI_DISK:-}" ]; then
  MODELS="$KOBZARAI_DISK/ollama-models"
else
  MODELS="$HOME/.ollama/models"
fi
FLASH=1; KV=1                              # дефолти = обидві оптимізації увімкнені
if [ -f "$CFG" ]; then
  V=$(/usr/bin/python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("models_dir") or "")' "$CFG" 2>/dev/null)
  [ -n "$V" ] && MODELS="$V"
  FLASH=$(/usr/bin/python3 -c 'import json,sys;print(1 if json.load(open(sys.argv[1])).get("ollama_flash",True) else 0)' "$CFG" 2>/dev/null)
  KV=$(/usr/bin/python3 -c 'import json,sys;print(1 if json.load(open(sys.argv[1])).get("ollama_kv_q8",True) else 0)' "$CFG" 2>/dev/null)
fi
# Якщо вибраний шлях відпав (від'єднали диск), а стандартна папка жива — беремо її.
if [ ! -d "$MODELS/manifests" ] && [ -d "$HOME/.ollama/models/manifests" ]; then
  MODELS="$HOME/.ollama/models"
fi
[ -d "$MODELS/manifests" ] || exit 0      # моделей нема ніде — не стартуємо, фантом не створюємо
pgrep -x ollama >/dev/null && exit 0       # вже працює
export OLLAMA_MODELS="$MODELS"
export OLLAMA_ORIGINS="*"
# --- оптимізація під 8ГБ RAM (керується тоглами в Налаштування → Загальні) ---
[ "$FLASH" = "1" ] && export OLLAMA_FLASH_ATTENTION=1            # менше RAM на KV-кеш, швидше
[ "$FLASH" = "1" ] && [ "$KV" = "1" ] && export OLLAMA_KV_CACHE_TYPE=q8_0  # KV у 8-біт (потребує flash)
export OLLAMA_MAX_LOADED_MODELS=1    # одна модель у RAM — без свопу
export OLLAMA_NUM_PARALLEL=1         # один слот, не множимо контекст у RAM
export OLLAMA_KEEP_ALIVE=5m          # вивантажувати модель через 5хв простою
# Бінарник шукаємо, а не припускаємо: на Intel це /usr/local/bin,
# у нативного Ollama.app — усередині бандла.
OLLAMA_BIN="$(command -v ollama || true)"
for CAND in /opt/homebrew/bin/ollama /usr/local/bin/ollama \
            /Applications/Ollama.app/Contents/Resources/ollama; do
  [ -n "$OLLAMA_BIN" ] && break
  [ -x "$CAND" ] && OLLAMA_BIN="$CAND"
done
[ -n "$OLLAMA_BIN" ] || exit 0            # не встановлена — про це говорить панель
exec "$OLLAMA_BIN" serve
