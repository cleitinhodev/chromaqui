"""Recorte da área exportada: matemática do recorte, recorte automático, equivalência com o quadro
inteiro e dimensões de saída em TODOS os formatos (inclui fundo composto).
Uso: python tests/test_crop.py [all]"""
import os, re, shutil, subprocess, sys
import cv2, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from chromaqui import core, exporters as ex
from PIL import Image

OUT = os.path.join(HERE, "_out")
VID = os.path.join(OUT, "teste_verde.mp4")
DEST = os.path.join(OUT, "recorte")


def test_math():
    W, H = 640, 360
    assert core.clamp_crop((-10, -5, 50, 40), W, H) == (0, 0, 50, 40)
    assert core.clamp_crop((600, 300, 100, 100), W, H) == (540, 260, 100, 100)
    assert core.clamp_crop((10, 10, 0, 0), W, H) == (10, 10, core.CROP_MIN, core.CROP_MIN)
    assert core.clamp_crop((100, 100, -40, -30), W, H) == (60, 70, 40, 30)        # arrasto "ao contrário"
    assert core.clamp_crop((0, 0, 5000, 5000), W, H) == (0, 0, W, H)
    assert core.normalize_crop(None, W, H) is None
    assert core.normalize_crop((0, 0, W, H), W, H) is None                          # quadro inteiro = sem recorte
    assert core.normalize_crop(("x", 0, 1, 1), W, H) is None
    assert core.normalize_crop((10, 20, 30, 40), W, H) == (10, 20, 30, 40)
    assert core.crop_fits((10, 20, 30, 40), W, H) and not core.crop_fits((620, 0, 30, 40), W, H)
    assert not core.crop_fits((0, 0, 1, 1), W, H) and not core.crop_fits(None, W, H)
    # pares: cresce para a direita/baixo; na borda cresce para a esquerda/cima; sem espaço, encolhe
    assert core.even_crop((10, 10, 31, 41), W, H) == (10, 10, 32, 42)
    assert core.even_crop((609, 319, 31, 41), W, H) == (608, 318, 32, 42)
    assert core.even_crop((0, 0, 639, 359), 639, 359) == (0, 0, 638, 358)
    # geometria de saída (escala depois do recorte; vídeo sempre par)
    g = lambda **k: core.export_geometry(W, H, core.ExportOptions(**k))
    assert g() == (None, 640, 360)
    assert g(scale=0.5) == (None, 320, 180)
    assert g(crop=(10, 10, 101, 51)) == ((10, 10, 101, 51), 101, 51)
    assert g(crop=(10, 10, 101, 51), scale=2.0) == ((10, 10, 101, 51), 202, 102)
    assert g(crop=(10, 10, 101, 51), even=True) == ((10, 10, 102, 52), 102, 52)
    for fmt in ("webm", "prores"):
        c, ow, oh = g(crop=(10, 10, 101, 51), fmt=fmt, scale=0.5)
        assert ow % 2 == 0 and oh % 2 == 0, (fmt, ow, oh)
    assert g(crop=(0, 0, W, H), fmt="png") == (None, 640, 360)
    print("CROP MATH OK")


