"""Gera docs/demo.gif e docs/demo.webp: a demonstração (assets/demo) meio a meio — à esquerda o vídeo original
com tela verde, à direita o recorte do Chromaqui! sobre o cenário — com o próprio código de recorte do programa.

    python tools/make_demo_gif.py [largura=720] [fps=12]
"""
import os, subprocess, sys, tempfile
import cv2
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from chromaqui import core, demo  # noqa: E402

W = int(sys.argv[1]) if len(sys.argv) > 1 else 720
FPS = int(sys.argv[2]) if len(sys.argv) > 2 else 12
DOCS = os.path.join(ROOT, "docs")


def best_loop(frames, min_len, max_len):
    """(início, fim) do trecho cujo último quadro mais se parece com o primeiro (laço sem salto)."""
    small = [cv2.resize(f, (160, 90), interpolation=cv2.INTER_AREA).astype(np.float32) for f in frames]
    best = None
    for a in range(0, len(frames) - min_len):
        for b in range(a + min_len, min(len(frames), a + max_len + 1)):
            d = float(np.abs(small[a] - small[b]).mean())
            if best is None or d < best[0]:
                best = (d, a, b)
    return best[1], best[2]


def main():
    v = core.Video(demo.video_path())
    src_fps = v.fps or 24.0
    step = max(1, round(src_fps / FPS))
    idx = list(range(0, v.frame_count, step))
    raw = [v.read(i) for i in idx]
    v.release()
    a, b = best_loop(raw, int(2.5 * FPS), int(4.0 * FPS))   # 2,5–4 s
    raw = raw[a:b]                                          # o quadro b (≈ a) não entra: laço contínuo
    H = int(round(W * raw[0].shape[0] / raw[0].shape[1] / 2) * 2)
    p = demo.params()
    bg = core.fit_image(cv2.imread(demo.background_path()), raw[0].shape[1], raw[0].shape[0], demo.BG_MODE)
    tmp = tempfile.mkdtemp(prefix="cq_demo_gif_")
    mid = W // 2
    for n, fr in enumerate(raw):
        res = core.render_view(fr, p, "Resultado", bg_img=bg)
        res = res[..., :3] if res.ndim == 3 and res.shape[2] == 4 else res
        o = cv2.resize(fr, (W, H), interpolation=cv2.INTER_AREA)
        r = cv2.resize(res, (W, H), interpolation=cv2.INTER_AREA)
        out = o.copy()
        out[:, mid:] = r[:, mid:]
        line = out[:, mid - 1:mid + 1].astype(np.float32)        # divisória sutil (branco 55%)
        out[:, mid - 1:mid + 1] = (line * 0.45 + 255 * 0.55).astype(np.uint8)
        cv2.imwrite(os.path.join(tmp, f"f{n:04d}.png"), out)
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    pat = os.path.join(tmp, "f%04d.png")
    gif = os.path.join(DOCS, "demo.gif")
    subprocess.run([ff, "-v", "error", "-y", "-framerate", str(FPS), "-i", pat, "-filter_complex",
                    "split[a][b];[a]palettegen=max_colors=256:stats_mode=full[p];"
                    "[b][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle", "-loop", "0", gif], check=True)
    from PIL import Image
    ims = [Image.open(os.path.join(tmp, f"f{n:04d}.png")).convert("RGB") for n in range(len(raw))]
    webp = os.path.join(DOCS, "demo.webp")
    ims[0].save(webp, save_all=True, append_images=ims[1:], duration=round(1000 / FPS), loop=0,
                quality=80, method=6)
    print(f"quadros {idx[a]}–{idx[b - 1]} (passo {step}), {len(raw)} quadros, {len(raw) / FPS:.1f} s, {W}x{H}")
    for f in (gif, webp):
        print(os.path.relpath(f, ROOT), os.path.getsize(f))


if __name__ == "__main__":
    main()
