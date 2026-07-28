# -*- coding: utf-8 -*-
"""Generate cover image for Codex guide page.

Output: workbuddy-hub/assets/covers/codex-cover.png
"""
from PIL import Image, ImageDraw, ImageFont
import os

W, H = 1200, 630
BG = (15, 23, 36)          # deep navy
ACCENT = (116, 185, 255)   # bright blue
SOFT = (45, 62, 90)        # muted blue
WHITE = (255, 255, 255)
MUTED = (160, 180, 205)

FONT_REG = "C:/Windows/Fonts/msyh.ttc"
FONT_BD = "C:/Windows/Fonts/msyhbd.ttc"


def font(size, bold=False):
    p = FONT_BD if bold else FONT_REG
    if not os.path.exists(p):
        p = FONT_REG
    return ImageFont.truetype(p, size)


img = Image.new("RGBA", (W, H), BG + (255,))
draw = ImageDraw.Draw(img, "RGBA")

# Background grid lines (subtle)
for i in range(0, W, 60):
    draw.line([(i, 0), (i, H)], fill=SOFT + (30,), width=1)
for i in range(0, H, 60):
    draw.line([(0, i), (W, i)], fill=SOFT + (30,), width=1)

# Decorative code-like blocks on the right
blocks = [
    (780, 110, 360, 28, ACCENT + (40,)),
    (780, 150, 260, 18, SOFT + (80,)),
    (780, 180, 320, 18, SOFT + (80,)),
    (780, 210, 200, 18, SOFT + (80,)),
    (780, 250, 360, 28, ACCENT + (35,)),
    (780, 290, 280, 18, SOFT + (80,)),
    (780, 320, 180, 18, SOFT + (80,)),
    (780, 360, 360, 28, ACCENT + (30,)),
]
for x, y, w, h, fill in blocks:
    draw.rounded_rectangle([x, y, x + w, y + h], radius=6, fill=fill)

# Accent glow circle top-right
draw.ellipse([W - 260, -240, W + 160, 180], fill=ACCENT + (18,))

# Top brand bar
bar_w = draw.textlength("Codex", font=font(30, True))
draw.rounded_rectangle([72, 88, 84 + bar_w + 24, 120], radius=6, fill=ACCENT + (30,), outline=ACCENT + (120,), width=1)
draw.text((96, 88), "Codex", font=font(30, True), fill=ACCENT)

# Main title
draw.text((72, 200), "把自然语言", font=font(66, True), fill=WHITE)
draw.text((72, 278), "变成可运行的代码", font=font(66, True), fill=ACCENT)

# Sub line
draw.text((72, 380), "云端代码智能体 · 场景 · 流程 · 提示词模板 · 验收清单", font=font(26, True), fill=MUTED)

# Bottom tags
tags = ["数据清洗", "报表生成", "接口调试", "脚本自动化"]
f_tag = font(22, True)
box_h = 48
x0, y0 = 72, 480
gap = 14
for i, t in enumerate(tags):
    tw = draw.textlength(t, font=f_tag)
    box_w = tw + 36
    x = x0 + i * (box_w + gap)
    draw.rounded_rectangle([x, y0, x + box_w, y0 + box_h], radius=12,
                           fill=ACCENT + (20,), outline=ACCENT + (160,), width=2)
    draw.text((x + 18, y0 + 10), t, font=f_tag, fill=WHITE)

out_dir = os.path.join(os.path.dirname(__file__), "workbuddy-hub", "assets", "covers")
os.makedirs(out_dir, exist_ok=True)
out = os.path.join(out_dir, "codex-cover.png")
img.convert("RGB").save(out, "PNG", optimize=True)
print("saved:", out, "size:", os.path.getsize(out), "bytes")
