# -*- coding: utf-8 -*-
"""Generate cover image for AI tool upgrade map page.

Output: workbuddy-hub/assets/covers/ai-upgrade-cover.png
"""
from PIL import Image, ImageDraw, ImageFont
import os

W, H = 1200, 630
BG = (30, 36, 40)          # warm dark
ORANGE = (198, 110, 53)    # WorkBuddy orange
GOLD = (242, 173, 98)      # light gold
BLUE = (111, 143, 169)     # soft blue
WHITE = (255, 255, 255)
MUTED = (180, 175, 165)

FONT_REG = "C:/Windows/Fonts/msyh.ttc"
FONT_BD = "C:/Windows/Fonts/msyhbd.ttc"


def font(size, bold=False):
    p = FONT_BD if bold else FONT_REG
    if not os.path.exists(p):
        p = FONT_REG
    return ImageFont.truetype(p, size)


img = Image.new("RGBA", (W, H), BG + (255,))
draw = ImageDraw.Draw(img, "RGBA")

# Background: three large translucent circles representing three eras
draw.ellipse([80, 180, 340, 440], fill=BLUE + (25,))
draw.ellipse([360, 160, 680, 480], fill=ORANGE + (22,))
draw.ellipse([760, 140, 1160, 540], fill=GOLD + (18,))

# Connecting arrow line between eras
arrow_y = 390
draw.line([(260, arrow_y), (940, arrow_y)], fill=MUTED + (60,), width=4)
for x in [260, 520, 800]:
    draw.ellipse([x - 10, arrow_y - 10, x + 10, arrow_y + 10], fill=WHITE + (50,), outline=WHITE + (120,), width=2)
# arrow head
draw.polygon([(940, arrow_y), (920, arrow_y - 10), (920, arrow_y + 10)], fill=MUTED + (80,))

# Era labels below circles
labels = [("Chatbot", "2022-2023"), ("OpenClaw", "2024-2025"), ("百花齐放", "2025-2026")]
positions = [170, 470, 830]
for (label, year), x in zip(labels, positions):
    tw = draw.textlength(label, font=font(24, True))
    draw.text((x - tw / 2, 420), label, font=font(24, True), fill=WHITE)
    tw2 = draw.textlength(year, font=font(16, True))
    draw.text((x - tw2 / 2, 452), year, font=font(16, True), fill=MUTED)

# Top brand bar
draw.rounded_rectangle([72, 88, 118, 120], radius=6, fill=ORANGE + (255,))
draw.text((134, 88), "AI Tool Landscape 2026", font=font(28, True), fill=WHITE)

# Main title
draw.text((72, 150), "从 Chatbot 到 OpenClaw", font=font(56, True), fill=WHITE)
draw.text((72, 222), "再到百花齐放的工具生态", font=font(56, True), fill=ORANGE)

# Sub line
draw.text((72, 310), "三代工具 · 能力雷达 · 选型矩阵 · 岗位起步建议", font=font(26, True), fill=MUTED)

out_dir = os.path.join(os.path.dirname(__file__), "workbuddy-hub", "assets", "covers")
os.makedirs(out_dir, exist_ok=True)
out = os.path.join(out_dir, "ai-upgrade-cover.png")
img.convert("RGB").save(out, "PNG", optimize=True)
print("saved:", out, "size:", os.path.getsize(out), "bytes")
