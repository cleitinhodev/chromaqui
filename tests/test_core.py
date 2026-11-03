"""Teste headless: gera vídeo verde sintético, aplica chroma key e exporta PNGs."""
import os, sys, shutil
import cv2, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from chromaqui import core as chroma
sys.path.insert(0, HERE)

OUT = os.path.join(HERE, "_out")
VID = os.path.join(OUT, "teste_verde.mp4")

def make_video(path, n=48, w=640, h=360):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 24, (w, h))
    rng = np.random.default_rng(0)
    for i in range(n):
        f = np.zeros((h, w, 3), np.uint8)
        # fundo verde com gradiente de iluminação + ruído
        shade = np.linspace(0.75, 1.05, w)[None, :, None]
        f[:] = np.clip(np.array([64, 177, 0], np.float32) * shade + rng.normal(0, 4, (h, w, 3)), 0, 255)
        x = 60 + i * 9
        cv2.circle(f, (x, 180), 70, (40, 60, 220), -1)          # bola vermelha
        cv2.rectangle(f, (x - 30, 260), (x + 30, 330), (230, 200, 30), -1)  # azul claro
        cv2.putText(f, f"{i+1}", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)
        vw.write(f)
    vw.release()

if __name__ == "__main__":
    shutil.rmtree(OUT, ignore_errors=True)
    make_video(VID)
    v = chroma.Video(VID); print("frames:", v.frame_count, v.width, v.height, v.fps); v.release()
    dest = os.path.join(OUT, "exportação ção")  # testa caminho com acentos
    prog = []
    P = chroma.KeyParams()
    n = chroma.export_frames(VID, dest, P, progress=lambda c, t: prog.append((c, t)))
    files = sorted(os.listdir(dest))
    print("exportados:", n, files[0], files[-1], "progress last:", prog[-1])
    assert n == 48 and len(files) == 48 and files[0] == "frame_00001.png"
    img = cv2.imdecode(np.fromfile(os.path.join(dest, "frame_00010.png"), np.uint8), cv2.IMREAD_UNCHANGED)
    assert img.shape[2] == 4, img.shape
    a = img[..., 3]
    x = 60 + 9 * 9
    print("alpha canto (fundo):", a[200, 600], "| centro bola:", a[180, x], "| retângulo:", a[295, x],
          "| fundo escuro esquerda:", a[200, 5 if x > 140 else 630])
    assert a[200, 600] == 0 and a[10, 300] == 0 and a[180, x] == 255 and a[295, x] == 255
    frac = (a == 0).mean(); print(f"fração transparente: {frac:.2f}")
    assert 0.6 < frac < 0.95
    # cancelamento
    c = chroma.export_frames(VID, os.path.join(OUT, "cancel"), P, None,
                             should_cancel=lambda: len(os.listdir(os.path.join(OUT, "cancel"))) >= 5)
    print("cancelado após:", c); assert c == 5
    # opções de exportação: intervalo, passo, escala, 16 bits
    d2 = os.path.join(OUT, "opts")
    n2 = chroma.export_frames(VID, d2, P, chroma.ExportOptions(start=4, end=23, step=2, prefix="clip_", scale=2.0, bit16=True, compression=9))
    f2 = sorted(os.listdir(d2)); im = cv2.imdecode(np.fromfile(os.path.join(d2, f2[0]), np.uint8), cv2.IMREAD_UNCHANGED)
    print("opções:", n2, f2[0], f2[-1], im.shape, im.dtype, im[..., 3].max())
    assert n2 == 10 and im.shape == (720, 1280, 4) and im.dtype == np.uint16 and im[..., 3].max() == 65535
    # parâmetros profissionais não quebram e têm efeito
    v = chroma.Video(VID); fr = v.read(10); v.release()
    a0 = chroma.compute_alpha(fr, P)
    for k, val in [("choke", 50), ("choke", -50), ("soften", 50), ("contrast", 50), ("pedestal", 30), ("transparency", 50), ("highlight", 80), ("shadow", 80), ("crop_left", 20)]:
        q = chroma.KeyParams(); q.values[k] = val
        a1 = chroma.compute_alpha(fr, q)
        print(f"  {k}={val}: opaco {a0.mean():.3f} -> {a1.mean():.3f}")
    for k, val in [("brightness", 40), ("fg_contrast", 50), ("saturation", 0), ("hue", 90), ("temperature", 60), ("desaturate", 100), ("spill_range", 100)]:
        q = chroma.KeyParams(); q.values[k] = val
        c1 = chroma.process_color(fr, q); print(f"  {k}={val}: mudança média de cor {np.abs(c1 - chroma.process_color(fr, P)).mean():.1f}")
    for view in ["Resultado", "Máscara (alfa)", "Original", "Lado a lado"]:
        for bg in ["xadrez", "preto", "branco", "cor"]:
            chroma.render_view(fr, P, view, bg, (255, 0, 255))
    pp = os.path.join(OUT, "p.json"); q = chroma.KeyParams((10, 20, 200)); q.values["choke"] = 7
    chroma.save_preset(pp, q); r = chroma.load_preset(pp); assert r.key_rgb == (10, 20, 200) and r.choke == 7
    # vídeo realista (bordas suaves, cabelo, desfoque, H.264): bordas contínuas e escala 2x
    import make_soft_video
    make_soft_video.main()
    sv = os.path.join(OUT, "teste_bordas_suaves.mp4")
    v = chroma.Video(sv); fr = v.read(12); v.release()
    key = tuple(int(c) for c in fr[20:60, 20:60].reshape(-1, 3).mean(0)[::-1])
    K = chroma.KeyParams(key)
    a = chroma.compute_alpha(fr, K)
    gt = np.load(os.path.join(OUT, "alpha_gt.npz"))["a12"]
    band = (gt > 0.02) & (gt < 0.98)
    inter = ((a > 0.02) & (a < 0.98))[band].mean()
    mae = np.abs(a - gt)[band].mean()
    print(f"bordas suaves: intermediários {inter*100:.1f}%  erro {mae:.3f}")
    assert inter > 0.4 and mae < 0.12
    d3 = os.path.join(OUT, "x2")
    n3 = chroma.export_frames(sv, d3, K, chroma.ExportOptions(start=12, end=12, scale=2.0))
    im = cv2.imdecode(np.fromfile(os.path.join(d3, "frame_00001.png"), np.uint8), cv2.IMREAD_UNCHANGED)
    print("2x:", im.shape); assert n3 == 1 and im.shape == (1080, 1920, 4)
    print("OK")
