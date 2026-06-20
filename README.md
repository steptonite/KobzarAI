# KobzarAI

Офлайн AI-робоче місце для macOS. Меню-бар застосунок тримає поруч локальну мовну модель ([Ollama](https://ollama.com)) і українську озвучку (StyleTTS2): модель пише — голос одразу читає. Без інтернету, акаунтів і телеметрії.

`macOS · Apple Silicon` &nbsp;•&nbsp; `офлайн` &nbsp;•&nbsp; `українська` &nbsp;•&nbsp; `MIT`

<video src="https://github.com/steptonite/KobzarAI/raw/main/media/preview.mp4" controls width="720"></video>

> [!IMPORTANT]
> Працює лише на **Apple Silicon** (M1/M2/M3…) — застосунок нативний (Cocoa/Quartz через pyobjc), на Intel/Windows/Linux не запуститься. Тестовано на MacBook Air M2 (8 ГБ).

## Що вміє

- **Керування Ollama з меню-бару** — старт/стоп, активна модель, вивантаження з RAM, індикатор RAM і swap, завантаження нових моделей (Ollama library або HuggingFace GGUF). Моделі можна тримати на зовнішньому SSD.
- **Українська озвучка** ([StyleTTS2-UA](https://huggingface.co/patriotyk)) — читає виділений текст або буфер обміну, пауза/стоп, глобальні хоткеї. Виділене береться через Accessibility, не чіпаючи буфер.
- **Міні-чат** — легке вікно для розмови з активною моделлю, з опційною автоозвучкою відповіді.
- **Тоглі під 8 ГБ** — Flash Attention і 8-біт KV-кеш прямо в налаштуваннях, без правки env.

## Встановлення

Потрібні [Homebrew](https://brew.sh) і Python 3.12 (`brew install python@3.12`).

```bash
git clone https://github.com/steptonite/KobzarAI.git
cd KobzarAI
./setup.sh
```

`setup.sh` робить усе сам: ставить панель і TTS-сервер (кожен у власному venv), завантажує голоси, кладе лаунчер Ollama і збирає **KobzarAI.app** у Програмах. Далі лишається:

1. Завантажити модель: `ollama pull qwen3:4b`
2. Запустити **KobzarAI** з Launchpad.
3. При першому старті дати дозвіл Accessibility (Системні налаштування → Конфіденційність і безпека → Доступність) — для хоткеїв і читання виділеного.

Ваги StyleTTS2 підтягуються автоматично при першому синтезі. Моделі на зовнішньому SSD: `export KOBZARAI_DISK="/Volumes/ТвійSSD"` перед запуском.

## Режими озвучки

| Режим | Як працює | Коли брати |
|---|---|---|
| **Базовий** | Увесь текст одним запитом, потім грає. Найрівніший тембр. | Короткий текст, максимальна якість. |
| **Стрім** | Грає поточний шматок, поки синтезується наступний. Перший звук ~0.7 с. | Виділене / буфер. |
| **Реалтайм** | Читає речення, поки модель ще пише. Тембр може трохи стрибати між реченнями. | Чат — чуєш відповідь майже одразу. |

Перед синтезом текст нормалізується: числа → словами ([num2words](https://github.com/savoirfairelinux/num2words)), абревіатури по літерах (`ДПА` → «де-пе-а»), символи (`%`, `₴`, `°`, `№`…) словами, латиниця → українська фонетика ([g2p_en](https://github.com/Kyubyong/g2p)). Емоджі вирізаються.

## Моделі

Бюджет під модель — **~4–5 ГБ RAM**, практична стеля = **4B у Q4_K_M**.

| Сценарій | Модель |
|---|---|
| Українська (тексти, уроки) | **MamayLM-Gemma-3-4B** ([INSAIT](https://huggingface.co/INSAIT-Institute)) |
| Код / міркування / мультимова | **qwen3:4b** |
| Vision (фото/скрін → текст) | **qwen3-vl:4b** |
| Швидкий чернетковий | **gemma3:1b** |
| Embeddings (RAG) | **nomic-embed-text** |

Прапори оптимізації (`OLLAMA_FLASH_ATTENTION`, `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_MAX_LOADED_MODELS=1`…) зашиті в `start-ollama.sh`. `num_ctx` ≤ 8192 — критично, інакше своп.

## Приватність

Під час роботи нічого не виходить у мережу — ні моделі, ні озвучка. Єдиний онлайн-момент — коли сам тягнеш моделі й голоси при встановленні. Без телеметрії, акаунтів і ключів; конфіг — локальний JSON у `~/.local/kobzarai/`. Сервіси стартуєш і зупиняєш руками з меню — жодних фонових демонів. У репозиторії немає персональних даних чи зашитих шляхів (диск моделей задається через `KOBZARAI_DISK` або UI).

## Структура

```
setup.sh          інсталятор в одну команду (venv-и, голоси, лаунчер, KobzarAI.app)
panel/            меню-бар застосунок (rumps + pyobjc)
  panel.py          логіка: Ollama, TTS, RAM, хоткеї, налаштування, міні-чат
  make_icon.py      генератор іконки (Pillow → .icns)
  start-ollama.sh   лаунчер Ollama з env-оптимізацією
tts-server/       OpenAI-сумісний TTS-сервер (Flask :5050, StyleTTS2 на CPU)
bench/            бенчмарки моделей під 8 ГБ
```

TTS — OpenAI-сумісний ендпойнт (`POST /v1/audio/speech`), тож його бачить будь-який клієнт, що вміє `audio/speech` (Cherry Studio, скрипти).

## Подяки

- [Ollama](https://ollama.com) — рантайм локальних моделей.
- [patriotyk](https://huggingface.co/patriotyk) — українські StyleTTS2-моделі, голоси та інструменти.
- [num2words](https://github.com/savoirfairelinux/num2words), [g2p_en](https://github.com/Kyubyong/g2p) — нормалізація тексту.
- [rumps](https://github.com/jaredks/rumps), [pyobjc](https://pyobjc.readthedocs.io) — меню-бар і нативний macOS.
- MamayLM ([INSAIT](https://huggingface.co/INSAIT-Institute)) — українська Gemma-3-4B.

## Ліцензія

MIT (код). Голосові моделі StyleTTS2 — за ліцензією patriotyk; MamayLM — Gemma terms.
