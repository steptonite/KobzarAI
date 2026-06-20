#!/bin/bash
# Лаунчер Ollama для панелі. Скопіюй у ~/.ollama/start-ollama.sh (саме там його шукає панель).
# Папку моделей і прапори оптимізації задає UI панелі (config.json). Дефолт диска — KOBZARAI_DISK.
CFG="$HOME/.local/kobzarai/config.json"
MODELS="${KOBZARAI_DISK:-/Volumes/ExternalSSD}/ollama-models"
FLASH=1; KV=1                              # дефолти = обидві оптимізації увімкнені
if [ -f "$CFG" ]; then
  V=$(/usr/bin/python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("models_dir") or "")' "$CFG" 2>/dev/null)
  [ -n "$V" ] && MODELS="$V"
  FLASH=$(/usr/bin/python3 -c 'import json,sys;print(1 if json.load(open(sys.argv[1])).get("ollama_flash",True) else 0)' "$CFG" 2>/dev/null)
  KV=$(/usr/bin/python3 -c 'import json,sys;print(1 if json.load(open(sys.argv[1])).get("ollama_kv_q8",True) else 0)' "$CFG" 2>/dev/null)
fi
[ -d "$MODELS/manifests" ] || exit 0      # диска/папки нема — не стартуємо, фантом не створюємо
pgrep -x ollama >/dev/null && exit 0       # вже працює
export OLLAMA_MODELS="$MODELS"
export OLLAMA_ORIGINS="*"
# --- оптимізація під 8ГБ RAM (керується тоглами в Налаштування → Загальні) ---
[ "$FLASH" = "1" ] && export OLLAMA_FLASH_ATTENTION=1            # менше RAM на KV-кеш, швидше
[ "$FLASH" = "1" ] && [ "$KV" = "1" ] && export OLLAMA_KV_CACHE_TYPE=q8_0  # KV у 8-біт (потребує flash)
export OLLAMA_MAX_LOADED_MODELS=1    # одна модель у RAM — без свопу
export OLLAMA_NUM_PARALLEL=1         # один слот, не множимо контекст у RAM
export OLLAMA_KEEP_ALIVE=5m          # вивантажувати модель через 5хв простою
exec /opt/homebrew/bin/ollama serve
