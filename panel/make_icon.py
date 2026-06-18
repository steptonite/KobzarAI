#!/usr/bin/env python3
"""Генерує іконку LocalAI: чіп + звукохвиля. Slate-фон, янтарний акцент.
Виводить app.icns + icon.png (для README/GitHub)."""
import math
import os
import subprocess
import tempfile
from PIL import Image, ImageDraw

OUT = os.path.dirname(os.path.abspath(__file__))
BG1 = (30, 41, 59)      # slate-800
BG2 = (15, 23, 42)      # slate-900
ACCENT = (245, 180, 70)  # янтар <80% sat
LINE = (148, 163, 184)  # slate-400


def rounded(sz):
    S = sz * 4  # supersample
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # вертикальний градієнт фону у скруглену плитку
    grad = Image.new("RGB", (1, S))
    for y in range(S):
        t = y / S
        grad.putpixel((0, y), tuple(int(BG1[i] + (BG2[i] - BG1[i]) * t) for i in range(3)))
    grad = grad.resize((S, S))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.225), fill=255)
    img.paste(grad, (0, 0), mask)

    # чіп: квадрат з ніжками
    m = int(S * 0.30)
    box = [m, m, S - m, S - m]
    d.rounded_rectangle(box, radius=int(S * 0.05), outline=LINE, width=max(2, S // 90))
    legs = 4
    span = box[2] - box[0]
    for i in range(legs):
        x = box[0] + span * (i + 1) / (legs + 1)
        ll = int(S * 0.045)
        d.line([(x, box[1] - ll), (x, box[1])], fill=LINE, width=max(2, S // 110))  # top
        d.line([(x, box[3]), (x, box[3] + ll)], fill=LINE, width=max(2, S // 110))  # bottom
        y = box[1] + span * (i + 1) / (legs + 1)
        d.line([(box[0] - ll, y), (box[0], y)], fill=LINE, width=max(2, S // 110))  # left
        d.line([(box[2], y), (box[2] + ll, y)], fill=LINE, width=max(2, S // 110))  # right

    # звукохвиля всередині чіпа (янтар)
    cx, cy = S // 2, S // 2
    w = box[2] - box[0]
    n = 7
    bw = w * 0.5 / n
    amps = [0.18, 0.34, 0.55, 0.78, 0.55, 0.34, 0.18]
    x0 = cx - (n * bw + (n - 1) * bw * 0.6) / 2
    for i, a in enumerate(amps):
        h = (box[3] - box[1]) * a / 2
        x = x0 + i * bw * 1.6
        d.rounded_rectangle([x, cy - h, x + bw, cy + h], radius=int(bw / 2), fill=ACCENT)

    return img.resize((sz, sz), Image.LANCZOS)


def main():
    png = rounded(1024)
    png.save(os.path.join(OUT, "icon.png"))
    with tempfile.TemporaryDirectory() as td:
        iconset = os.path.join(td, "app.iconset")
        os.makedirs(iconset)
        for sz in (16, 32, 64, 128, 256, 512, 1024):
            rounded(sz).save(os.path.join(iconset, f"icon_{sz}x{sz}.png"))
            rounded(sz * 2).save(os.path.join(iconset, f"icon_{sz}x{sz}@2x.png"))
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o",
                        os.path.join(OUT, "app.icns")], check=True)
    print("wrote", os.path.join(OUT, "app.icns"), "+ icon.png")


if __name__ == "__main__":
    main()
