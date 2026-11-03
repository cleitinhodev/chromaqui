"""Ícone provisório "C!" na cor de destaque do tema (até chegar o logo oficial)."""
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from chromaqui.theme import ACCENT, _hls, _rgb  # noqa: E402

FONTS = ["C:/Windows/Fonts/segoeuib.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]


def font(size):
    for f in FONTS:
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def make(path, n=1024, accent=ACCENT):
    hi, lo = _rgb(_hls(accent, dl=0.12)), _rgb(_hls(accent, dl=-0.22))
    # fundo: quadrado arredondado com degradê diagonal
    grad = Image.new("RGBA", (n, n))
    px = grad.load()
    for y in range(n):
        for x in range(n):
            t = (x + y) / (2 * n)
            px[x, y] = tuple(int(hi[i] + (lo[i] - hi[i]) * t) for i in range(3)) + (255,)
    mask = Image.new("L", (n, n), 0)
    m = int(n * 0.06)
    ImageDraw.Draw(mask).rounded_rectangle((m, m, n - m, n - m), radius=int(n * 0.22), fill=255)
    out = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    out.paste(grad, (0, 0), mask)
    # brilho superior
    gloss = Image.new("L", (n, n), 0)
    ImageDraw.Draw(gloss).ellipse((-n * 0.2, -n * 0.75, n * 1.2, n * 0.42), fill=60)
    gloss = Image.composite(gloss, Image.new("L", (n, n), 0), mask)
    out = Image.alpha_composite(out, Image.merge("RGBA", [Image.new("L", (n, n), 255)] * 3 + [gloss]))
    # texto "C!" com brilho neon
    f = font(int(n * 0.56))
    txt = "C!"
    d = ImageDraw.Draw(out)
    bb = d.textbbox((0, 0), txt, font=f)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    pos = ((n - tw) / 2 - bb[0], (n - th) / 2 - bb[1] - n * 0.01)
    glow = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    ImageDraw.Draw(glow).text(pos, txt, font=f, fill=(255, 255, 255, 200))
    glow = glow.filter(ImageFilter.GaussianBlur(n * 0.025))
    out = Image.alpha_composite(out, glow)
    shadow = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text((pos[0] + n * 0.012, pos[1] + n * 0.018), txt, font=f, fill=lo + (170,))
    out = Image.alpha_composite(out, shadow.filter(ImageFilter.GaussianBlur(n * 0.008)))
    ImageDraw.Draw(out).text(pos, txt, font=f, fill=(255, 255, 255, 255))
    out.save(path)
    return path


if __name__ == "__main__":
    p = make(os.path.join(ROOT, "assets", "logo_placeholder.png"))
    from make_icon import make as make_icons  # noqa: E402
    print(make_icons(p, os.path.join(ROOT, "assets")))
