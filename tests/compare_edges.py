"""Compara a versão anterior do keyer com a nova no vídeo de bordas suaves.
Gera ../comparacao_bordas.png (recortes ampliados 4x sobre xadrez) e imprime métricas."""
import os, sys, importlib.util
import cv2, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from chromaqui import core as chroma
spec = importlib.util.spec_from_file_location("chroma_antigo", os.path.join(HERE, "chroma_antigo.py"))
old = importlib.util.module_from_spec(spec); sys.modules["chroma_antigo"] = old; spec.loader.exec_module(old)

OUT = os.path.join(HERE, "_out")
VID = os.path.join(OUT, "teste_bordas_suaves.mp4")
if not os.path.exists(VID):
    import make_soft_video; make_soft_video.main()
FR = 12
gt = np.load(os.path.join(OUT, "alpha_gt.npz"))[f"a{FR}"]
cap = cv2.VideoCapture(VID); cap.set(cv2.CAP_PROP_POS_FRAMES, FR); ok, frame = cap.read(); cap.release()
key = tuple(int(v) for v in frame[20:60, 20:60].reshape(-1, 3).mean(0)[::-1])  # como "clicar no fundo"

bgra_old = old.key_frame(frame, old.KeyParams(key))
bgra_new = chroma.key_frame(frame, chroma.KeyParams(key))
a_old = bgra_old[..., 3] / 255.0
a_new = bgra_new[..., 3] / 255.0

band = cv2.dilate(((gt > 0.02) & (gt < 0.98)).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
def m(a, bgra):
    inter = ((a > 0.02) & (a < 0.98))[band].mean() * 100
    mae = np.abs(a - gt)[band].mean()
    hair = np.abs(a - gt)[60:240, 240:540][band[60:240, 240:540]].mean()
    blur = np.abs(a - gt)[60:180, 700:900][band[60:180, 700:900]].mean()
    c = bgra[..., :3].astype(np.float32)
    g = np.maximum(c[..., 1] - np.maximum(c[..., 0], c[..., 2]), 0)
    green = (g * a)[band].sum() / max(a[band].sum(), 1e-6)
    return inter, mae, hair, blur, green
gi = ((gt > 0.02) & (gt < 0.98))[band].mean() * 100
mo, mn = m(a_old, bgra_old), m(a_new, bgra_new)
pa = chroma.KeyParams(key); pa.values.update(spill=0, decontam=0, cw_enable=0)
pb = chroma.KeyParams(key); pb.values.update(spill=0, cw_enable=0)
ba0, bb0 = chroma.key_frame(frame, pa), chroma.key_frame(frame, pb)
g_old0, g_new0 = m(ba0[..., 3] / 255.0, ba0)[4], m(bb0[..., 3] / 255.0, bb0)[4]
lines = [f"Faixa de borda: {band.sum()} px; no alfa real {gi:.1f}% dos pixels da borda sao intermediarios",
         f"Pixels de borda com alfa intermediario (suave): antigo {mo[0]:.1f}%  -> novo {mn[0]:.1f}%",
         f"Erro medio do alfa na borda (vs. real, 0-1):    antigo {mo[1]:.3f}  -> novo {mn[1]:.3f}",
         f"Erro medio no cabelo:                          antigo {mo[2]:.3f}  -> novo {mn[2]:.3f}",
         f"Erro medio no desfoque de movimento:           antigo {mo[3]:.3f}  -> novo {mn[3]:.3f}",
         f"Verde residual nas bordas (0-255, pond. alfa):  antigo {mo[4]:.1f}   -> novo {mn[4]:.1f}",
         f"Efeito da descontaminacao (novo, sem spill): desligada {g_old0:.1f} -> ligada {g_new0:.1f}"]
print("\n".join(lines))

def over_checker(bgra):
    h, w = bgra.shape[:2]
    bg = chroma.checkerboard(h, w, 8).astype(np.float32)
    a = bgra[..., 3:4] / 255.0
    return (bgra[..., :3] * a + bg * (1 - a)).astype(np.uint8)

def crop4(bgra, x, y, w, h):
    c = bgra[y:y + h, x:x + w]
    hh, ww = c.shape[:2]
    # xadrez desenhado já na escala ampliada para não confundir com pixels
    big = cv2.resize(c, (ww * 4, hh * 4), interpolation=cv2.INTER_NEAREST)
    return over_checker(big)

regions = [("Cabelo (fios finos)", 330, 80, 160, 90), ("Desfoque de movimento", 730, 75, 160, 90),
           ("Borda lisa (rosto/ombro)", 250, 300, 160, 90)]
font = cv2.FONT_HERSHEY_SIMPLEX
rows = []
for name, x, y, w, h in regions:
    a = crop4(bgra_old, x, y, w, h); b = crop4(bgra_new, x, y, w, h)
    sep = np.full((a.shape[0], 12, 3), 255, np.uint8)
    row = np.hstack([a, sep, b])
    head = np.full((34, row.shape[1], 3), 255, np.uint8)
    cv2.putText(head, f"{name} - zoom 4x", (8, 24), font, 0.7, (30, 30, 30), 2, cv2.LINE_AA)
    rows.append(np.vstack([head, row]))
W = rows[0].shape[1]
title = np.full((60, W, 3), 255, np.uint8)
cv2.putText(title, "ANTES (versao anterior)", (60, 40), font, 0.9, (0, 0, 180), 2, cv2.LINE_AA)
cv2.putText(title, "DEPOIS (bordas refinadas)", (W // 2 + 60, 40), font, 0.9, (0, 130, 0), 2, cv2.LINE_AA)
foot = np.full((30 * len(lines) + 20, W, 3), 255, np.uint8)
def ascii_pt(s):
    import unicodedata
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
for i, l in enumerate(lines):
    cv2.putText(foot, ascii_pt(l), (10, 30 + 30 * i), font, 0.6, (30, 30, 30), 1, cv2.LINE_AA)
img = np.vstack([title] + rows + [foot])
chroma.write_png(os.path.join(ROOT, "comparacao_bordas.png"), img)
print("salvo", os.path.join(ROOT, "comparacao_bordas.png"), img.shape)
