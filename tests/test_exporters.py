"""Testa todos os formatos de exportação (inclui verificação de alfa com ffprobe)."""
import json, os, shutil, subprocess, sys
import cv2, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
from chromaqui import core, exporters as ex
from PIL import Image

OUT = os.path.join(HERE, "_out")
VID = os.path.join(OUT, "teste_verde.mp4")
DEST = os.path.join(OUT, "formatos")


def ffprobe(path):
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    r = subprocess.run([exe, "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
                        "stream=codec_name,profile,pix_fmt,width,height,nb_read_frames:stream_tags=alpha_mode",
                        "-of", "json", path], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)["streams"][0]


def vp9_alpha_pixfmt(path):
    """ffprobe mostra yuv420p + alpha_mode=1; decodificando com libvpx-vp9 aparece yuva420p."""
    exe = shutil.which("ffmpeg") or ex.ffmpeg_exe()
    r = subprocess.run([exe, "-hide_banner", "-c:v", "libvpx-vp9", "-i", path, "-frames:v", "1",
                        "-f", "rawvideo", "-pix_fmt", "rgba", "-"], capture_output=True)
    rgba = np.frombuffer(r.stdout, np.uint8)
    return "yuva420p" in r.stderr.decode(errors="replace"), rgba


def check_all(video=VID, dest=DEST, log=print, background=None):
    if not os.path.exists(video):
        sys.path.insert(0, HERE); import test_core; test_core.make_video(video)
    shutil.rmtree(dest, ignore_errors=True); os.makedirs(dest)
    P = core.KeyParams()
    res = {}
    for f in ex.FORMATS:
        o = core.ExportOptions(start=2, end=13, step=2, fmt=f.key, scale=0.5)
        out = os.path.join(dest, f.key + (f.ext if f.single_file else ""))
        r = ex.export(video, out, P, o)
        assert r["count"] == 6, (f.key, r)
        res[f.key] = r
        if not f.single_file:
            files = sorted(os.listdir(out)); assert len(files) == 6 and files[0].endswith(f.ext), files
            im = Image.open(os.path.join(out, files[2])); im.load()
            assert im.mode in ("RGBA", "LA") or "A" in im.getbands() or f.key == "tiff", (f.key, im.mode)
            arr = cv2.imdecode(np.fromfile(os.path.join(out, files[2]), np.uint8), cv2.IMREAD_UNCHANGED) \
                if f.key != "tga" else np.asarray(im)
            assert arr.shape[2] == 4 and arr[..., 3].min() == 0 and arr[..., 3].max() == 255, f.key
            log(f"{f.key}: 6 arquivos, alfa ok ({im.mode})")
    # GIF: transparência
    g = Image.open(res["gif"]["output"])
    assert g.n_frames == 6 and "transparency" in g.info, g.info
    tidx = g.info["transparency"]
    g.seek(3); a = np.asarray(g.convert("RGBA"))[..., 3]
    assert a.min() == 0 and a.max() == 255 and 0.2 < (a == 0).mean() < 0.95, (a == 0).mean()
    log(f"gif: {g.n_frames} quadros, transparência índice {tidx}, {100*(a==0).mean():.0f}% transparente")
    # WebP / APNG
    w = Image.open(res["webp"]["output"]); assert w.n_frames == 6 and getattr(w, "is_animated", False)
    w.seek(2); aw = np.asarray(w.convert("RGBA"))[..., 3]; assert aw.min() < 10 and aw.max() > 245
    log(f"webp animado: {w.n_frames} quadros, alfa ok")
    p = Image.open(res["apng"]["output"]); assert p.n_frames == 6
    p.seek(2); ap = np.asarray(p.convert("RGBA"))[..., 3]; assert ap.min() == 0 and ap.max() == 255
    log(f"apng: {p.n_frames} quadros, alfa ok")
    s = ffprobe(res["webm"]["output"])
    if s:
        assert s["codec_name"] == "vp9" and {k.lower(): v for k, v in s.get("tags", {}).items()}.get("alpha_mode") == "1", s
        ok, rgba = vp9_alpha_pixfmt(res["webm"]["output"])
        assert ok, "VP9 sem alfa"
        al = rgba.reshape(-1, 4)[:, 3]; assert al.min() < 10 and al.max() > 245
        log(f"webm: {s['codec_name']} alpha_mode=1, decodifica como yuva420p, {s['nb_read_frames']} quadros")
        s = ffprobe(res["prores"]["output"])
        assert s["codec_name"] == "prores" and s["pix_fmt"] in ("yuva444p10le", "yuva444p12le") and "4444" in s.get("profile", ""), s
        log(f"prores: {s.get('profile')} {s['pix_fmt']}, {s['nb_read_frames']} quadros")
    # fps automático = fps do vídeo / passo
    assert abs(res["gif"]["fps"] - 12.0) < 0.01
    # fundo incluído
    bgp = os.path.join(dest, "fundo.png")
    grad = np.zeros((90, 160, 3), np.uint8); grad[..., 0] = np.linspace(0, 255, 160)[None]; grad[..., 2] = 200
    cv2.imencode(".png", grad)[1].tofile(bgp)
    bg = background or core.Background(); bg.load(bgp); bg.mode = "fill"
    o = core.ExportOptions(start=0, end=0, fmt="png", include_bg=True, prefix="bg_")
    ex.export(video, os.path.join(dest, "com_fundo"), P, o, background=bg)
    im = cv2.imdecode(np.fromfile(os.path.join(dest, "com_fundo", "bg_00001.png"), np.uint8), cv2.IMREAD_UNCHANGED)
    assert im[..., 3].min() == 255 and abs(int(im[5, 5, 2]) - 200) < 6, im[5, 5]
    log("fundo incluído na exportação: ok (opaco, fundo visível)")
    # cancelar
    r = ex.export(video, os.path.join(dest, "cancel.webm"), P, core.ExportOptions(fmt="webm"),
                  should_cancel=lambda: True)
    assert r["cancelled"] and not os.path.exists(os.path.join(dest, "cancel.webm"))
    log("cancelar: ok")
    return res


if __name__ == "__main__":
    check_all()
    print("OK")
