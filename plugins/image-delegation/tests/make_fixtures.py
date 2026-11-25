#!/usr/bin/env python3
"""Create N PNGs with big labels IMG-01..IMG-N (default 10) for testing.

Usage: python make_fixtures.py [--n 10] [--out DIR]
Default DIR: <cwd>/.claude/tmp/fixtures (run from the project root). Prints only paths.
"""
import argparse
import os

from PIL import Image, ImageDraw, ImageFont

PROJECT = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

ap = argparse.ArgumentParser()
ap.add_argument("--n", type=int, default=10)
ap.add_argument("--out", default=os.path.join(PROJECT, ".claude", "tmp", "fixtures"))
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)

font = None
for name in ("arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "Arial.ttf", "Helvetica.ttc"):
    try:
        font = ImageFont.truetype(name, 150)
        break
    except OSError:
        pass
if font is None:
    try:
        font = ImageFont.load_default(size=150)  # Pillow >= 10.1
    except TypeError:
        font = ImageFont.load_default()

for i in range(1, a.n + 1):
    im = Image.new("RGB", (800, 400), "white")
    d = ImageDraw.Draw(im)
    label = f"IMG-{i:02d}"
    l, t, r, b = d.textbbox((0, 0), label, font=font)
    d.text(((800 - (r - l)) / 2 - l, (400 - (b - t)) / 2 - t), label, fill="black", font=font)
    p = os.path.abspath(os.path.join(a.out, f"img{i:02d}.png"))
    im.save(p)
    print(p)
