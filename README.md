# KobzarAI

**Повністю офлайн AI-робоче місце для macOS** — меню-бар застосунок, що тримає поруч локальні мовні моделі (через [Ollama](https://ollama.com)) і **українську озвучку** (StyleTTS2). Модель думає, голос говорить — і все це без інтернету, ключів і телеметрії.

> Назва — від кобзаря, мандрівного співця: дума народжується в голові, а звучить уголос.

`macOS · Apple Silicon` &nbsp;•&nbsp; `офлайн` &nbsp;•&nbsp; `українська` &nbsp;•&nbsp; `MIT`

![icon](panel/icon.png)

> [!IMPORTANT]
> **Тільки macOS на Apple Silicon** (M1/M2/M3…). Залежить від нативного Cocoa/Quartz (pyobjc) — на Intel-Mac, Windows чи Linux не працює.
> Розроблено й протестовано на MacBook Air M2 (8 ГБ) — звідси аскетизм щодо памʼяті по всьому стеку.

---

## Філософія

- **Офлайн і приватно.** Жодних хмар, акаунтів, телеметрії. Текст не виходить за межі Mac.
- **Без прихованих автозапусків.** Жодних `launchd`/демонів/`KeepAlive`. Кожен сервіс стартуєш і **зупиняєш руками** з меню. Свідоме рішення (раз обпеклися: фоновий демон зробив озвучку невбивною й сам вантажив RAM).
- **Одна модель у RAM.** На скромній памʼяті немає місця під дві — стек це поважає.

## Можливості

**Керування Ollama з меню-бару** — старт/стоп, активна модель, вивантаження з RAM, індикація RAM/swap (з ⚠ коли swap росте), завантаження нових моделей (Ollama library або HuggingFace GGUF). Моделі можна тримати на зовнішньому SSD.

**Українська озвучка** ([StyleTTS2-UA](https://huggingface.co/patriotyk)) — озвучити виділений текст або буфер обміну, пауза/стоп, глобальні хоткеї. Виділене читається через **Accessibility API** *без* засмічення буфера обміну. Стан прямо в іконці: ⏳ синтез · ♪ грає · ‖ пауза.

**Міні-чат** — легке вікно для розмови з активною моделлю, з опційною автоозвучкою відповіді.

**Налаштування під 8 ГБ** — тоглі оптимізації Ollama (Flash Attention, KV-кеш 8-біт) прямо в UI, без правки env руками.

## Три режими озвучки

StyleTTS2 — велика модель; на скромній памʼяті синтез довгого тексту відчутно затримує перший звук. Звідси три режими (Налаштування → Голос):

| Режим | Як працює | Коли брати |
|---|---|---|
| **Базовий** | Увесь текст одним запитом, потім грає. Найрівніший тембр. | Короткий текст, максимальна якість. |
| **Стрім** | Конвеєр: грає шматок N поки в фоні синтезується N+1. Перший звук ~0.7 с замість ~3 с. | Виділене/буфер — щоб не чекати. |
| **Реалтайм** | Озвучує речення **поки модель ще пише** (ефект «живого диктора»). Речення батчаться у шматки, щоб тембр не стрибав. | Чат — слухаєш відповідь майже одразу. |

Перед синтезом текст чиститься від емоджі (модель їх не читає).

### Текстова нормалізація

TTS-модель сама не читає цифри, абревіатури й латиницю — сервер їх розгортає:

- **Числа → слова:** `15` → «пʼятнадцять» ([num2words](https://github.com/savoirfairelinux/num2words), uk).
- **Абревіатури по літерах:** `ДПА` → «де-пе-а»; винятки (`НАТО`, `ЮНЕСКО`…) — як слова.
- **Символи:** `%`, `₴`, `$`, `°`, `№`, `@`, `#`, `/`… → словами.
- **Латиниця → українська фонетика** через [g2p_en](https://github.com/Kyubyong/g2p) (ARPABET → укр): `I go to bed` → «ай ґоу ту бед». Англійські слова не перемикають голос на «кривий англійський».

## Встановлення

> Потрібні [Homebrew](https://brew.sh) і Python 3.12 (`brew install python@3.12`).

**В одну команду** — ставить venv-и, залежності, **голоси** й лаунчер:

```bash
git clone https://github.com/steptonite/kobzar.git
cd kobzar
./setup.sh
```

`setup.sh` сам:
- поставить панель у `~/.local/kobzarai/` і TTS-сервер у `~/.local/styletts2-ua-server/` (кожен зі своїм `.venv`);
- завантажить **голоси** (`filatov.pt` + `voices/*.pt`) з HF Space [patriotyk/styletts2-ukrainian](https://huggingface.co/spaces/patriotyk/styletts2-ukrainian) і ресурси нормалізації (nltk);
- покладе лаунчер Ollama у `~/.ollama/start-ollama.sh`.

Лишається тільки `ollama pull` модель і дозвіл Accessibility — скрипт нагадає.

> Ваги StyleTTS2 (`patriotyk/styletts2_ukrainian_single` / `_multispeaker`) тягнуться автоматично при першому синтезі.

<details>
<summary><b>Або вручну, крок за кроком</b></summary>

```bash
brew install ollama
PANEL=~/.local/kobzarai; TTS=~/.local/styletts2-ua-server

# Панель
mkdir -p $PANEL && cp panel/panel.py panel/make_icon.py $PANEL/
python3 -m venv $PANEL/.venv
$PANEL/.venv/bin/pip install -r panel/requirements.txt

# TTS-сервер (тягне torch — довго)
mkdir -p $TTS/voices && cp tts-server/{server.py,start-tts.sh,requirements.txt} $TTS/
python3 -m venv $TTS/.venv
$TTS/.venv/bin/pip install -r $TTS/requirements.txt
$TTS/.venv/bin/python -c "import nltk; nltk.download('averaged_perceptron_tagger_eng'); nltk.download('cmudict')"

# Голоси з HF Space patriotyk
$TTS/.venv/bin/python -c "from huggingface_hub import snapshot_download; \
snapshot_download(repo_id='patriotyk/styletts2-ukrainian', repo_type='space', \
allow_patterns=['filatov.pt','voices/*.pt'], local_dir='$TTS')"

# Лаунчер Ollama
cp panel/start-ollama.sh ~/.ollama/start-ollama.sh && chmod +x ~/.ollama/start-ollama.sh
```
</details>

## Запуск

```bash
# (опц.) диск з моделями Ollama на зовнішньому SSD:
export KOBZARAI_DISK="/Volumes/MyExternalSSD"

# панель (TTS і Ollama стартуються з меню панелі)
~/.local/kobzarai/.venv/bin/python ~/.local/kobzarai/panel.py
```

При першому запуску дай дозвіл **Accessibility** (Системні налаштування → Конфіденційність і безпека → Доступність → додай KobzarAI) — для хоткеїв і читання виділеного. Після видачі дозволу хоткеї підхоплюються без перезапуску.

> Хочеш іконку в Док як окремий застосунок — збери `.app` навколо цього ж `panel.py` (нюанс із меню-бар-іконкою описаний у «Граблях»).

## Моделі

Бюджет під модель — **~4–5 ГБ RAM**, тож практична стеля = **4B у Q4_K_M**. Перевірені ролі:

| Сценарій | Модель |
|---|---|
| Українська (тексти, уроки) | **MamayLM-Gemma-3-4B** (INSAIT) — сильний укр 4B |
| Код / міркування / мультимова | **qwen3:4b** |
| Vision (фото/скрін → текст) | **qwen3-vl:4b** |
| Швидкий чернетковий | **gemma3:1b** |
| Embeddings (RAG) | **nomic-embed-text** |

Прапори оптимізації (`OLLAMA_FLASH_ATTENTION`, `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_KEEP_ALIVE=5m`) зашиті в `start-ollama.sh`; перші два — тоглами в налаштуваннях. `num_ctx` ≤ 8192 у клієнті — критично, інакше своп.

## Структура

```
setup.sh          інсталятор в одну команду (venv-и, голоси, лаунчер)
panel/            меню-бар застосунок (rumps + pyobjc)
  panel.py          уся логіка: Ollama, TTS, RAM, хоткеї, налаштування, міні-чат
  make_icon.py      генератор іконки (Pillow → .icns)
  start-ollama.sh   лаунчер Ollama (env-оптимізація з config.json) → ~/.ollama/
  requirements.txt
tts-server/       OpenAI-сумісний TTS-сервер
  server.py         Flask :5050, POST /v1/audio/speech, StyleTTS2 на CPU
  start-tts.sh      запуск (лише якщо порт вільний)
  requirements.txt
bench/            бенчмарки моделей під 8 ГБ (швидкість, ablation, vision)
```

TTS — **OpenAI-сумісний** ендпойнт, тож його бачить будь-який клієнт, що вміє `audio/speech` (Cherry Studio, скрипти тощо).

## Приватність і безпека

- **Нічого не виходить у мережу** під час роботи: ні моделі, ні озвучка не шлють текст назовні. Єдиний онлайн-момент — коли ти сам тягнеш моделі/голоси при встановленні.
- **Без телеметрії, акаунтів, ключів.** Конфіг — локальний JSON у `~/.local/kobzarai/`.
- У репозиторії **немає персональних даних і зашитих шляхів** — диск моделей задається через `KOBZARAI_DISK` або UI, усе інше відносне до `~`.

## Граблі розробки (нюанси, на яких підірвалися)

- **macOS 26 не малює меню-бар-іконку, якщо `.app` запускає Python через `exec`** ([Apple FB21015611](https://developer.apple.com/bug-reporting/)). Лаунчер мусить запускати python **дочірнім** процесом і робити `wait`, а не `exec`. Активаційна політика — `accessory`.
- **pyobjc:** кожен метод підкласу `NSObject` трактується як селектор. Чисто-пайтонівські хелпери **обовʼязково** з `@objc.python_method`, інакше `BadPrototypeError`.
- **Виділення тягнуло буфер** доки застосунок не мав Accessibility: і AX-читання, і синтетичний `⌘C` мовчки фейляться без trust. Корінь — дозвіл, а не код. (Зміна bundle ID скидає дозвіл — після ребрендингу його дають наново.)
- **TTS + модель разом** на скромній памʼяті співіснують, але синтез сповільнюється через своп. Для уроку/демо: спершу згенеруй текст, *потім* озвучуй (або вмикай Стрім/Реалтайм для швидкого старту).
- **Реалтайм-дрейф тембру** гаситься батчингом: речення з потоку LLM зливаються у довші шматки (перший — короткий для швидкого старту), тож на TTS іде менше окремих запитів → менше перемикань style-вектора.
- **Скрол вкладок налаштувань** — фіксовані вкладки завжди в `NSScrollView` з перевернутим clip-view (контент пришпилений до верху, скролбар автоприховується), щоб висота вкладки не різала інфо на низьких екранах.

## Подяки

- [Ollama](https://ollama.com) — локальний рантайм мовних моделей.
- [patriotyk](https://huggingface.co/patriotyk) — українські StyleTTS2-моделі, голоси та інструменти (`styletts2-inference`, `ipa-uk`, `ukrainian-word-stress`).
- [num2words](https://github.com/savoirfairelinux/num2words), [g2p_en](https://github.com/Kyubyong/g2p) — нормалізація тексту.
- [rumps](https://github.com/jaredks/rumps), [pyobjc](https://pyobjc.readthedocs.io) — меню-бар і нативний macOS.
- MamayLM ([INSAIT](https://huggingface.co/INSAIT-Institute)) — українська Gemma-3-4B.

## Ліцензія

MIT (код). Голосові моделі StyleTTS2 — за ліцензією їхніх авторів (patriotyk); MamayLM — Gemma terms.

---

*Зроблено як офлайн-інструмент українського AI-креатора й викладача. PR і issue вітаються.*
