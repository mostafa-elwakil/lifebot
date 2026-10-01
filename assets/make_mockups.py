"""Render 3 floating-widget redesign mockups for the user to choose from."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
W, H = 560, 220
BG = (18, 19, 30, 255)
CARD = (26, 27, 38, 255)
BLUE = (122, 162, 247)
GREEN = (158, 206, 106)
PURPLE = (187, 154, 247)
RED = (255, 107, 107)
GREY = (86, 95, 137)
WHITE = (192, 202, 245)


def base(title):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((16, 8), title, fill=WHITE)
    return img, d


def card(d, box, outline, width=3):
    d.rounded_rectangle(box, radius=28, fill=CARD, outline=outline, width=width)


def mock_a():
    """A — Glass Pill: minimal pill, big time, thin progress line."""
    img, d = base("A — Glass Pill (minimal)")
    card(d, [16, 44, 544, 204], BLUE)
    d.ellipse([36, 70, 150, 178], outline=BLUE, width=5)  # ring
    d.text((66, 108), "62%", fill=WHITE)
    d.text((175, 70), "Core System Architecture", fill=BLUE)
    d.text((175, 95), "DEEP WORK", fill=PURPLE)
    d.text((175, 118), "25:00", fill=GREEN)
    for i, x in enumerate([380, 430, 480]):
        d.ellipse([x, 120, x + 40, 160], outline=BLUE, width=3)
    d.line([36, 190, 150 + int((524 - 150) * 0.62), 190], fill=GREEN, width=5)
    img.save(OUT / "mockup_a_pill.png")


def mock_b():
    """B — Neon Card: header + huge time + gradient progress bar."""
    img, d = base("B — Neon Card (expressive)")
    card(d, [16, 44, 544, 204], GREEN)
    d.rectangle([36, 60, 130, 84], fill=GREEN)
    d.text((44, 63), "FOCUS", fill=(26, 27, 38))
    d.text((150, 60), "Core System Architecture", fill=WHITE)
    d.text((36, 95), "24:59", fill=GREEN)
    d.rounded_rectangle([36, 150, 524, 164], radius=7, fill=(40, 44, 64))
    d.rounded_rectangle([36, 150, 36 + int(488 * 0.35), 164], radius=7, fill=GREEN)
    for i, x in enumerate([380, 430, 480]):
        d.rounded_rectangle([x, 100, x + 40, 140], radius=10, outline=GREEN, width=3)
    img.save(OUT / "mockup_b_neon.png")


def mock_c():
    """C — Split Flip: left time block, right controls grid."""
    img, d = base("C — Split Flip (controls-first)")
    d.rounded_rectangle([16, 44, 250, 204], radius=28, fill=(36, 40, 59), outline=PURPLE, width=3)
    d.text((40, 80), "25:00", fill=PURPLE)
    d.text((40, 130), "FOCUS 62%", fill=GREY)
    d.rounded_rectangle([266, 44, 544, 204], radius=28, fill=CARD, outline=PURPLE, width=3)
    d.text((286, 60), "Core System Architecture", fill=WHITE)
    d.text((286, 85), "Deep Work", fill=PURPLE)
    for i, (x, y) in enumerate([(286, 115), (336, 115), (386, 115), (436, 115)]):
        d.rounded_rectangle([x, y, x + 44, y + 44], radius=12, outline=PURPLE, width=3)
    img.save(OUT / "mockup_c_split.png")


mock_a()
mock_b()
mock_c()
print("mockups written")
