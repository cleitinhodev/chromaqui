"""Prepara o logotipo para os ícones: remove o fundo, recorta justo e centraliza num quadrado.

    python tools/prepare_logo.py original.png assets/logo.png [--size 1024] [--margin 0.06]

* Se o PNG já tem transparência, só limpa o "ruído" de alfa quase zero ligado às bordas.
* Se o fundo é branco/quase branco, remove SÓ o branco conectado às bordas da imagem
  (preenchimento a partir das bordas, não um recorte global de branco): os quadradinhos
  brancos do logo e suas sombras/contornos cinza são preservados, e a borda fica suave
  (alfa proporcional à distância do branco, com a cor "des-misturada" do branco).
"""
from __future__ import annotations

import argparse

import cv2
import numpy as np
from PIL import Image


def _border_connected(mask: np.ndarray) -> np.ndarray:
    """Componentes de `mask` que tocam a borda da imagem."""
    n, lab = cv2.connectedComponents(mask.astype(np.uint8), connectivity=4)
    edge = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    edge = edge[edge != 0]
    return np.isin(lab, edge)


def remove_background(rgba: np.ndarray, lo=6, hi=40) -> np.ndarray:
    rgb = rgba[..., :3].astype(np.float32)
    a = rgba[..., 3].astype(np.float32)
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    if np.median(border) < 16:                     # já transparente: limpa só o ruído de fundo
        bg = _border_connected(a <= 8)
        a[bg] = 0
        a[a >= 250] = 255
        out = np.dstack([rgb, a])
    else:                                          # fundo branco: flood fill a partir das bordas
        d = (255.0 - rgb).max(axis=2)              # distância do branco
        region = _border_connected(d <= lo)        # núcleo: branco "puro" ligado às bordas
        # cresce para sombras/antisserrilhado só enquanto a distância do branco NÃO diminui:
        # atravessar o contorno de um quadradinho branco exigiria "descer" de novo -> bloqueado
        k = np.ones((3, 3), np.uint8)
        for _ in range(64):
            dmin = cv2.erode(np.where(region, d, 1e6).astype(np.float32), k)
            grow = (~region) & (d <= hi) & (d >= dmin - 1.0) & (dmin < 1e6)
            if not grow.any():
                break
            region |= grow
        alpha = np.ones_like(d)
        t = np.clip((d - lo) / (hi - lo), 0, 1)
        alpha[region] = (t * t * (3 - 2 * t))[region]
        alpha = cv2.GaussianBlur(alpha, (0, 0), 0.6)
        alpha[~region] = 1.0
        al = np.maximum(alpha, 1e-3)[..., None]
        col = np.clip((rgb - (1 - al) * 255.0) / al, 0, 255)   # tira a mistura com o branco
        out = np.dstack([col, alpha * 255.0])
    out[out[..., 3] == 0, :3] = 0
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def crop_square(rgba: np.ndarray, size=1024, margin=0.06) -> Image.Image:
    ys, xs = np.where(rgba[..., 3] > 8)
    crop = rgba[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = crop.shape[:2]
    s = int(round(max(w, h) * (1 + 2 * margin)))
    canvas = np.zeros((s, s, 4), np.uint8)
    y0, x0 = (s - h) // 2, (s - w) // 2
    canvas[y0:y0 + h, x0:x0 + w] = crop
    img = Image.fromarray(canvas, "RGBA").convert("RGBa")          # pré-multiplicado: sem halo
    return img.resize((size, size), Image.LANCZOS).convert("RGBA")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--size", type=int, default=1024)
    ap.add_argument("--margin", type=float, default=0.06)
    a = ap.parse_args()
    src = np.asarray(Image.open(a.src).convert("RGBA"))
    out = crop_square(remove_background(src), a.size, a.margin)
    out.save(a.dst, optimize=True)
    print("ok:", a.dst, out.size)
