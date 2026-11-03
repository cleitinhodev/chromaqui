"""Gera vídeo de teste realista: bordas suaves (anti-aliasing), fios finos tipo cabelo,
desfoque de movimento, fundo verde irregular e compressão H.264 (yuv420p).
Salva também o alfa verdadeiro (ground truth) para medir a qualidade."""
import os, subprocess, sys
import cv2, numpy as np

W, H, SS, N = 960, 540, 4, 24
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_out")


def background(rng):
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    shade = 0.78 + 0.3 * (xx / W) - 0.12 * ((yy - H / 2) / H) ** 2 * 4
    base = np.array([60, 175, 35], np.float32)  # BGR verde de estúdio
    bg = base[None, None] * shade[..., None]
    wr = cv2.GaussianBlur(rng.normal(0, 1, (H, W)).astype(np.float32), (0, 0), 25) * 60  # dobras do pano
    bg += wr[..., None] * np.array([0.3, 1, 0.3], np.float32)
    return bg


def foreground(i, rng_seed=7, hair=(30, 45, 70)):
    """Desenha em super-resolução e reduz (anti-aliasing real). Retorna cor BGR e alfa."""
    w, h = W * SS, H * SS
    col = np.zeros((h, w, 3), np.float32)
    a = np.zeros((h, w), np.float32)
    cx = int((300 + i * 8) * SS)
    cy = int(250 * SS)
    # corpo (camisa) e cabeça
    cv2.ellipse(col, (cx, cy + 260 * SS), (150 * SS, 140 * SS), 0, 180, 360, (90, 60, 160), -1, cv2.LINE_AA)
    cv2.ellipse(a, (cx, cy + 260 * SS), (150 * SS, 140 * SS), 0, 180, 360, 1, -1, cv2.LINE_AA)
    cv2.ellipse(col, (cx, cy), (70 * SS, 90 * SS), 0, 0, 360, (120, 160, 215), -1, cv2.LINE_AA)
    cv2.ellipse(a, (cx, cy), (70 * SS, 90 * SS), 0, 0, 360, 1, -1, cv2.LINE_AA)
    # cabelo: massa + fios finos
    cv2.ellipse(col, (cx, cy - 30 * SS), (78 * SS, 70 * SS), 0, 180, 360, hair, -1, cv2.LINE_AA)
    cv2.ellipse(a, (cx, cy - 30 * SS), (78 * SS, 70 * SS), 0, 180, 360, 1, -1, cv2.LINE_AA)
    rng = np.random.default_rng(rng_seed)
    for _ in range(140):
        ang = rng.uniform(np.pi * 1.05, np.pi * 1.95)
        r0 = 70 * SS
        length = rng.uniform(25, 75) * SS
        curl = rng.uniform(-0.6, 0.6)
        pts = []
        for t in np.linspace(0, 1, 14):
            aa = ang + curl * t
            rr = r0 + length * t
            pts.append([cx + rr * np.cos(aa), cy - 30 * SS + rr * np.sin(aa) * 1.0])
        pts = np.array(pts, np.int32)
        th = int(rng.integers(2, 5))  # 0.5 a 1.25 px na resolução final
        cv2.polylines(col, [pts], False, tuple(c * 0.9 for c in hair), th, cv2.LINE_AA)
        cv2.polylines(a, [pts], False, 1.0, th, cv2.LINE_AA)
    col = cv2.resize(col, (W, H), interpolation=cv2.INTER_AREA)
    a = cv2.resize(a, (W, H), interpolation=cv2.INTER_AREA)
    return col, np.clip(a, 0, 1)


def ball(i):
    """Bola rápida com desfoque de movimento + disco desfocado (fora de foco)."""
    col = np.zeros((H, W, 3), np.float32)
    a = np.zeros((H, W), np.float32)
    x = int(650 + 12 * i)
    cv2.circle(col, (x, 120), 40, (40, 140, 240), -1, cv2.LINE_AA)
    cv2.circle(a, (x, 120), 40, 1, -1, cv2.LINE_AA)
    k = np.zeros((1, 31), np.float32); k[:] = 1 / 31  # desfoque de movimento horizontal
    pm = cv2.filter2D(col * a[..., None], -1, k)
    a = cv2.filter2D(a, -1, k)
    col2 = np.zeros((H, W, 3), np.float32); a2 = np.zeros((H, W), np.float32)
    cv2.circle(col2, (820, 420), 55, (200, 200, 60), -1, cv2.LINE_AA)
    cv2.circle(a2, (820, 420), 55, 1, -1, cv2.LINE_AA)
    a2 = cv2.GaussianBlur(a2, (0, 0), 6)
    pm2 = np.array([200, 200, 60], np.float32)[None, None] * a2[..., None]
    return pm, a, pm2, a2


def frame(i, bg, hair=(30, 45, 70)):
    fc, fa = foreground(i, hair=hair)
    pm, ba, pm2, a2 = ball(i)
    img = bg.copy()
    for p, al in ((pm2, a2), (fc * fa[..., None], fa), (pm, ba)):
        img = p + img * (1 - al[..., None])
    alpha = 1 - (1 - fa) * (1 - ba) * (1 - a2)
    pmt = np.zeros_like(img)
    for p, al in ((pm2, a2), (fc * fa[..., None], fa), (pm, ba)):
        pmt = p + pmt * (1 - al[..., None])
    fg = pmt / np.maximum(alpha, 1e-4)[..., None]   # cor real do objeto (sem fundo)
    return np.clip(img, 0, 255).astype(np.uint8), alpha, fg


def make(name, hair, gt_name):
    os.makedirs(OUT, exist_ok=True)
    rng = np.random.default_rng(1)
    bg = background(rng)
    path = os.path.join(OUT, name)
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                           "-s", f"{W}x{H}", "-r", "24", "-i", "-", "-c:v", "libx264", "-crf", "26",
                           "-preset", "medium", "-pix_fmt", "yuv420p", path], stdin=subprocess.PIPE)
    gts = {}
    for i in range(N):
        img, alpha, fg = frame(i, bg, hair)
        img = np.clip(img.astype(np.float32) + rng.normal(0, 3, img.shape), 0, 255).astype(np.uint8)  # ruído do sensor
        ff.stdin.write(img.tobytes())
        if i in (0, 12, 23):
            gts[f"a{i}"] = alpha.astype(np.float32)
        if i == 12:
            gts["fg12"] = np.clip(fg, 0, 255).astype(np.float32)
    ff.stdin.close(); ff.wait()
    np.savez_compressed(os.path.join(OUT, gt_name), **gts)
    print("ok", path)


def main():
    make("teste_bordas_suaves.mp4", (30, 45, 70), "alpha_gt.npz")          # cabelo castanho escuro
    make("teste_cabelo_loiro.mp4", (95, 190, 225), "alpha_gt_loiro.npz")   # cabelo loiro (BGR)


if __name__ == "__main__":
    main()
