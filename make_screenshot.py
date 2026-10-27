#!/usr/bin/env python3
"""Render a REAL Sayflow run as a terminal-style PNG screenshot.

Runs examples/reminder-digest.say for real, captures its actual trace
output, and draws it into screenshot.png. Nothing is staged: delete the
PNG and re-run this script and you get the same image from a fresh run
(the sample data is reset afterwards so the repo stays pristine).
"""

import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"


def main():
    run = subprocess.run(
        [sys.executable, "sayflow.py", "examples/reminder-digest.say"],
        cwd=HERE, capture_output=True, text=True)
    if run.returncode != 0:
        print(run.stdout)
        print(run.stderr, file=sys.stderr)
        return 1
    lines = run.stdout.splitlines()
    # Keep the header, the first two reminders being sorted, and the end.
    keep = lines[:22] + ["   ..."] + lines[-14:]
    title = "$ python3 sayflow.py examples/reminder-digest.say"

    font = ImageFont.truetype(FONT, 22)
    font_bold = ImageFont.truetype(FONT_BOLD, 22)
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    width = 0
    for line in [title] + keep:
        width = max(width, probe.textlength(line, font=font))
    line_h = 32
    pad = 28
    img_w = int(width) + pad * 2
    img_h = line_h * (len(keep) + 2) + pad * 2
    img = Image.new("RGB", (img_w, img_h), (24, 26, 32))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([8, 8, img_w - 8, 52], radius=10, fill=(45, 48, 58))
    for i, color in enumerate(((237, 106, 94), (245, 191, 79), (98, 197, 102))):
        cx = 34 + i * 30
        draw.ellipse([cx, 24, cx + 16, 40], fill=color)
    draw.text((110, 18), "Sayflow — visible step trace", font=font_bold, fill=(220, 223, 230))
    y = 52 + pad // 2
    draw.text((pad, y), title, font=font_bold, fill=(140, 220, 160))
    y += line_h
    for line in keep:
        color = (150, 200, 255) if line.startswith("[") or line.startswith("==") else (225, 228, 235)
        if line.strip().startswith("..."):
            color = (130, 135, 150)
        draw.text((pad, y), line, font=font, fill=color)
        y += line_h
    out = os.path.join(HERE, "screenshot.png")
    img.save(out)
    print("Wrote {} ({}x{}) from a live run.".format(out, img_w, img_h))

    subprocess.run([sys.executable, "reset_samples.py"], cwd=HERE,
                   capture_output=True, text=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
