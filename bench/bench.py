#!/usr/bin/env python3
"""
bench.py — практичний бенчмарк локальних моделей під реальні сценарії.
Без залежностей (stdlib). Б'є Ollama /api/generate, міряє швидкість/латентність,
зберігає повні відповіді у Markdown (читабельно) + сирі метрики у JSON.

Запуск:   python3 bench/bench.py
Звіти:    bench/results/run_<timestamp>.{md,json}

Сценарії заточені під користувача: AI-креатор + викладач інформатики, укр/рос/англ.
Оцінювання — людиною (або Claude) за готовим звітом; харнес лише збирає факти.
"""
import json, time, urllib.request, urllib.error, os, datetime, subprocess

OLLAMA = "http://127.0.0.1:11434"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
NUM_PREDICT = 320          # стеля токенів на відповідь (щоб бенч не тривав годинами на CPU)
TIMEOUT = 300

# Кандидати (текстові; vision/embed не сюди). Прибери/додай за смаком.
MODELS = [
    "gemma3:1b",
    "hf.co/INSAIT-Institute/MamayLM-Gemma-3-4B-IT-v1.0-GGUF:Q4_K_M",
    "gemma3:4b",
    "qwen3:4b",
    "huihui_ai/qwen3-abliterated:4b",
]

# Сценарії: (id, категорія, промпт, що перевіряємо очима)
PROMPTS = [
    ("ua_teach", "UA·викладання",
     "Поясни учневі 8 класу простими словами, що таке змінна у програмуванні. 4-5 речень, з життєвою аналогією.",
     "природна укр, коректна аналогія, рівень школяра"),
    ("ua_lesson", "UA·текст",
     "Напиши короткий (3 речення) вступ до уроку інформатики про алгоритми — щоб зачепити увагу класу.",
     "жива укр, без кальок, по темі"),
    ("code_write", "Код",
     "Напиши на Python функцію бінарного пошуку у відсортованому списку. Додай 1 речення пояснення складності.",
     "робочий код, правильний O(log n), без зайвого"),
    ("code_bug", "Код·дебаг",
     "Знайди помилку:\n\ndef avg(nums):\n    total = 0\n    for n in nums:\n        total += n\n    return total / len(nums)\n\nЩо станеться при avg([]) і як полагодити?",
     "бачить ділення на нуль, дає фікс"),
    ("reason", "Міркування",
     "У кошику 3 червоних і 5 синіх кульок. Витягую 2 не дивлячись. Яка ймовірність що обидві сині? Покажи кроки.",
     "правильна відповідь 5/14 ≈ 0.357, логіка видна"),
    ("ru", "RU",
     "Объясни кратко (3-4 предложения) что такое рекурсия, на примере.",
     "грамотна рос, коректний приклад"),
    ("en2ua", "EN→UA",
     "Answer in Ukrainian: what is the difference between a list and a tuple in Python?",
     "зрозумів англ, відповів укр, технічно вірно"),
    ("format", "Формат",
     "Дай рівно 3 поради як учневі не вигоріти від програмування. Тільки нумерований список 1-3, без вступу й висновку.",
     "точно 3 пункти, без зайвого тексту"),
    ("json", "JSON",
     'Поверни ЛИШЕ валідний JSON-обʼєкт з полями name (рядок "Python"), year (число 1991), typed (булеве false). Без markdown, без пояснень.',
     "чистий парсабельний JSON, без ```"),
    ("creative", "Креатив",
     "Придумай 3 коротких слогани українською для офлайн AI-асистента, що працює без інтернету. Кожен до 6 слів.",
     "свіжо, укр, в межах ліміту слів"),
]


def gen(model, prompt):
    body = json.dumps({
        "model": model, "prompt": prompt, "stream": False,
        "keep_alive": "2m",
        "options": {"num_predict": NUM_PREDICT, "temperature": 0.4},
    }).encode()
    req = urllib.request.Request(f"{OLLAMA}/api/generate", body,
                                 {"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        d = json.load(r)
    wall = time.time() - t0
    ev, evd = d.get("eval_count", 0), d.get("eval_duration", 1) or 1
    return {
        "text": d.get("response", "").strip(),
        "tok_s": round(ev / (evd / 1e9), 1),
        "eval_tokens": ev,
        "load_s": round(d.get("load_duration", 0) / 1e9, 2),
        "wall_s": round(wall, 1),
    }


def ps_size(model):
    try:
        out = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            if model.split(":")[0] in line:
                return line.split()[-3] + " " + line.split()[-2]  # розмір у RAM
    except Exception:
        pass
    return "?"


def unload(model):
    try:
        body = json.dumps({"model": model, "keep_alive": 0}).encode()
        urllib.request.urlopen(urllib.request.Request(
            f"{OLLAMA}/api/generate", body, {"Content-Type": "application/json"}), timeout=30)
    except Exception:
        pass


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    results = {}   # model -> {prompt_id -> metrics}
    ram = {}

    for m in MODELS:
        print(f"\n=== {m} ===")
        results[m] = {}
        for pid, cat, prompt, _ in PROMPTS:
            print(f"  {pid} ...", end="", flush=True)
            try:
                r = gen(m, prompt)
                print(f" {r['tok_s']} tok/s, {r['wall_s']}s")
            except Exception as e:
                r = {"text": f"[ПОМИЛКА: {e}]", "tok_s": 0, "eval_tokens": 0, "load_s": 0, "wall_s": 0}
                print(f" FAIL: {e}")
            results[m][pid] = r
        ram[m] = ps_size(m)
        unload(m)
        time.sleep(2)

    # JSON
    jpath = os.path.join(OUT_DIR, f"run_{stamp}.json")
    with open(jpath, "w") as f:
        json.dump({"models": MODELS, "ram": ram, "results": results,
                   "prompts": [{"id": p[0], "cat": p[1], "prompt": p[2], "check": p[3]} for p in PROMPTS]},
                  f, ensure_ascii=False, indent=2)

    # Markdown — групуємо по сценарію, моделі поруч (зручно порівнювати)
    md = [f"# Бенчмарк локальних моделей — {stamp}\n",
          "Залізо: M2 Air 8ГБ. Ліміт відповіді: %d токенів, temp 0.4.\n" % NUM_PREDICT,
          "## Швидкість (середнє tok/s по всіх сценаріях) + RAM\n",
          "| Модель | сер. tok/s | RAM (ollama ps) |", "|---|---|---|"]
    for m in MODELS:
        ts = [results[m][p[0]]["tok_s"] for p in PROMPTS if results[m][p[0]]["tok_s"]]
        avg = round(sum(ts) / len(ts), 1) if ts else 0
        md.append(f"| `{m.split('/')[-1]}` | {avg} | {ram.get(m,'?')} |")
    md.append("")

    for pid, cat, prompt, check in PROMPTS:
        md.append(f"\n## [{cat}] {pid}\n")
        md.append(f"**Промпт:** {prompt}\n")
        md.append(f"**Що оцінюємо:** {check}\n")
        for m in MODELS:
            r = results[m][pid]
            short = m.split("/")[-1]
            md.append(f"### {short}  ·  {r['tok_s']} tok/s · {r['wall_s']}s")
            md.append("```\n" + r["text"] + "\n```\n")

    mpath = os.path.join(OUT_DIR, f"run_{stamp}.md")
    with open(mpath, "w") as f:
        f.write("\n".join(md))

    print(f"\n✓ Звіт: {mpath}\n✓ Сирі дані: {jpath}")


if __name__ == "__main__":
    main()
