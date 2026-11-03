"""Gera os ícones do Chromaqui! a partir de um PNG (de preferência quadrado, 1024 px, com transparência).

Uso:
    python tools/make_icon.py logo.png            # grava em assets/
    python tools/make_icon.py logo.png --out pasta

Saída:
    icon.ico      — multi-tamanho 16, 24, 32, 48, 64, 128, 256 (ícone do .exe e da janela)
    favicon.ico   — 16, 32, 48 (para o site)
    icon.png      — 512 px
    icons/icon_<N>.png — 16 … 1024 px
"""
from __future__ import annotations

import argparse
import os

import numpy as np
from PIL import Image, ImageFilter

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
FAVICON_SIZES = [16, 32, 48]
PNG_SIZES = [16, 24, 32, 48, 64, 128, 256, 512, 1024]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def square(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    w, h = img.size
    if w == h:
        return img
    s = max(w, h)
    out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    out.paste(img, ((s - w) // 2, (s - h) // 2))
    return out


def tight(img: Image.Image, margin=0.02) -> Image.Image:
    """Recorta a margem transparente (deixa só `margin`): aproveita melhor os 16/24 px."""
    box = img.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
    if not box:
        return img
    return _pad(img.crop(box), margin)


def _pad(img, margin):
    sq = square(img)
    s = sq.size[0]
    m = int(round(s * margin))
    out = Image.new("RGBA", (s + 2 * m, s + 2 * m), (0, 0, 0, 0))
    out.paste(sq, (m, m))
    return out


def resized(img, n, small_tune=True):
    """Reduz com Lanczos em alfa pré-multiplicado (sem halo escuro/claro nas bordas). Em 16–32 px
    recorta mais justo e aplica nitidez (cor e alfa) para o ícone continuar legível."""
    if small_tune and n <= 24:
        img = tight(img, 0.02)
    r = img.convert("RGBa").resize((n, n), Image.LANCZOS).convert("RGBA")
    if small_tune and n <= 32:
        rgb = r.convert("RGB").filter(ImageFilter.UnsharpMask(radius=0.8, percent=90, threshold=0))
        a = np.asarray(r)[..., 3].astype(np.float32) / 255
        a = np.clip((a - 0.5) * 1.35 + 0.5, 0, 1)
        r = Image.fromarray(np.dstack([np.asarray(rgb), (a * 255 + 0.5).astype(np.uint8)]), "RGBA")
    return r


def make(src: str, out_dir: str):
    os.makedirs(os.path.join(out_dir, "icons"), exist_ok=True)
    img = square(Image.open(src))
    imgs = {n: resized(img, n) for n in sorted(set(ICO_SIZES + FAVICON_SIZES + PNG_SIZES))}
    big = imgs[256]
    big.save(os.path.join(out_dir, "icon.ico"), format="ICO", sizes=[(n, n) for n in ICO_SIZES],
             append_images=[imgs[n] for n in ICO_SIZES if n != 256])
    imgs[48].save(os.path.join(out_dir, "favicon.ico"), format="ICO", sizes=[(n, n) for n in FAVICON_SIZES],
                  append_images=[imgs[n] for n in FAVICON_SIZES if n != 48])
    imgs[512].save(os.path.join(out_dir, "icon.png"))
    for n in PNG_SIZES:
        imgs[n].save(os.path.join(out_dir, "icons", f"icon_{n}.png"))
    return os.path.join(out_dir, "icon.ico")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("png")
    ap.add_argument("--out", default=os.path.join(ROOT, "assets"))
    a = ap.parse_args()
    ico = make(a.png, a.out)
    chk = Image.open(ico)
    print("ok:", ico, "tamanhos:", sorted(chk.info.get("sizes", [])))
