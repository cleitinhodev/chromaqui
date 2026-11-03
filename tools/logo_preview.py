"""Gera docs/logo_preview.png: o logotipo sobre fundo escuro e claro, e os tamanhos pequenos do ícone."""
import os
import sys

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(logo=os.path.join(ROOT, "assets", "logo.png"), out=os.path.join(ROOT, "docs", "logo_preview.png"),
         icons=os.path.join(ROOT, "assets", "icons")):
    lg = Image.open(logo).convert("RGBA")
    W, H = 1400, 700
    img = Image.new("RGBA", (W, H))
    halves = (((14, 20, 18), (230, 236, 232)), ((246, 250, 247), (40, 50, 44)))
    for i, (bg, fg) in enumerate(halves):
        x0 = i * W // 2
        ImageDraw.Draw(img).rectangle([x0, 0, x0 + W // 2, H], fill=bg)
        big = lg.resize((420, 420), Image.LANCZOS)
        img.alpha_composite(big, (x0 + (W // 2 - 420) // 2, 30))
        x = x0 + 40
        for n in (16, 24, 32, 48, 64, 128):
            p = os.path.join(icons, f"icon_{n}.png")
            ic = Image.open(p).convert("RGBA")
            y = 500 + (128 - n) // 2
            img.alpha_composite(ic, (x, y))
            ImageDraw.Draw(img).text((x, 640), f"{n}", fill=fg)
            x += n + 22
        # zoom 4x do 16 e 32 px (para conferir legibilidade)
        for n, xx in ((16, x0 + 510), (32, x0 + 600)):
            ic = Image.open(os.path.join(icons, f"icon_{n}.png")).convert("RGBA").resize((64, 64), Image.NEAREST)
            img.alpha_composite(ic, (xx, 532))
            ImageDraw.Draw(img).text((xx, 640), f"{n}px x{64 // n}", fill=fg)
    img.convert("RGB").save(out)
    print("ok:", out)


if __name__ == "__main__":
    main(*sys.argv[1:])
