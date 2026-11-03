"""Mede e mostra o efeito da Colorização de bordas (sem x com) nos vídeos de cabelo.
Gera ../comparacao_colorizacao.png (recortes ampliados 4x sobre fundo escuro) e imprime métricas."""
import os, sys, time
import cv2, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
from chromaqui import core as chroma

OUT = os.path.join(HERE, "_out")
VIDS = [("Cabelo castanho", "teste_bordas_suaves.mp4", "alpha_gt.npz"),
        ("Cabelo loiro", "teste_cabelo_loiro.mp4", "alpha_gt_loiro.npz")]
if not all(os.path.exists(os.path.join(OUT, v)) for _, v, _ in VIDS):
    import make_soft_video; make_soft_video.main()
FR = 12


def load(vid, gtn):
    cap = cv2.VideoCapture(os.path.join(OUT, vid)); cap.set(cv2.CAP_PROP_POS_FRAMES, FR)
    ok, frame = cap.read(); cap.release()
    g = np.load(os.path.join(OUT, gtn))
    key = tuple(int(v) for v in frame[20:60, 20:60].reshape(-1, 3).mean(0)[::-1])
    return frame, g[f"a{FR}"], g["fg12"], key


def metrics(bgra, gt, fg, band):
    a = bgra[..., 3] / 255.0
    c = bgra[..., :3].astype(np.float32)
    g = np.maximum(c[..., 1] - np.maximum(c[..., 0], c[..., 2]), 0)
    green = (g * a)[band].sum() / max(a[band].sum(), 1e-6)
    m = band & (gt > 0.15) & (a > 0.15)
    w = np.minimum(a, gt)[m]
    err = (np.abs(c - fg).mean(-1)[m] * w).sum() / w.sum()   # erro de cor vs. cor real do objeto
    return green, err


def params(key, cw, spill=50):
    p = chroma.KeyParams(key)
    p.values.update(cw_enable=cw, spill=spill)
    return p


REG = {"Cabelo (fios finos)": (330, 70, 160, 90), "Borda da pele (rosto)": (430, 215, 160, 90)}
rows, lines = [], []
for name, vid, gtn in VIDS:
    frame, gt, fg, key = load(vid, gtn)
    band = cv2.dilate(((gt > 0.02) & (gt < 0.98)).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    res = {}
    for cw in (0, 1):
        for sp in (50, 0):
            t = time.time(); b = chroma.key_frame(frame, params(key, cw, sp)); dt = time.time() - t
            res[(cw, sp)] = (b, metrics(b, gt, fg, band), dt)
    (g0, e0), (g1, e1) = res[(0, 50)][1], res[(1, 50)][1]
    (g0s, _), (g1s, _) = res[(0, 0)][1], res[(1, 0)][1]
    lines += [f"{name}: verde residual na borda (0-255, pond. alfa)  sem {g0:.2f} -> com {g1:.2f}  ({(1 - g1 / g0) * 100:.0f}% menos)",
              f"{name}:   ...sem supressao de spill:                    sem {g0s:.2f} -> com {g1s:.2f}  ({(1 - g1s / g0s) * 100:.0f}% menos)",
              f"{name}: erro de cor vs. cor real do objeto (0-255)     sem {e0:.2f} -> com {e1:.2f}",
              f"{name}: tempo por quadro 960x540  sem {res[(0, 50)][2]:.2f}s  com {res[(1, 50)][2]:.2f}s"]
    for rname, (x, y, w, h) in REG.items():
        if name == "Cabelo loiro" and rname.startswith("Borda"):
            continue
        tiles = []
        for cw in (0, 1):
            b = res[(cw, 50)][0][y:y + h, x:x + w]
            a = b[..., 3:4] / 255.0
            comp = (b[..., :3] * a + np.array([115, 115, 115]) * (1 - a)).astype(np.uint8)
            tiles.append(cv2.resize(comp, (w * 4, h * 4), interpolation=cv2.INTER_NEAREST))
        rows.append((f"{name} - {rname}" if rname.startswith("Cabelo") else rname, tiles))

font = cv2.FONT_HERSHEY_SIMPLEX
TW = rows[0][1][0].shape[1]; W = TW * 2 + 10
parts = []
title = np.full((60, W, 3), 255, np.uint8)
cv2.putText(title, "SEM colorizacao de bordas", (60, 40), font, 0.9, (0, 0, 180), 2, cv2.LINE_AA)
cv2.putText(title, "COM colorizacao de bordas", (TW + 70, 40), font, 0.9, (0, 130, 0), 2, cv2.LINE_AA)
parts.append(title)
for rn, (t0, t1) in rows:
    head = np.full((34, W, 3), 255, np.uint8)
    cv2.putText(head, f"{rn} - zoom 4x, fundo cinza", (8, 24), font, 0.65, (30, 30, 30), 2, cv2.LINE_AA)
    parts += [head, np.hstack([t0, np.full((t0.shape[0], 10, 3), 255, np.uint8), t1])]
foot = np.full((20 + 28 * len(lines), W, 3), 255, np.uint8)
for i, l in enumerate(lines):
    cv2.putText(foot, l, (10, 26 + 28 * i), font, 0.5, (30, 30, 30), 1, cv2.LINE_AA)
parts.append(foot)
img = np.vstack(parts)
dst = os.path.join(ROOT, "comparacao_colorizacao.png")
cv2.imwrite(dst, img)
print("\n".join(lines))
print("salvo", dst, img.shape)
