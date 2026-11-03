"""(Referência) Lógica de keying da versão 2.x — chamada "Chroma Frames" — usada só para comparar resultados nos testes."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict

import cv2
import numpy as np

VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".wmv")

PRESETS = {
    "Verde": (0, 177, 64),    # RGB
    "Azul": (0, 71, 187),
}

# --------------------------------------------------------------------------------------
# Definição dos parâmetros: (chave, rótulo, mín, máx, padrão, dica)  agrupados por seção
PARAM_SECTIONS = [
    ("Geração da máscara", [
        ("tolerance", "Tolerância", 0, 100, 30, "Quanto de cores parecidas com a cor-chave será removido."),
        ("edge", "Faixa de transição", 0, 100, 20, "Largura da passagem entre opaco e transparente (bordas, cabelo)."),
        ("transparency", "Transparência", 0, 100, 0, "Deixa as áreas semitransparentes mais transparentes."),
        ("highlight", "Realce (luzes)", 0, 100, 0, "Aumenta a opacidade das áreas claras do objeto."),
        ("shadow", "Sombra", 0, 100, 0, "Aumenta a opacidade das áreas escuras do objeto."),
        ("pedestal", "Pedestal", 0, 100, 0, "Remove ruído: valores baixos de alfa viram transparentes."),
    ]),
    ("Limpeza da máscara", [
        ("choke", "Encolher / expandir", -100, 100, 0, "Positivo encolhe a borda do objeto; negativo expande."),
        ("soften", "Suavizar", 0, 100, 0, "Desfoca a máscara para bordas mais macias."),
        ("contrast", "Contraste da máscara", 0, 100, 0, "Deixa a máscara mais dura (menos áreas semitransparentes)."),
        ("midpoint", "Ponto médio", 0, 100, 50, "Ponto de equilíbrio usado pelo contraste da máscara."),
    ]),
    ("Supressão de reflexo (spill)", [
        ("spill", "Quantidade", 0, 100, 50, "Quanto do reflexo da cor-chave é removido das bordas."),
        ("spill_range", "Intervalo", 0, 100, 0, "Amplia a faixa de cores consideradas reflexo (mais agressivo)."),
        ("desaturate", "Dessaturar", 0, 100, 0, "Tira a saturação das áreas com reflexo."),
        ("spill_luma", "Luma (preservar brilho)", 0, 100, 50, "Devolve o brilho perdido ao remover o reflexo."),
    ]),
    ("Correção de cor do objeto", [
        ("brightness", "Brilho", -100, 100, 0, ""),
        ("fg_contrast", "Contraste", -100, 100, 0, ""),
        ("saturation", "Saturação", 0, 200, 100, "100 = original."),
        ("hue", "Matiz", -180, 180, 0, "Gira as cores (graus)."),
        ("temperature", "Temperatura", -100, 100, 0, "Negativo = mais frio (azul); positivo = mais quente."),
    ]),
    ("Recorte (garbage matte)", [
        ("crop_top", "Recortar topo %", 0, 50, 0, "Torna transparente essa porcentagem do topo."),
        ("crop_bottom", "Recortar baixo %", 0, 50, 0, ""),
        ("crop_left", "Recortar esquerda %", 0, 50, 0, ""),
        ("crop_right", "Recortar direita %", 0, 50, 0, ""),
    ]),
]
PARAM_DEFAULTS = {k: d for _, items in PARAM_SECTIONS for k, _, _, _, d, _ in items}


@dataclass
class KeyParams:
    key_rgb: tuple = PRESETS["Verde"]
    values: dict = field(default_factory=lambda: dict(PARAM_DEFAULTS))
    enabled: bool = True

    def __getattr__(self, name):
        vals = self.__dict__.get("values")
        if vals is not None and name in vals:
            return vals[name]
        raise AttributeError(name)

    def to_dict(self):
        return {"key_rgb": list(self.key_rgb), "enabled": self.enabled, **self.values}

    @classmethod
    def from_dict(cls, d):
        vals = dict(PARAM_DEFAULTS)
        for k in vals:
            if k in d:
                vals[k] = int(d[k])
        return cls(tuple(int(c) for c in d.get("key_rgb", PRESETS["Verde"])), vals, bool(d.get("enabled", True)))


@dataclass
class ExportOptions:
    start: int = 0              # índice do primeiro quadro (0-based)
    end: int = -1               # último quadro inclusive (-1 = até o fim)
    step: int = 1               # exporta 1 a cada N quadros
    prefix: str = "frame_"
    scale: float = 1.0
    bit16: bool = False
    compression: int = 3        # 0..9


def save_preset(path, params: KeyParams):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"app": "ChromaFrames", "version": 2, **params.to_dict()}, f, ensure_ascii=False, indent=2)


def load_preset(path) -> KeyParams:
    with open(path, encoding="utf-8") as f:
        return KeyParams.from_dict(json.load(f))


# --------------------------------------------------------------------------------------
def _rgb_to_crcb(rgb):
    px = np.uint8([[list(rgb[::-1])]])
    ycc = cv2.cvtColor(px, cv2.COLOR_BGR2YCrCb)[0, 0].astype(np.float32)
    return ycc[1], ycc[2]


def _smoothstep(e0, e1, x):
    t = np.clip((x - e0) / max(e1 - e0, 1e-6), 0, 1)
    return t * t * (3 - 2 * t)


def compute_alpha(frame_bgr, p: KeyParams, px_scale: float = 1.0) -> np.ndarray:
    """Máscara alfa float32 0..1. px_scale = (resolução do preview / original) p/ raios."""
    ycc = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2YCrCb).astype(np.float32)
    kcr, kcb = _rgb_to_crcb(p.key_rgb)
    dist = np.sqrt((ycc[..., 1] - kcr) ** 2 + (ycc[..., 2] - kcb) ** 2)
    t = p.tolerance * 0.9
    s = max(p.edge * 0.6, 0.5)
    a = np.clip((dist - t) / s, 0.0, 1.0)

    # --- geração
    if p.transparency:
        a = a ** (1.0 + p.transparency / 25.0)
    luma = ycc[..., 0] / 255.0
    if p.highlight:
        a = a + (1 - a) * (p.highlight / 100.0) * _smoothstep(0.55, 0.95, luma)
    if p.shadow:
        a = a + (1 - a) * (p.shadow / 100.0) * (1 - _smoothstep(0.05, 0.45, luma))
    if p.pedestal:
        ped = p.pedestal / 100.0 * 0.9
        a = np.clip((a - ped) / (1 - ped), 0, 1)

    # --- limpeza
    if p.choke:
        r = int(round(abs(p.choke) / 100.0 * 20 * px_scale))
        if r >= 1:
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
            a = cv2.erode(a, k) if p.choke > 0 else cv2.dilate(a, k)
    if p.soften:
        sigma = p.soften / 100.0 * 10 * px_scale
        if sigma > 0.3:
            a = cv2.GaussianBlur(a, (0, 0), sigma)
    if p.contrast or p.midpoint != 50:
        k = 1.0 + p.contrast / 100.0 * 15
        a = np.clip(0.5 + (a - p.midpoint / 100.0) * k, 0, 1)

    # --- recorte
    h, w = a.shape
    ct, cb = int(h * p.crop_top / 100), int(h * p.crop_bottom / 100)
    cl, cr = int(w * p.crop_left / 100), int(w * p.crop_right / 100)
    if ct: a[:ct] = 0
    if cb: a[h - cb:] = 0
    if cl: a[:, :cl] = 0
    if cr: a[:, w - cr:] = 0
    return a.astype(np.float32)


def process_color(frame_bgr, p: KeyParams) -> np.ndarray:
    """Supressão de spill + correção de cor. Retorna BGR float32 0..255."""
    img = frame_bgr.astype(np.float32)
    lum_w = np.array([0.114, 0.587, 0.299], np.float32)  # pesos BGR
    if p.spill:
        key_bgr = np.array(p.key_rgb[::-1], np.float32)
        dom = int(np.argmax(key_bgr))
        o1, o2 = [c for c in range(3) if c != dom]
        mx = np.maximum(img[..., o1], img[..., o2])
        avg = (img[..., o1] + img[..., o2]) * 0.5
        r = p.spill_range / 100.0
        limit = mx * (1 - r) + avg * r
        excess = np.maximum(img[..., dom] - limit, 0) * (p.spill / 100.0)
        y0 = img @ lum_w
        img[..., dom] -= excess
        if p.desaturate:
            amt = np.clip(excess / 48.0, 0, 1) * (p.desaturate / 100.0)
            gray = img @ lum_w
            img = img + (gray[..., None] - img) * amt[..., None]
        if p.spill_luma:
            img += ((y0 - img @ lum_w) * (p.spill_luma / 100.0))[..., None]
    # correção de cor
    if p.temperature:
        t = p.temperature / 100.0 * 30
        img[..., 2] += t
        img[..., 0] -= t
    if p.brightness:
        img += p.brightness * 1.28
    if p.fg_contrast:
        c = p.fg_contrast / 100.0
        f = (1 + c) if c >= 0 else 1 / (1 - c)
        img = (img - 128) * f + 128
    if p.saturation != 100:
        gray = img @ lum_w
        img = gray[..., None] + (img - gray[..., None]) * (p.saturation / 100.0)
    img = np.clip(img, 0, 255)
    if p.hue:
        hsv = cv2.cvtColor(img.astype(np.uint8), cv2.COLOR_BGR2HSV)
        hsv[..., 0] = ((hsv[..., 0].astype(np.int16) + int(round(p.hue / 2))) % 180).astype(np.uint8)
        img = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR).astype(np.float32)
    return img


def key_frame_float(frame_bgr, p: KeyParams, px_scale=1.0):
    """Retorna (cor BGR float 0..255, alfa float 0..1)."""
    if not p.enabled:
        return frame_bgr.astype(np.float32), np.ones(frame_bgr.shape[:2], np.float32)
    return process_color(frame_bgr, p), compute_alpha(frame_bgr, p, px_scale)


def to_bgra(color, alpha, bit16=False) -> np.ndarray:
    if bit16:
        out = np.dstack([color * 257.0, alpha * 65535.0])
        return np.clip(out + 0.5, 0, 65535).astype(np.uint16)
    out = np.dstack([color, alpha * 255.0])
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def key_frame(frame_bgr, p: KeyParams, px_scale=1.0) -> np.ndarray:
    return to_bgra(*key_frame_float(frame_bgr, p, px_scale))


def resize_rgba(color, alpha, scale):
    """Redimensiona com alfa pré-multiplicado (evita halos)."""
    if abs(scale - 1.0) < 1e-6:
        return color, alpha
    h, w = alpha.shape
    size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    pm = cv2.resize(color * alpha[..., None], size, interpolation=interp)
    a = np.clip(cv2.resize(alpha, size, interpolation=interp), 0, 1)
    c = np.where(a[..., None] > 1e-4, pm / np.maximum(a[..., None], 1e-4), 0)
    return np.clip(c, 0, 255), a


# --------------------------------------------------------------------------------------
def checkerboard(h, w, size=12) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w]
    board = (((yy // size) + (xx // size)) % 2).astype(np.uint8)
    out = np.where(board[..., None] == 1, 205, 150).astype(np.uint8)
    return np.repeat(out, 3, axis=2)


def render_view(frame_bgr, p: KeyParams, view="Resultado", bg="xadrez", bg_rgb=(0, 0, 0), px_scale=1.0):
    """Imagem BGR uint8 para a pré-visualização."""
    if view == "Original":
        return frame_bgr
    color, alpha = key_frame_float(frame_bgr, p, px_scale)
    if view == "Máscara (alfa)":
        g = (alpha * 255).astype(np.uint8)
        return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
    h, w = alpha.shape
    if bg == "xadrez":
        back = checkerboard(h, w).astype(np.float32)
    else:
        rgb = {"preto": (0, 0, 0), "branco": (255, 255, 255)}.get(bg, bg_rgb)
        back = np.empty((h, w, 3), np.float32)
        back[:] = rgb[::-1]
    out = (color * alpha[..., None] + back * (1 - alpha[..., None])).astype(np.uint8)
    if view == "Lado a lado":
        sep = np.full((h, 4, 3), 40, np.uint8)
        return np.hstack([frame_bgr, sep, out])
    return out


# --------------------------------------------------------------------------------------
def _safe_path(path: str) -> str:
    """No Windows o OpenCV pode falhar com caminhos com acentos; usa nome curto 8.3."""
    if sys.platform.startswith("win"):
        try:
            path.encode("ascii")
        except UnicodeEncodeError:
            import ctypes
            buf = ctypes.create_unicode_buffer(1024)
            if ctypes.windll.kernel32.GetShortPathNameW(path, buf, 1024):
                return buf.value
    return path


def write_png(path: str, img: np.ndarray, compression: int = 3) -> None:
    """Salva PNG (8 ou 16 bits) suportando caminhos Unicode no Windows."""
    ok, data = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, int(compression)])
    if not ok:
        raise IOError(f"Falha ao codificar PNG: {path}")
    data.tofile(path)


class Video:
    def __init__(self, path: str):
        self.path = path
        self.cap = cv2.VideoCapture(_safe_path(path))
        if not self.cap.isOpened():
            raise IOError("Não foi possível abrir o vídeo.")
        self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if self.frame_count <= 0:
            n = 0
            while self.cap.grab():
                n += 1
            self.frame_count = n
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        self._pos = 0

    def read(self, index: int):
        index = max(0, min(index, self.frame_count - 1))
        if index != self._pos:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = self.cap.read()
        self._pos = index + 1 if ok else -1
        return frame if ok else None

    def release(self):
        self.cap.release()


def export_frames(path, out_dir, params: KeyParams, opts: ExportOptions | None = None,
                  progress=None, should_cancel=None):
    """Exporta os quadros como PNG RGBA. Retorna quantos arquivos foram salvos."""
    opts = opts or ExportOptions()
    os.makedirs(out_dir, exist_ok=True)
    v = Video(path)
    n_total = v.frame_count
    start = max(0, min(opts.start, n_total - 1))
    end = n_total - 1 if opts.end < 0 else min(opts.end, n_total - 1)
    step = max(1, int(opts.step))
    expected = max(0, (end - start) // step + 1)
    cap = v.cap
    if start > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    count = 0
    idx = start
    try:
        while idx <= end:
            if should_cancel and should_cancel():
                break
            if (idx - start) % step:
                if not cap.grab():
                    break
                idx += 1
                continue
            ok, frame = cap.read()
            if not ok:
                break
            color, alpha = key_frame_float(frame, params)
            color, alpha = resize_rgba(color, alpha, opts.scale)
            write_png(os.path.join(out_dir, f"{opts.prefix}{count + 1:05d}.png"),
                      to_bgra(color, alpha, opts.bit16), opts.compression)
            count += 1
            idx += 1
            if progress:
                progress(count, max(expected, count))
    finally:
        v.release()
    return count
