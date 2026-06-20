#!/usr/bin/env python3
"""VL-тест: подає одне зображення (vl_test.png) кільком моделям, збирає описи.
Очікуваний вміст (для оцінки очима):
  - заголовок 'Урок 5: Алгоритми' (кирилиця)
  - червоне коло + синій квадрат (рівно 2 фігури)
  - число 1991
  - код 'def avg(nums): return sum(nums)/len(nums)'
Текстові моделі впадуть/зігнорять картинку — це теж результат (хто реально VL).

Запуск:  python3 bench/vl_test.py
         BENCH_VL_MODELS="a,b" python3 bench/vl_test.py
"""
import base64, json, os, time, urllib.request, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
OLLAMA = "http://127.0.0.1:11434"
IMG = os.path.join(HERE, "vl_test.png")
OUT_DIR = os.path.join(HERE, "results")

_DEFAULT = [
    "gemma3:4b",
    "hf.co/mlabonne/gemma-3-4b-it-abliterated-GGUF:Q4_K_M",
    "huihui_ai/qwen3-vl-abliterated:4b",
    "hf.co/INSAIT-Institute/MamayLM-Gemma-3-4B-IT-v1.0-GGUF:Q4_K_M",  # контроль: має vision?
]
MODELS = (os.environ.get("BENCH_VL_MODELS", "").split(",")
          if os.environ.get("BENCH_VL_MODELS") else _DEFAULT)

PROMPT = ("Уважно опиши це зображення українською. 1) Прочитай ВЕСЬ текст дослівно. "
          "2) Назви всі геометричні фігури та їх кольори і скільки їх. 3) Назви число.")


def ask(model, img_b64):
    payload = {"model": model, "prompt": PROMPT, "images": [img_b64],
               "stream": False, "keep_alive": "1m",
               "options": {"num_predict": 400, "temperature": 0.2}}
    body = json.dumps(payload).encode()
    req = urllib.request.Request(f"{OLLAMA}/api/generate", body,
                                 {"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.load(r)
    return d.get("response", "").strip(), round(time.time() - t0, 1)


def unload(m):
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"{OLLAMA}/api/generate",
            json.dumps({"model": m, "keep_alive": 0}).encode(),
            {"Content-Type": "application/json"}), timeout=30)
    except Exception:
        pass


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    img_b64 = base64.b64encode(open(IMG, "rb").read()).decode()
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    md = [f"# VL-тест — {stamp}\n",
          "Очікую: 'Урок 5: Алгоритми', червоне коло + синій квадрат (2 фігури), 1991, def avg…\n"]
    for m in MODELS:
        print(f"=== {m} ===", flush=True)
        try:
            txt, sec = ask(m, img_b64)
            print(f"  {sec}s, {len(txt)} chars")
        except Exception as e:
            txt, sec = f"[FAIL: {e}]", 0
            print(f"  FAIL: {e}")
        md.append(f"\n## {m.split('/')[-1]} · {sec}s\n```\n{txt}\n```\n")
        unload(m)
        time.sleep(2)
    path = os.path.join(OUT_DIR, f"vl_{stamp}.md")
    open(path, "w").write("\n".join(md))
    print(f"\n✓ {path}")


if __name__ == "__main__":
    main()
