#!/usr/bin/env python3
"""Синтетичне тестове зображення з ВІДОМИМ вмістом — щоб об'єктивно оцінити VL.
Містить: укр-заголовок (кирилиця-OCR), 2 фігури+кольори, число, рядок коду."""
from PIL import Image, ImageDraw, ImageFont
import os

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 760, 480
img = Image.new("RGB", (W, H), "#f4f4f0")
d = ImageDraw.Draw(img)


def font(sz):
    for p in ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
              "/System/Library/Fonts/Helvetica.ttc",
              "/Library/Fonts/Arial.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz)
            except Exception:
                pass
    return ImageFont.load_default()


# заголовок (кирилиця)
d.text((30, 24), "Урок 5: Алгоритми", fill="#111", font=font(40))
# фігури
d.ellipse((40, 110, 160, 230), fill="#c0392b")            # червоне коло
d.rectangle((220, 120, 360, 220), fill="#2667c0")          # синій квадрат
# число
d.text((430, 140), "1991", fill="#111", font=font(64))
# рядок коду (моноширинний-ish)
d.text((40, 290), "def avg(nums):", fill="#0a7d3a", font=font(34))
d.text((40, 340), "    return sum(nums) / len(nums)", fill="#444", font=font(28))
# підпис унизу
d.text((40, 420), "Тест зору · 3 фігури немає, лише 2", fill="#888", font=font(22))

out = os.path.join(HERE, "vl_test.png")
img.save(out)
print("saved", out)