def test_equivalence(video):
    """O recorte processa só a região (+ contexto) e tem de dar o mesmo resultado do quadro inteiro."""
    v = core.Video(video); f = v.read(10); W, H = v.width, v.height; v.release()
    p = core.KeyParams(); p.values["crop_top"] = 10; p.values["crop_left"] = 5       # garbage matte em %
    worst = 0.0
    for s in (1.0, 2.0, 0.5):
        c0, a0 = core.key_for_export(f, p, s, None)
        for crop in ((W // 5 + 1, H // 6 + 1, W // 2 + 1, H // 2 + 1), (0, 0, W // 2, H - 10), (W - 101, H - 77, 101, 77)):
            cr, ow, oh = core.export_geometry(W, H, core.ExportOptions(crop=crop, scale=s))
            c1, a1 = core.key_for_export(f, p, s, cr, (ow, oh))
            assert a1.shape == (oh, ow) and c1.shape == (oh, ow, 3), (a1.shape, ow, oh)
            bx, by, _, _ = core.crop_box_out(cr, W, H, s, ow, oh)
            ref = a0[by:by + oh, bx:bx + ow]
            d = np.abs(ref - a1) * 255
            assert d.mean() < 0.05 and np.percentile(d, 99.9) < 2.0, (s, crop, d.mean(), d.max())
            worst = max(worst, float(d.max()))
    print(f"CROP EQUIVALENCE OK ({os.path.basename(video)}: alfa igual ao quadro inteiro; maior diferença {worst:.2f}/255)")


def test_auto(video):
    p = core.KeyParams()
    r = core.auto_crop(video, p, samples=30, margin=0)
    # objetos do vídeo de teste: bola (raio 70) de x=-10 a x=553, y=110..250; retângulo até y=330; texto em (20, 50)
    x, y, w, h = r
    assert x == 0 and y <= 25 and x + w >= 550 and y + h >= 328, r
    assert x + w < 600 and y + h < 345, f"recorte automático pegou fundo: {r}"
    r8 = core.auto_crop(video, p, samples=30, margin=8)
    assert r8[1] == max(0, y - 8) and r8[1] + r8[3] == min(360, y + h + 8), (r, r8)
    p2 = core.KeyParams(); p2.enabled = False
    assert core.auto_crop(video, p2) == (0, 0, 640, 360)
    # fundo verde puro: nada encontrado
    blank = os.path.join(OUT, "so_fundo.mp4")
    vw = cv2.VideoWriter(blank, cv2.VideoWriter_fourcc(*"mp4v"), 24, (320, 240))
    for _ in range(6):
        vw.write(np.full((240, 320, 3), (64, 177, 0), np.uint8))
    vw.release()
    assert core.auto_crop(blank, p) is None
    print(f"AUTO CROP OK {r} (margem 8: {r8}; fundo puro: nada)")


def _ffmpeg_size(path):
    exe = ex.ffmpeg_exe()
    r = subprocess.run([exe, "-hide_banner", "-i", path], capture_output=True, text=True, errors="replace")
    m = re.search(r"Video: .*?, (\d{2,5})x(\d{2,5})", r.stderr)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _size(key, out):
    f = ex.FORMAT_BY_KEY[key]
    if not f.single_file:
        files = sorted(os.listdir(out))
        im = Image.open(os.path.join(out, files[0])); return im.size, len(files), im.mode
    if key == "sheet":   # sprite sheet: tamanho de cada quadro (sourceSize) no JSON
        import json
        d = json.load(open(os.path.splitext(out)[0] + ".json", encoding="utf-8"))
        fr = list(d["frames"].values())
        ss = fr[0]["sourceSize"]
        return (ss["w"], ss["h"]), len(fr), Image.open(out).mode
    if key in ("gif", "apng", "webp"):
        im = Image.open(out); return im.size, getattr(im, "n_frames", 1), im.mode
    return _ffmpeg_size(out), None, None


def test_formats(video=VID):
    shutil.rmtree(DEST, ignore_errors=True); os.makedirs(DEST)
    P = core.KeyParams()
    crop = (121, 33, 301, 255)                 # ímpar de propósito
    res = []
    for scale in (1.0, 2.0, 0.5):
        for f in ex.FORMATS:
            o = core.ExportOptions(start=0, end=5, step=1, fmt=f.key, scale=scale, crop=crop)
            _, ow, oh = core.export_geometry(640, 360, o)
            out = os.path.join(DEST, f"{f.key}_{scale}" + (f.ext if f.single_file else ""))
            r = ex.export(video, out, P, o)
            assert r["count"] == 6, (f.key, r)
            size, n, mode = _size(f.key, r["output"])
            assert size == (ow, oh), (f.key, scale, size, (ow, oh))
            if f.key in ("webm", "prores"):
                assert ow % 2 == 0 and oh % 2 == 0
            if n is not None:
                assert n == 6, (f.key, n)
            res.append(f"{f.key}@{scale}={ow}x{oh}")
    print("CROP EXPORT OK:", ", ".join(res))


def test_background(video=VID):
    """Fundo incluído: encaixado no quadro inteiro e recortado na mesma área (igual à prévia)."""
    bgp = os.path.join(OUT, "fundo_recorte.png")
    yy, xx = np.mgrid[0:180, 0:320]
    grad = np.dstack([xx * 255 // 319, yy * 255 // 179, np.full_like(xx, 200)]).astype(np.uint8)
    cv2.imwrite(bgp, grad)
    bg = core.Background(); bg.load(bgp); bg.mode = "stretch"
    crop = (200, 100, 120, 80)
    for scale in (1.0, 2.0):
        o = core.ExportOptions(start=0, end=0, fmt="png", crop=crop, include_bg=True, scale=scale)
        out = os.path.join(DEST, f"com_fundo_{scale}")
        ex.export(video, out, core.KeyParams(), o, background=bg)
        img = cv2.imdecode(np.fromfile(os.path.join(out, "frame_00001.png"), np.uint8), cv2.IMREAD_UNCHANGED)
        full = bg.frame(0, int(640 * scale), int(360 * scale))
        ref = full[int(100 * scale):int(180 * scale), int(200 * scale):int(320 * scale)]
        assert img.shape[:2] == ref.shape[:2] and img[..., 3].min() == 255, img.shape
        # canto superior esquerdo do recorte é fundo verde -> deve mostrar o fundo naquele ponto
        assert np.abs(img[2, 2, :3].astype(int) - ref[2, 2].astype(int)).max() < 6, (img[2, 2], ref[2, 2])
    bg.clear()
    print("CROP + FUNDO OK (fundo recortado na mesma área da prévia)")


if __name__ == "__main__":
    if not os.path.exists(VID):
        import test_core; test_core.make_video(VID)
    test_math()
    test_equivalence(VID)
    loiro = os.path.join(OUT, "teste_cabelo_loiro.mp4")
    if os.path.exists(loiro):
        test_equivalence(loiro)
    test_auto(VID)
    test_formats()
    test_background()
    print("TEST CROP OK")
