#!/bin/bash
# Запуск StyleTTS2 TTS-сервера для Cherry. Локальний, не залежить від зовнішнього диска.
cd "$(cd "$(dirname "$0")" && pwd)" || exit 1
# вже запущений?
if lsof -ti :5050 >/dev/null 2>&1; then exit 0; fi
exec .venv/bin/python -u server.py
