"""Chromaqui! — lógica de keying profissional e leitura de vídeo (sem interface)."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field, asdict

import cv2
import numpy as np

from . import gpu

VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".wmv")

PRESETS = {
    "Verde": (0, 177, 64),    # RGB
    "Azul": (0, 71, 187),
}

# --------------------------------------------------------------------------------------
# Definição dos parâmetros: (chave, rótulo, mín, máx, padrão, dica)  agrupados por seção
PARAM_SECTIONS = [
    ("Geração da máscara", [
        ("tolerance", "Tolerância", 0, 100, 20, "Quanto de cores parecidas com a cor-chave será removido."),
        ("edge", "Faixa de transição", 0, 100, 80, "Largura da passagem entre opaco e transparente. Valores altos = bordas mais suaves e naturais (cabelo, desfoque)."),
        ("transparency", "Transparência", 0, 100, 0, "Deixa as áreas semitransparentes mais transparentes."),
        ("highlight", "Realce (luzes)", 0, 100, 0, "Aumenta a opacidade das áreas claras do objeto."),
        ("shadow", "Sombra", 0, 100, 0, "Aumenta a opacidade das áreas escuras do objeto."),
        ("pedestal", "Pedestal", 0, 100, 0, "Remove ruído: valores baixos de alfa viram transparentes."),
    ]),
    ("Qualidade das bordas", [
        ("refine", "Refinar bordas", 0, 100, 70, "Refina a máscara guiada pela imagem (guided filter): bordas lisas, sem serrilhado, preservando fios de cabelo."),
        ("decontam", "Descontaminar bordas", 0, 100, 100, "Remove a cor do fundo misturada nos pixels de borda (sem halo verde/azul)."),
        ("chroma_smooth", "Suavizar croma", 0, 100, 15, "Reduz os 'degraus' causados pela compressão do vídeo (H.264 4:2:0) antes do recorte."),
    ]),
    ("Colorização de bordas", [
        ("cw_enable", "Ativar", 0, 1, 1, "Recolore só as bordas com a cor mais próxima do objeto que não seja a cor-chave (cabelo loiro pega o loiro, pele pega o tom da pele…)."),
        ("cw_amount", "Intensidade", 0, 100, 80, "Quanto a cor das bordas é puxada para a cor do objeto ao lado."),
        ("cw_width", "Largura da borda (px)", 0, 20, 2, "Quantos pixels para dentro da parte opaca também são recoloridos (além da faixa semitransparente)."),
        ("cw_reach", "Alcance da amostragem (px)", 1, 100, 50, "Até que distância da borda a cor do objeto é procurada."),
        ("cw_luma", "Preservar brilho", 0, 100, 100, "100 = mantém o brilho original da borda e troca só a cor (preserva detalhes como fios de cabelo)."),
        ("cw_keyonly", "Só afetar resíduo da cor-chave", 0, 1, 1, "Ligado: só recolore pixels que ainda têm tom da cor-chave (verde/azul). Desligado: recolore toda a borda."),
        ("cw_smooth", "Suavização da cor amostrada", 0, 100, 30, "Média da cor amostrada (menos ruído, transição mais uniforme)."),
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
    compression: int = 3        # 0..9 (PNG)
    fmt: str = "png"            # ver exporters.FORMATS
    fps: float = 0.0            # 0 = automático (fps do vídeo ÷ passo)
    loop: int = 0               # repetições da animação (0 = infinito)
    quality: int = 90           # WebP / WebM (0..100)
    lossless: bool = False      # WebP
    gif_colors: int = 256
    gif_dither: bool = True
    gif_alpha_threshold: int = 128
    gif_palette: str = "alta"   # "rápida" | "alta"
    gif_matte: bool = True      # mistura as bordas semitransparentes com a cor matte
    gif_matte_rgb: tuple = (255, 255, 255)
    include_bg: bool = False    # compõe o fundo (imagem/vídeo) na exportação
    tiff_compress: bool = True
    crop: tuple | None = None   # (x, y, largura, altura) em pixels do vídeo ORIGINAL; None = quadro inteiro
    even: bool = False          # força largura/altura pares na saída recortada


def save_preset(path, params: KeyParams, extra: dict | None = None):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"app": "Chromaqui", "version": 3, **params.to_dict(), **(extra or {})}, f,
                  ensure_ascii=False, indent=2)


def load_preset(path) -> KeyParams:
    with open(path, encoding="utf-8") as f:
        return KeyParams.from_dict(json.load(f))


def load_preset_extra(path) -> dict:
    """Dados extras do preset (ex.: {"crop": {"size": [w, h], "rect": [x, y, w, h]}})."""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return {k: d[k] for k in ("crop",) if k in d}


# --------------------------------------------------------------------------------------
# Recorte da área exportada (em pixels do vídeo original)
CROP_MIN = 2                # menor lado aceito (px)
CROP_PAD = 192              # contexto extra (px do original) processado ao redor do recorte:
                            # filtros de borda/placa limpa/colorização "enxergam" além do recorte
CROP_ALIGN = 8              # região processada alinhada à grade dos desfoques em resolução reduzida
                            # (fator até 8): mesmo resultado do quadro inteiro, sem "costuras"
EVEN_FORMATS = {"webm", "prores"}   # vídeos: dimensões pares obrigatórias (yuv 4:2:0 / 4:4:4)


def full_rect(w, h):
    return (0, 0, int(w), int(h))


def clamp_crop(rect, w, h, min_size=CROP_MIN):
    """Ajusta (x, y, cw, ch) para caber em w×h (inteiros, lado mínimo min_size)."""
    w, h = int(w), int(h)
    x, y, cw, ch = (int(round(float(v))) for v in rect)
    if cw < 0:
        x, cw = x + cw, -cw
    if ch < 0:
        y, ch = y + ch, -ch
    m = min(min_size, w, h)
    cw = max(m, min(cw, w))
    ch = max(m, min(ch, h))
    x = max(0, min(x, w - cw))
    y = max(0, min(y, h - ch))
    return (x, y, cw, ch)


def crop_fits(rect, w, h):
    """True se o recorte salvo cabe (sem ajustes) num vídeo w×h."""
    try:
        x, y, cw, ch = (int(v) for v in rect)
    except (TypeError, ValueError):
        return False
    return x >= 0 and y >= 0 and cw >= CROP_MIN and ch >= CROP_MIN and x + cw <= w and y + ch <= h


def normalize_crop(rect, w, h):
    """Recorte válido ou None (sem recorte / quadro inteiro / inválido)."""
    if rect is None:
        return None
    try:
        r = clamp_crop(rect, w, h)
    except (TypeError, ValueError):
        return None
    return None if r == full_rect(w, h) else r


def even_crop(rect, w, h):
    """Largura/altura pares: cresce 1 px (para a direita/baixo ou esquerda/cima) ou, se não couber, encolhe."""
    x, y, cw, ch = rect
    if cw % 2:
        if x + cw < w:
            cw += 1
        elif x > 0:
            x, cw = x - 1, cw + 1
        elif cw > 2:
            cw -= 1
    if ch % 2:
        if y + ch < h:
            ch += 1
        elif y > 0:
            y, ch = y - 1, ch + 1
        elif ch > 2:
            ch -= 1
    return (x, y, cw, ch)


def export_geometry(w, h, opts: "ExportOptions"):
    """(recorte efetivo ou None, largura de saída, altura de saída) — o mesmo cálculo usado na exportação."""
    s = float(opts.scale)
    crop = normalize_crop(opts.crop, w, h)
    if crop is None:
        return None, max(1, int(round(w * s))), max(1, int(round(h * s)))
    even = bool(opts.even) or opts.fmt in EVEN_FORMATS
    if even:
        crop = even_crop(crop, w, h)
    ow, oh = max(1, int(round(crop[2] * s))), max(1, int(round(crop[3] * s)))
    if even:
        ow -= ow % 2 if ow > 1 else 0
        oh -= oh % 2 if oh > 1 else 0
    return crop, ow, oh


def crop_box_out(crop, w, h, scale, ow, oh):
    """Posição (x, y) do recorte no quadro inteiro já escalado (para recortar o fundo igual)."""
    fw, fh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    x = max(0, min(int(round(crop[0] * scale)), fw - ow))
    y = max(0, min(int(round(crop[1] * scale)), fh - oh))
    return x, y, fw, fh


def key_for_export(frame_bgr, p: "KeyParams", scale=1.0, crop=None, out_size=None, pad=CROP_PAD):
    """Recorte de cor + alfa de um quadro do vídeo, na resolução de saída.
    Com recorte, processa só a região recortada + `pad` px de contexto (mais rápido; bordas iguais
    às do quadro inteiro) e depois corta exatamente a área pedida. O recorte é em pixels do ORIGINAL;
    a escala (Lanczos ao ampliar) vem depois."""
    if crop is None:
        if scale > 1.0:
            # aumenta ANTES do recorte (Lanczos): bordas calculadas na resolução final
            h, w = frame_bgr.shape[:2]
            frame_bgr = gpu.resize(frame_bgr, (int(round(w * scale)), int(round(h * scale))),
                                   interpolation=cv2.INTER_LANCZOS4)
            return key_frame_float(frame_bgr, p, scale)
        color, alpha = key_frame_float(frame_bgr, p)
        return resize_rgba(color, alpha, scale)
    H, W = frame_bgr.shape[:2]
    x, y, cw, ch = crop
    al = CROP_ALIGN
    px0, py0 = max(0, (x - pad) // al * al), max(0, (y - pad) // al * al)
    px1 = min(W, px0 + -(-(x + cw + pad - px0) // al) * al)
    py1 = min(H, py0 + -(-(y + ch + pad - py0) // al) * al)
    sub = frame_bgr[py0:py1, px0:px1]
    ox, oy = x - px0, y - py0
    ow, oh = out_size or (max(1, int(round(cw * scale))), max(1, int(round(ch * scale))))
    if scale > 1.0:
        sw, sh = max(1, int(round((px1 - px0) * scale))), max(1, int(round((py1 - py0) * scale)))
        sub = gpu.resize(np.ascontiguousarray(sub), (sw, sh), interpolation=cv2.INTER_LANCZOS4)
        box = (int(round(px0 * scale)), int(round(py0 * scale)), int(round(W * scale)), int(round(H * scale)))
        color, alpha = key_frame_float(sub, p, scale, frame_box=box)
        sx = max(0, min(int(round(ox * scale)), sw - ow))
        sy = max(0, min(int(round(oy * scale)), sh - oh))
        return (np.ascontiguousarray(color[sy:sy + oh, sx:sx + ow]),
                np.ascontiguousarray(alpha[sy:sy + oh, sx:sx + ow]))
    color, alpha = key_frame_float(np.ascontiguousarray(sub), p, frame_box=(px0, py0, W, H))
    if abs(scale - 1.0) < 1e-6:
        return (np.ascontiguousarray(color[oy:oy + oh, ox:ox + ow]),
                np.ascontiguousarray(alpha[oy:oy + oh, ox:ox + ow]))
    # reduz a região com contexto (origem alinhada) e corta depois: mesma grade de pixels da
    # redução do quadro inteiro (sem deslocamento de meio pixel)
    color, alpha = resize_rgba(color, alpha, scale)
    sh, sw = alpha.shape
    bx, by, _fw, _fh = crop_box_out(crop, W, H, scale, ow, oh)
    sx = max(0, min(bx - int(round(px0 * scale)), sw - ow))
    sy = max(0, min(by - int(round(py0 * scale)), sh - oh))
    return (np.ascontiguousarray(color[sy:sy + oh, sx:sx + ow]),
            np.ascontiguousarray(alpha[sy:sy + oh, sx:sx + ow]))


def auto_crop(video, p: "KeyParams", samples=30, margin=8, max_w=640, threshold=0.1,
              progress=None, should_cancel=None):
    """Caixa que contém o objeto (alfa > limiar) em `samples` quadros espaçados, + margem (px).
    Retorna (x, y, w, h) em pixels do original, ou None se nada for encontrado / cancelado."""
    own = isinstance(video, str)
    v = Video(video) if own else video
    try:
        W, H = v.width, v.height
        if not p.enabled:
            return full_rect(W, H)
        n = max(1, v.frame_count)
        k = max(1, min(int(samples), n))
        idxs = sorted(set(int(round(i * (n - 1) / max(1, k - 1))) for i in range(k)))
        x0 = y0 = None
        x1 = y1 = 0
        kern = np.ones((3, 3), np.uint8)
        for j, i in enumerate(idxs):
            if should_cancel and should_cancel():
                return None
            f = v.read(i)
            if f is None:
                continue
            fh, fw = f.shape[:2]
            sc = min(1.0, max_w / max(1, fw))
            small = cv2.resize(f, (max(1, int(round(fw * sc))), max(1, int(round(fh * sc)))),
                               interpolation=cv2.INTER_AREA) if sc < 1.0 else f
            sc_x, sc_y = small.shape[1] / fw, small.shape[0] / fh
            a = compute_alpha(small, p, sc)
            m = cv2.morphologyEx((a > threshold).astype(np.uint8), cv2.MORPH_OPEN, kern)
            if m.any():
                bx, by, bw, bh = cv2.boundingRect(m)
                fx0, fy0 = int(np.floor(bx / sc_x)), int(np.floor(by / sc_y))
                fx1, fy1 = int(np.ceil((bx + bw) / sc_x)), int(np.ceil((by + bh) / sc_y))
                x0 = fx0 if x0 is None else min(x0, fx0)
                y0 = fy0 if y0 is None else min(y0, fy0)
                x1, y1 = max(x1, fx1), max(y1, fy1)
            if progress:
                progress(j + 1, len(idxs))
        if x0 is None:
            return None
        mg = max(0, int(margin))
        x0, y0 = max(0, x0 - mg), max(0, y0 - mg)
        x1, y1 = min(W, x1 + mg), min(H, y1 + mg)
        return clamp_crop((x0, y0, x1 - x0, y1 - y0), W, H)
    finally:
        if own:
            v.release()


# --------------------------------------------------------------------------------------
def _rgb_to_crcb(rgb):
    px = np.uint8([[list(rgb[::-1])]])
    ycc = cv2.cvtColor(px, cv2.COLOR_BGR2YCrCb)[0, 0].astype(np.float32)
    return ycc[1], ycc[2]


def _smoothstep(e0, e1, x):
    t = np.clip((x - e0) / max(e1 - e0, 1e-6), 0, 1)
    return t * t * (3 - 2 * t)


def _gblur(x, sig):
    """Desfoque gaussiano; para raios grandes calcula em resolução reduzida e amplia
    (mesmo resultado visual, várias vezes mais rápido — usado em campos suaves)."""
    if sig < 5.0:
        return gpu.GaussianBlur(x, (0, 0), sig)
    h, w = x.shape[:2]
    k = int(min(8, sig // 2.5))
    sw, sh = max(1, w // k), max(1, h // k)
    return gpu.gblur_reduced(x, k, sw, sh, max(0.6, np.sqrt(max(sig * sig - k * k / 12.0, 1.0)) / k))


def _box(x, r):
    return cv2.boxFilter(x, -1, (2 * r + 1, 2 * r + 1), borderType=cv2.BORDER_REFLECT)


def guided_filter(guide_bgr01: np.ndarray, src: np.ndarray, r: int, eps: float) -> np.ndarray:
    """Guided filter colorido (He et al. 2010), vetorizado com NumPy + boxFilter do OpenCV.
    guide: HxWx3 float32 0..1; src: HxW float32. Retorna src refinado seguindo as bordas da imagem."""
    I = guide_bgr01
    mI = _box(I, r)
    mp = _box(src, r)
    mIp = _box(I * src[..., None], r)
    cov_Ip = mIp - mI * mp[..., None]
    # matriz de covariância 3x3 por pixel
    var = np.empty(I.shape[:2] + (3, 3), np.float32)
    for i in range(3):
        for j in range(i, 3):
            v = _box(I[..., i] * I[..., j], r) - mI[..., i] * mI[..., j]
            var[..., i, j] = v
            var[..., j, i] = v
    var[..., 0, 0] += eps
    var[..., 1, 1] += eps
    var[..., 2, 2] += eps
    a = np.linalg.solve(var, cov_Ip[..., None])[..., 0]
    b = mp - (a * mI).sum(-1)
    ma = _box(a, r)
    mb = _box(b, r)
    return (ma * I).sum(-1) + mb


def guided_filter_gray(I: np.ndarray, src: np.ndarray, r: int, eps: float) -> np.ndarray:
    """Guided filter (He et al.) com guia em tons de cinza; rápido e vetorizado (GPU se ativa)."""
    return gpu.guided_filter_gray(I, src, r, eps)


def _raw_alpha(frame_bgr, p, px_scale):
    ycc = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2YCrCb).astype(np.float32)
    cr, cb = ycc[..., 1], ycc[..., 2]
    sm = p.values.get("chroma_smooth", 0)
    if sm:
        sigma = 0.3 + sm / 100.0 * 1.7 * max(px_scale, 0.35)
        cr = gpu.GaussianBlur(cr, (0, 0), sigma)
        cb = gpu.GaussianBlur(cb, (0, 0), sigma)
    kcr, kcb = _rgb_to_crcb(p.key_rgb)
    kx, ky = kcr - 128.0, kcb - 128.0
    kn = max(np.hypot(kx, ky), 8.0)
    ux, uy = kx / kn, ky / kn
    cx, cy = cr - 128.0, cb - 128.0
    proj = cx * ux + cy * uy                    # "quanto é fundo" (na direção da cor-chave)
    perp = np.abs(cy * ux - cx * uy)            # desvio de matiz em relação ao fundo
    # Placa limpa local: o fundo real varia de brilho (dobras, luz). Estima a intensidade
    # do fundo ao redor e normaliza, para que fundo mais claro/escuro também seja removido.
    # sementes de fundo: mesma matiz da chave (±~20°), mesmo que mais escuro/claro que a cor escolhida
    bg0 = (proj > 0.3 * kn) & (perp < 0.36 * proj)
    sig = max(6.0, 25.0 * px_scale)
    wsum = _gblur(bg0.astype(np.float32), sig)
    psum = _gblur(np.where(bg0, proj, 0).astype(np.float32), sig)
    local = np.where(wsum > 0.02, psum / np.maximum(wsum, 1e-6), kn)
    local = np.clip(local, 0.3 * kn, 1.6 * kn)
    # Num pixel misturado I = a*F + (1-a)*B, proj cai linearmente com a -> alfa contínuo.
    raw = 1.0 - proj / local + perp / local
    lo = (p.tolerance / 100.0) * 0.8
    width = max(p.edge / 100.0, 0.02)
    return np.clip((raw - lo) / width, 0.0, 1.0).astype(np.float32), ycc


def _color_line_alpha(frame_bgr, a0, px_scale):
    """Estimativa local de cor do objeto (F) e do fundo (B) ao redor de cada pixel de borda e
    alfa pelo modelo de mistura I = a*F + (1-a)*B  ->  a = (I-B)·(F-B) / |F-B|².
    Corrige bordas com desfoque de movimento/fora de foco, onde a cor misturada engana o keyer."""
    I = frame_bgr.astype(np.float32)
    sig = max(3.0, 10.0 * px_scale)
    wF = np.clip((a0 - 0.9) / 0.1, 0, 1)
    wB = np.clip((0.1 - a0) / 0.1, 0, 1)
    dF = _gblur(wF, sig)
    dB = _gblur(wB, sig)
    F = _gblur(I * wF[..., None], sig) / np.maximum(dF, 1e-4)[..., None]
    B = _gblur(I * wB[..., None], sig) / np.maximum(dB, 1e-4)[..., None]
    d = F - B
    n2 = (d * d).sum(-1)
    acl = np.clip(((I - B) * d).sum(-1) / np.maximum(n2, 1.0), 0, 1)
    distF = np.sqrt(((I - F) ** 2).sum(-1))
    distB = np.sqrt(((I - B) ** 2).sum(-1))
    noise = 14.0
    mixed = (dF > 0.03) & (dB > 0.03) & (n2 > 35.0 ** 2) & (distF > noise) & (distB > noise)
    return np.where(mixed, acl, a0).astype(np.float32)


def compute_alpha(frame_bgr, p: KeyParams, px_scale: float = 1.0, frame_box=None) -> np.ndarray:
    """Máscara alfa contínua (float32 0..1) na resolução do quadro.
    px_scale = fator de escala do quadro em relação ao original (para raios de filtros).
    frame_box = (x, y, largura, altura do quadro inteiro) quando `frame_bgr` é só um pedaço do quadro
    (exportação recortada): o garbage matte em % continua relativo ao quadro inteiro."""
    a, ycc = _raw_alpha(frame_bgr, p, px_scale)
    if p.values.get("refine", 0):
        a = _color_line_alpha(frame_bgr, a, px_scale)
    ref = p.values.get("refine", 0)
    if ref:
        # Vídeos H.264/HEVC guardam a cor (croma) em meia resolução (4:2:0), o que gera
        # bordas em "escadinha". O guided filter guiado pela LUMA (resolução total) transfere
        # os detalhes finos (fios de cabelo, contornos) para a máscara.
        s_ = ref / 100.0
        r = max(1, int(round(px_scale * (1 + 1.5 * max(0.0, s_ - 0.5)))))
        eps = 10 ** (-2.4 - 1.6 * s_)
        y = ycc[..., 0] / 255.0
        g = guided_filter_gray(y, a, r, eps)
        a = np.clip(a + (g - a) * min(1.0, s_ * 1.6), 0, 1)
        a[a < 0.006] = 0
        a[a > 0.994] = 1
    luma = ycc[..., 0] / 255.0

    if p.transparency:
        a = a ** (1.0 + p.transparency / 25.0)
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
            a = gpu.GaussianBlur(a, (0, 0), sigma)
    if p.contrast or p.midpoint != 50:
        k = 1.0 + p.contrast / 100.0 * 15
        a = np.clip(0.5 + (a - p.midpoint / 100.0) * k, 0, 1)

    # --- recorte (garbage matte, em % do quadro inteiro)
    h, w = a.shape
    bx, by, FW, FH = frame_box if frame_box is not None else (0, 0, w, h)
    ct, cb = int(FH * p.crop_top / 100), int(FH * p.crop_bottom / 100)
    cl, cr = int(FW * p.crop_left / 100), int(FW * p.crop_right / 100)
    if ct: a[:max(0, ct - by)] = 0
    if cb: a[max(0, FH - cb - by):] = 0
    if cl: a[:, :max(0, cl - bx)] = 0
    if cr: a[:, max(0, FW - cr - bx):] = 0
    return a.astype(np.float32)


def decontaminate(img, alpha, key_rgb, amount, px_scale=1.0):
    """Estima a cor real do objeto nas bordas: F = (I - (1-a)*B) / a, onde B é o fundo local
    (média do fundo puro ao redor; usa a cor-chave onde não há fundo próximo)."""
    if amount <= 0:
        return img
    wb = (1.0 - alpha) ** 4
    sig = max(2.0, 8.0 * px_scale)
    num = _gblur(img * wb[..., None], sig)
    den = _gblur(wb, sig)[..., None]
    key = np.array(key_rgb[::-1], np.float32)[None, None]
    B = np.where(den > 1e-3, num / np.maximum(den, 1e-3), key)
    a = alpha[..., None]
    F = (img - (1 - a) * B) / np.maximum(a, 0.12)
    F = np.clip(F, 0, 255)
    w = (amount / 100.0) * (a < 0.999)
    return img + (F - img) * w


def _key_excess(img, key_rgb):
    key = np.array(key_rgb[::-1], np.float32)
    dom = int(np.argmax(key))
    o1, o2 = [c for c in range(3) if c != dom]
    return img[..., dom] - np.maximum(img[..., o1], img[..., o2])


def key_residual(img, key_rgb):
    """0..1: quanto o pixel ainda tem do tom da cor-chave (excesso do canal dominante)."""
    key = np.array(key_rgb[::-1], np.float32)
    dom = int(np.argmax(key))
    o1, o2 = [c for c in range(3) if c != dom]
    kex = max(float(key[dom] - max(key[o1], key[o2])), 30.0)
    ex = img[..., dom] - np.maximum(img[..., o1], img[..., o2])
    return np.clip(ex / (0.35 * kex), 0, 1).astype(np.float32)


_LUM = np.array([0.114, 0.587, 0.299], np.float32)  # pesos BGR


def _propagate(img, alpha, ks, width, sm, px_scale, d_in=None):
    """Cor da fonte mais próxima (pixel interno confiável, sem cor-chave) para cada pixel.
    Retorna (cor propagada BGR, distância até a fonte em px) ou None se não houver fontes."""
    h, w = alpha.shape
    if d_in is None:
        d_in = cv2.distanceTransform((alpha > 0.98).astype(np.uint8), cv2.DIST_L2, 3)
    src = (alpha > 0.95) & (ks < 0.12) & (d_in > width + 0.5)
    if not src.any():
        return None
    srcf = src.astype(np.float32)
    col = img
    if sm > 0:   # cor de cada fonte = média local das fontes (suavização da cor amostrada)
        sg = 0.5 + sm * 4.0 * max(px_scale, 0.5)
        num = gpu.GaussianBlur(img * srcf[..., None], (0, 0), sg)
        den = gpu.GaussianBlur(srcf, (0, 0), sg)[..., None]
        col = np.where(den > 1e-4, num / np.maximum(den, 1e-4), img)
    dist, lab = cv2.distanceTransformWithLabels((~src).astype(np.uint8), cv2.DIST_L2, 5,
                                                labelType=cv2.DIST_LABEL_PIXEL)
    ys, xs = np.nonzero(src)
    lut = np.zeros(int(lab.max()) + 1, np.int64)
    lut[lab[ys, xs]] = ys * w + xs
    P = np.ascontiguousarray(col.reshape(-1, 3)[lut[lab]])
    if sm > 0:
        P = gpu.GaussianBlur(P, (0, 0), 0.5 + sm * 2.0 * max(px_scale, 0.5))
    return P.astype(np.float32), dist.astype(np.float32)


def colorize_edges(img, alpha, p: KeyParams, px_scale=1.0):
    """Colorização de bordas: leva a cor do objeto (pixels internos confiáveis, sem tom da
    cor-chave) até a faixa de borda e mistura com a cor da borda.
    Retorna (imagem, peso 0..1 aplicado por pixel)."""
    h, w = alpha.shape
    amount = p.values.get("cw_amount", 0) / 100.0
    if amount <= 0:
        return img, np.zeros((h, w), np.float32)
    width = p.values.get("cw_width", 2) * px_scale
    reach = max(1.0, p.values.get("cw_reach", 50) * px_scale)
    ks = key_residual(img, p.key_rgb)
    opaque = (alpha > 0.98).astype(np.uint8)
    # distância (px) de cada pixel opaco até a parte não opaca
    d_in = cv2.distanceTransform(opaque, cv2.DIST_L2, 3)
    semi = (alpha > 0.004) & (alpha <= 0.98)
    edge_w = np.where(semi, 1.0, np.clip(1.0 - (d_in - width) / max(1.0, px_scale), 0, 1) * opaque)
    edge_w = edge_w.astype(np.float32)
    if not edge_w.any():
        return img, np.zeros((h, w), np.float32)
    sm = p.values.get("cw_smooth", 30) / 100.0
    if px_scale > 1.5:
        # cor propagada é um campo suave: calcula em resolução menor (rápido em 2x/4x) e amplia
        f = 1.0 / px_scale
        sz = (max(1, int(round(w * f))), max(1, int(round(h * f))))
        im_s = gpu.resize(img, sz, interpolation=cv2.INTER_AREA)
        a_s = gpu.resize(alpha, sz, interpolation=cv2.INTER_AREA)
        r = _propagate(im_s, a_s, key_residual(im_s, p.key_rgb), width * f, sm, 1.0)
        if r is None:
            return img, np.zeros((h, w), np.float32)
        P = gpu.resize(r[0], (w, h), interpolation=cv2.INTER_LINEAR)
        dist = gpu.resize(r[1], (w, h), interpolation=cv2.INTER_LINEAR) * px_scale
    else:
        r = _propagate(img, alpha, ks, width, sm, px_scale, d_in)
        if r is None:
            return img, np.zeros((h, w), np.float32)
        P, dist = r
    # peso: borda × intensidade × alcance (× resíduo da cor-chave)
    wgt = edge_w * amount * np.clip(1.0 + (reach - dist) / max(2.0, 0.25 * reach), 0, 1)
    if p.values.get("cw_keyonly", 1):
        # só onde o pixel difere da cor do objeto no eixo da cor-chave: resíduo verde/azul
        # (ou o excesso oposto, magenta, deixado pela descontaminação); ≥ ~5 níveis = peso total
        dev = np.abs(_key_excess(img, p.key_rgb) - _key_excess(P, p.key_rgb))
        wgt = wgt * np.clip((dev - 2.0) / 6.0, 0, 1)
    lumk = p.values.get("cw_luma", 100) / 100.0
    if lumk > 0:
        dy = (img @ _LUM) - (P @ _LUM)
        P = P + (dy * lumk)[..., None]
    out = img + (np.clip(P, 0, 255) - img) * wgt[..., None]
    return out.astype(np.float32), wgt.astype(np.float32)


def process_color(frame_bgr, p: KeyParams, alpha=None, px_scale=1.0, debug=None) -> np.ndarray:
    """Descontaminação + colorização de bordas + supressão de spill + correção de cor.
    Retorna BGR float32 0..255."""
    img = frame_bgr.astype(np.float32)
    if alpha is not None and p.values.get("decontam", 0):
        img = decontaminate(img, alpha, p.key_rgb, p.decontam, px_scale)
    if alpha is not None and p.values.get("cw_enable", 0):
        img, cw = colorize_edges(img, alpha, p, px_scale)
        if debug is not None:
            debug["cw"] = cw
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


def key_frame_float(frame_bgr, p: KeyParams, px_scale=1.0, frame_box=None):
    """Retorna (cor BGR float 0..255, alfa float 0..1)."""
    if not p.enabled:
        return frame_bgr.astype(np.float32), np.ones(frame_bgr.shape[:2], np.float32)
    alpha = compute_alpha(frame_bgr, p, px_scale, frame_box)
    return process_color(frame_bgr, p, alpha, px_scale), alpha


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
    pm = gpu.resize(color * alpha[..., None], size, interpolation=interp)
    a = np.clip(gpu.resize(alpha, size, interpolation=interp), 0, 1)
    c = np.where(a[..., None] > 1e-4, pm / np.maximum(a[..., None], 1e-4), 0)
    return np.clip(c, 0, 255), a


# --------------------------------------------------------------------------------------
def checkerboard(h, w, size=12) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w]
    board = (((yy // size) + (xx // size)) % 2).astype(np.uint8)
    out = np.where(board[..., None] == 1, 205, 150).astype(np.uint8)
    return np.repeat(out, 3, axis=2)


def render_view(frame_bgr, p: KeyParams, view="Resultado", bg="xadrez", bg_rgb=(0, 0, 0), px_scale=1.0,
                bg_img=None):
    """Imagem BGR uint8 para a pré-visualização. bg_img: fundo BGR (h,w,3) opcional."""
    if view == "Original":
        return frame_bgr
    if not p.enabled:
        color, alpha = key_frame_float(frame_bgr, p, px_scale)
    else:
        alpha = compute_alpha(frame_bgr, p, px_scale)
        dbg = {}
        color = process_color(frame_bgr, p, alpha, px_scale, debug=dbg)
    if view == "Máscara (alfa)":
        g = (alpha * 255).astype(np.uint8)
        return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
    if view == "Máscara da colorização":
        # objeto escurecido em cinza + área afetada em magenta (mais forte = mais colorizado)
        cw = dbg.get("cw") if p.enabled else None
        base = (frame_bgr.astype(np.float32) @ _LUM) * alpha * 0.45
        out = np.repeat(base[..., None], 3, axis=2)
        if cw is not None:
            k = np.clip(cw / max(p.values.get("cw_amount", 70) / 100.0, 1e-3), 0, 1)[..., None]
            out = out * (1 - k) + np.array([255, 40, 255], np.float32) * k
        return np.clip(out, 0, 255).astype(np.uint8)
    h, w = alpha.shape
    if bg_img is not None and bg_img.shape[:2] == (h, w):
        back = bg_img.astype(np.float32)
    elif bg == "xadrez":
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


class Playback:
    """Lógica de reprodução (sem interface): decodifica em sequência (sem 'seek' a cada quadro),
    mantém o ritmo do FPS escolhido e descarta quadros quando o processamento fica lento."""

    def __init__(self, video, start=0, fps=None, loop=True, clock=time.perf_counter):
        self.video = Video(video) if isinstance(video, str) else video
        self.fps = float(fps or self.video.fps or 30.0)
        self.loop = loop
        self.clock = clock
        self.seeks = self.dropped = self.shown = self.decoded = 0
        self._times = deque()
        self._pending = None
        self._seek_to(start)

    def _seek_to(self, idx):
        idx = max(0, min(int(idx), self.video.frame_count - 1))
        self.video.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        self.seeks += 1
        self.idx = idx
        self.t0, self.n = self.clock(), 0

    def seek(self, idx):
        """Pula para um quadro (pode ser chamado de outra thread)."""
        self._pending = idx

    def set_fps(self, fps):
        self.fps = max(0.1, float(fps))
        self.t0, self.n = self.clock(), 0

    def next_frame(self):
        """Retorna (índice, quadro BGR) do próximo quadro a mostrar, ou None no fim (sem repetir)."""
        if self._pending is not None:
            idx, self._pending = self._pending, None
            self._seek_to(idx)
        fc = self.video.frame_count
        due = int((self.clock() - self.t0) * self.fps)       # quadro que já deveria estar na tela
        behind = due - self.n
        if behind > self.fps:                                 # atraso grande: reancora o relógio
            self.t0 = self.clock() - self.n / self.fps
            behind = int(self.fps)
        for _ in range(max(0, behind)):                       # descarta quadros atrasados
            if self.idx >= fc - 1:
                break
            if not self.video.cap.grab():
                break
            self.idx += 1
            self.n += 1
            self.dropped += 1
        for _attempt in range(2):
            if self.idx >= fc:
                if not self.loop:
                    return None
                self._seek_to(0)
            ok, frame = self.video.cap.read()
            if ok:
                break
            if not self.loop or self.idx == 0:
                return None
            self.idx = fc                                     # fim real antes do previsto
        else:
            return None
        self.decoded += 1
        i = self.idx
        self.idx += 1
        self.n += 1
        return i, frame

    def wait_time(self):
        """Segundos até a hora de mostrar o quadro já decodificado."""
        return max(0.0, self.t0 + self.n / self.fps - self.clock())

    def mark_shown(self):
        now = self.clock()
        self.shown += 1
        self._times.append(now)
        while self._times and now - self._times[0] > 1.0:
            self._times.popleft()

    @property
    def actual_fps(self):
        t = self._times
        return (len(t) - 1) / (t[-1] - t[0]) if len(t) >= 2 and t[-1] > t[0] else 0.0

    def release(self):
        self.video.release()


class Background:
    """Fundo de teste (imagem ou vídeo) para a pré-visualização e, opcionalmente, exportação."""
    MODES = ("fill", "fit", "stretch")

    def __init__(self):
        self.kind = None          # None | "image" | "video"
        self.path = ""
        self.mode = "fill"
        self.fill_rgb = (0, 0, 0)
        self._img = None
        self._video = None
        self._cache = None
        self._lock = threading.Lock()

    @property
    def active(self):
        return self.kind is not None

    def clone(self):
        """Cópia independente (para exportar em outra thread)."""
        b = Background()
        if self.active:
            b.load(self.path)
        b.mode, b.fill_rgb = self.mode, self.fill_rgb
        return b

    def clear(self):
        with self._lock:
            if self._video:
                self._video.release()
            self.kind, self.path, self._img, self._video, self._cache = None, "", None, None, None

    def load(self, path: str):
        ext = os.path.splitext(path)[1].lower()
        v = img = None
        if ext in VIDEO_EXTS:
            v = Video(path)
            if v.frame_count <= 0:
                v.release()
                raise IOError("Vídeo de fundo vazio.")
        else:
            img = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                raise IOError("Não foi possível abrir a imagem.")
        self.clear()
        with self._lock:
            self._video, self._img = v, img
            self.kind = "video" if v is not None else "image"
            self.path = path

    def _source(self, idx):
        if self.kind == "image":
            return self._img, 0
        n = max(1, self._video.frame_count)
        j = idx % n
        return self._video.read(j), j

    def frame(self, idx: int, w: int, h: int):
        """Fundo BGR uint8 do tamanho pedido (ou None)."""
        if not self.active:
            return None
        with self._lock:
            return self._frame(idx, w, h)

    def _frame(self, idx, w, h):
        key = (self.kind, idx if self.kind == "video" else 0, w, h, self.mode)
        if self._cache and self._cache[0] == key:
            return self._cache[1]
        src, _ = self._source(idx)
        if src is None:
            return None
        out = fit_image(src, w, h, self.mode, self.fill_rgb)
        self._cache = (key, out)
        return out


def fit_image(src, w, h, mode="fill", fill_rgb=(0, 0, 0)):
    sh, sw = src.shape[:2]
    if mode == "stretch":
        return cv2.resize(src, (w, h), interpolation=cv2.INTER_AREA if sw > w else cv2.INTER_LINEAR)
    s = max(w / sw, h / sh) if mode == "fill" else min(w / sw, h / sh)
    nw, nh = max(1, int(round(sw * s))), max(1, int(round(sh * s)))
    r = cv2.resize(src, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
    if mode == "fill":
        x0, y0 = (nw - w) // 2, (nh - h) // 2
        return np.ascontiguousarray(r[y0:y0 + h, x0:x0 + w])
    out = np.empty((h, w, 3), np.uint8)
    out[:] = fill_rgb[::-1]
    x0, y0 = (w - nw) // 2, (h - nh) // 2
    out[y0:y0 + nh, x0:x0 + nw] = r
    return out


def export_frames(path, out_dir, params: KeyParams, opts: ExportOptions | None = None,
                  progress=None, should_cancel=None, background=None):
    """Compatibilidade: exporta (PNG por padrão). Ver exporters.export."""
    from .exporters import export
    return export(path, out_dir, params, opts, progress, should_cancel, background)["count"]
