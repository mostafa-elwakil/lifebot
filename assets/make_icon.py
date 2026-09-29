"""Generate Rakez app icons (ICO for Windows, PNG for Linux) from the brand theme."""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent
BG = (26, 27, 38, 255)
BLUE = (122, 162, 247, 255)
PURPLE = (187, 154, 247, 255)
GREEN = (158, 206, 106, 255)
RED = (255, 107, 107, 255)
WHITE = (255, 255, 255, 255)
HEAD = (36, 40, 59, 255)


def draw(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 256  # scale factor vs the SVG viewBox

    def R(v):
        return int(v * s)

    # background
    d.rounded_rectangle([R(8), R(8), R(248), R(248)], radius=R(56), fill=BG,
                        outline=BLUE, width=max(1, R(6)))
    # antenna
    d.line([R(128), R(52), R(128), R(30)], fill=PURPLE, width=max(1, R(8)))
    d.ellipse([R(118), R(14), R(138), R(34)], fill=PURPLE)
    # ears
    d.rounded_rectangle([R(34), R(118), R(52), R(162)], radius=R(9), fill=BLUE)
    d.rounded_rectangle([R(204), R(118), R(222), R(162)], radius=R(9), fill=BLUE)
    # head
    d.rounded_rectangle([R(52), R(62), R(204), R(194)], radius=R(40), fill=HEAD,
                        outline=BLUE, width=max(1, R(6)))
    # normal eye
    d.ellipse([R(88), R(108), R(116), R(136)], fill=GREEN)
    # focus eye: red ring + green ring + clock hands
    d.ellipse([R(134), R(98), R(182), R(146)], outline=RED, width=max(1, R(6)))
    d.ellipse([R(140), R(104), R(176), R(140)], outline=GREEN, width=max(1, R(3)))
    d.line([R(158), R(122), R(158), R(108)], fill=WHITE, width=max(1, R(5)))
    d.line([R(158), R(122), R(168), R(126)], fill=WHITE, width=max(1, R(5)))
    d.ellipse([R(154), R(118), R(162), R(126)], fill=WHITE)
    # smile
    d.arc([R(100), R(140), R(156), R(176)], start=25, end=155, fill=BLUE,
          width=max(1, R(7)))
    return img


def main():
    base = draw(512)
    base.save(OUT / "icon-512.png")
    base.resize((256, 256), Image.LANCZOS).save(OUT / "icon-256.png")
    base.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                       (64, 64), (128, 128), (256, 256)])
    print("icons written:", sorted(p.name for p in OUT.glob("icon*")))


if __name__ == "__main__":
    main()
