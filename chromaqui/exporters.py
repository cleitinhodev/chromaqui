"""Exportação: sequências de imagens (PNG/TGA/TIFF/WebP) e animações/vídeos com
transparência (GIF, WebP animado, APNG, WebM VP9 com alfa, MOV ProRes 4444 com alfa)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass

import cv2
import numpy as np

from . import gpu
from .core import ExportOptions, KeyParams, Video, key_frame_float, resize_rgba, to_bgra, write_png


@dataclass(frozen=True)
class Format:
    key: str
    label: str
    ext: str
    single_file: bool        # True = um arquivo; False = pasta com sequência
    needs_ffmpeg: bool = False


FORMATS = [
    Format("png", "Sequência PNG", ".png", False),
    Format("tga", "Sequência TGA", ".tga", False),
    Format("tiff", "Sequência TIFF", ".tif", False),
    Format("webp_seq", "Sequência WebP", ".webp", False),
    Format("gif", "GIF animado (transparente)", ".gif", True),
    Format("webp", "WebP animado (alfa)", ".webp", True, True),
    Format("apng", "APNG animado (alfa)", ".png", True, True),
    Format("webm", "WebM VP9 (alfa)", ".webm", True, True),
    Format("prores", "MOV ProRes 4444 (alfa)", ".mov", True, True),
]
FORMAT_BY_KEY = {f.key: f for f in FORMATS}


# --------------------------------------------------------------------------------------
def ffmpeg_exe():
    """ffmpeg embutido (imageio-ffmpeg); se faltar, procura no PATH."""
    env = os.environ.get("CHROMAQUI_FFMPEG")
    if env and os.path.isfile(env):
        return env
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            return exe
    except Exception:  # noqa: BLE001
        pass
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        d = os.path.join(base, "imageio_ffmpeg", "binaries")
        if os.path.isdir(d):
            for n in os.listdir(d):
                if n.startswith("ffmpeg"):
                    return os.path.join(d, n)
    return shutil.which("ffmpeg")


def ffmpeg_available():
    return ffmpeg_exe() is not None


def _no_window():
    return {"creationflags": 0x08000000} if sys.platform.startswith("win") else {}


# --------------------------------------------------------------------------------------
class _SeqWriter:
    def __init__(self, out_dir, opts: ExportOptions, ext):
        os.makedirs(out_dir, exist_ok=True)
        self.out_dir, self.opts, self.ext, self.n = out_dir, opts, ext, 0
        self.files = []

    def write(self, color, alpha):
        o = self.opts
        self.n += 1
        path = os.path.join(self.out_dir, f"{o.prefix}{self.n:05d}{self.ext}")
        if o.fmt == "png":
            write_png(path, to_bgra(color, alpha, o.bit16), o.compression)
        elif o.fmt == "tiff":
            # Pillow/tifffile gravam a tag ExtraSamples (alfa não associado), que o OpenCV omite:
            # sem ela, Photoshop/GIMP podem ignorar a transparência.
            rgba = to_bgra(color, alpha, o.bit16)[..., [2, 1, 0, 3]]
            if o.bit16:
                import tifffile
                tifffile.imwrite(path, rgba, photometric="rgb", extrasamples=["unassalpha"],
                                 compression="zlib" if o.tiff_compress else None)   # Deflate, sem perdas
            else:
                from PIL import Image
                Image.fromarray(np.ascontiguousarray(rgba), "RGBA").save(
                    path, compression="tiff_lzw" if o.tiff_compress else None)
        elif o.fmt == "webp_seq":
            q = 101 if o.lossless else max(1, min(100, int(o.quality)))      # >100 = sem perdas
            ok, data = cv2.imencode(".webp", to_bgra(color, alpha), [cv2.IMWRITE_WEBP_QUALITY, q])
            if not ok:
                raise IOError(path)
            data.tofile(path)
        elif o.fmt == "tga":
            from PIL import Image
            bgra = to_bgra(color, alpha)
            Image.fromarray(bgra[..., [2, 1, 0, 3]], "RGBA").save(path, compression="tga_rle")
        self.files.append(path)

    def close(self, ok=True):
        return self.out_dir


class _GifWriter:
    """GIF tem transparência de 1 bit: pixel com alfa >= limiar fica opaco. As bordas
    semitransparentes podem ser misturadas com uma cor 'matte' (a cor do fundo onde o GIF
    será usado) para não ficarem serrilhadas/escuras."""

    def __init__(self, path, opts: ExportOptions, fps):
        self.path, self.o, self.fps = path, opts, fps
        self.frames = []

    def write(self, color, alpha):
        from PIL import Image
        o = self.o
        a = np.clip(alpha, 0, 1)[..., None]
        if o.gif_matte:
            matte = np.array(o.gif_matte_rgb[::-1], np.float32)
            c = color * a + matte * (1 - a)
        else:
            c = color
        rgb = np.clip(c[..., ::-1] + 0.5, 0, 255).astype(np.uint8)
        opaque = alpha * 255.0 >= o.gif_alpha_threshold
        n = max(2, min(256, int(o.gif_colors)))
        img = Image.fromarray(np.ascontiguousarray(rgb), "RGB")
        method = Image.Quantize.FASTOCTREE if o.gif_palette == "rápida" else Image.Quantize.MEDIANCUT
        dither = Image.Dither.FLOYDSTEINBERG if o.gif_dither else Image.Dither.NONE
        # quantiza só os pixels opacos (a paleta não desperdiça cores com o fundo)
        if opaque.any():
            src = rgb.copy()
            mean = rgb[opaque].mean(0).astype(np.uint8)
            src[~opaque] = mean
            img = Image.fromarray(src, "RGB")
        q0 = img.quantize(colors=n - 1, method=method, dither=Image.Dither.NONE)
        pal = (q0.getpalette() or [0, 0, 0])[: 3 * (n - 1)]
        k = len(pal) // 3
        # completa a paleta repetindo a última cor (nenhum índice "sobra" vira preto/transparente)
        full = pal + pal[-3:] * (256 - k)
        pimg = Image.new("P", (1, 1))
        pimg.putpalette(full)
        q = img.quantize(palette=pimg, dither=dither) if o.gif_dither else q0
        idx = np.asarray(q, np.uint8).copy()
        idx[idx >= k] = k - 1
        pal = full
        t = 255
        idx[~opaque] = t
        out = Image.fromarray(idx, "P")
        out.putpalette(pal)
        out.info["transparency"] = t
        self.frames.append(out)

    def close(self, ok=True):
        if not ok or not self.frames:
            return None
        d = max(20, int(round(1000.0 / max(self.fps, 1e-3) / 10.0)) * 10)  # GIF usa centésimos
        self.frames[0].save(self.path, save_all=True, append_images=self.frames[1:], duration=d,
                            loop=int(self.o.loop), transparency=255, disposal=2, optimize=False)
        return self.path


class _FFmpegWriter:
    def __init__(self, path, opts: ExportOptions, fps):
        self.path, self.o, self.fps = path, opts, fps
        self.proc = None
        self.deep = opts.fmt == "prores"          # envia 16 bits para o ProRes (10 bits + alfa 16)
        self.err = b""

    def _args(self, w, h):
        o = self.o
        exe = ffmpeg_exe()
        if not exe:
            raise RuntimeError("ffmpeg não encontrado")
        a = [exe, "-hide_banner", "-loglevel", "error", "-y",
             "-f", "rawvideo", "-pix_fmt", "bgra64le" if self.deep else "bgra",
             "-s", f"{w}x{h}", "-framerate", f"{self.fps:.6f}", "-i", "-"]
        even = ["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2:color=black@0"]
        q = max(0, min(100, int(o.quality)))
        if o.fmt == "webm":
            crf = int(round(63 - q * 0.53))                  # 90 -> ~15
            a += even + ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", str(crf),
                         "-auto-alt-ref", "0", "-row-mt", "1", "-deadline", "good", "-cpu-used", "4",
                         "-metadata:s:v:0", "alpha_mode=1"]
        elif o.fmt == "prores":
            a += even + ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
                         "-alpha_bits", "16", "-vendor", "apl0", "-f", "mov"]
        elif o.fmt == "webp":
            a += ["-c:v", "libwebp_anim", "-loop", str(int(o.loop))]
            if o.lossless:
                a += ["-lossless", "1", "-pix_fmt", "bgra"]
            else:
                a += ["-lossless", "0", "-quality", str(q), "-pix_fmt", "yuva420p"]
            a += ["-f", "webp"]
        elif o.fmt == "apng":
            a += ["-c:v", "apng", "-pix_fmt", "rgba", "-plays", str(int(o.loop)), "-f", "apng"]
        return a + [self.path]

    def write(self, color, alpha):
        img = to_bgra(color, alpha, self.deep)
        if self.proc is None:
            h, w = img.shape[:2]
            self.proc = subprocess.Popen(self._args(w, h), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.PIPE, **_no_window())
        try:
            self.proc.stdin.write(np.ascontiguousarray(img).tobytes())
        except (BrokenPipeError, OSError):
            self.err = self.proc.stderr.read() if self.proc.stderr else b""
            raise RuntimeError("ffmpeg falhou: " + self.err.decode("utf-8", "replace")[-400:])

    def close(self, ok=True):
        if self.proc is None:
            return None
        if not ok:
            try:
                self.proc.kill()
            finally:
                self.proc.wait()
            try:
                os.remove(self.path)
            except OSError:
                pass
            return None
        _, err = self.proc.communicate()
        if self.proc.returncode != 0:
            raise RuntimeError("ffmpeg falhou: " + (err or b"").decode("utf-8", "replace")[-400:])
        return self.path


# --------------------------------------------------------------------------------------
def composite(color, alpha, back_bgr):
    """Compõe o objeto sobre o fundo; resultado opaco (alfa = 1)."""
    a = alpha[..., None]
    out = color * a + back_bgr.astype(np.float32) * (1 - a)
    return out, np.ones_like(alpha)


def default_output_name(video_path, fmt_key):
    f = FORMAT_BY_KEY[fmt_key]
    base = os.path.splitext(os.path.basename(video_path))[0] or "chromaqui"
    return f"{base}_chromaqui{f.ext}"


def export(path, out, params: KeyParams, opts: ExportOptions | None = None,
           progress=None, should_cancel=None, background=None):
    """Exporta o intervalo escolhido. `out` = pasta (sequências) ou arquivo (animações).
    Retorna {"count", "output", "fps", "cancelled"}."""
    opts = opts or ExportOptions()
    fmt = FORMAT_BY_KEY.get(opts.fmt)
    if fmt is None:
        raise ValueError(f"formato desconhecido: {opts.fmt}")
    if fmt.needs_ffmpeg and not ffmpeg_available():
        raise RuntimeError("ffmpeg não encontrado")
    v = Video(path)
    n_total = v.frame_count
    start = max(0, min(opts.start, n_total - 1))
    end = n_total - 1 if opts.end < 0 else min(opts.end, n_total - 1)
    step = max(1, int(opts.step))
    fps = opts.fps if opts.fps and opts.fps > 0 else (v.fps or 30.0) / step
    expected = max(0, (end - start) // step + 1)
    if fmt.single_file:
        if os.path.isdir(out):
            out = os.path.join(out, default_output_name(path, fmt.key))
        os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
        writer = _GifWriter(out, opts, fps) if fmt.key == "gif" else _FFmpegWriter(out, opts, fps)
    else:
        writer = _SeqWriter(out, opts, fmt.ext)
    bg = background if (opts.include_bg and background is not None and background.active) else None
    cap = v.cap
    if start > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    count, idx, ok_all, cancelled = 0, start, False, False
    try:
        while idx <= end:
            if should_cancel and should_cancel():
                cancelled = True
                break
            if (idx - start) % step:
                if not cap.grab():
                    break
                idx += 1
                continue
            ok, frame = cap.read()
            if not ok:
                break
            if opts.scale > 1.0:
                # aumenta ANTES do recorte (Lanczos): bordas calculadas na resolução final
                h, w = frame.shape[:2]
                frame = gpu.resize(frame, (int(round(w * opts.scale)), int(round(h * opts.scale))),
                                   interpolation=cv2.INTER_LANCZOS4)
                color, alpha = key_frame_float(frame, params, opts.scale)
            else:
                color, alpha = key_frame_float(frame, params)
                color, alpha = resize_rgba(color, alpha, opts.scale)
            if bg is not None:
                hh, ww = alpha.shape
                color, alpha = composite(color, alpha, bg.frame(idx, ww, hh))
            writer.write(color, alpha)
            count += 1
            idx += 1
            if progress:
                progress(count, max(expected, count))
        ok_all = not cancelled and count > 0
    finally:
        v.release()
        output = writer.close(ok_all or (not cancelled and not fmt.single_file))
    return {"count": count if (ok_all or not fmt.single_file) else 0, "output": output,
            "fps": fps, "cancelled": cancelled}
