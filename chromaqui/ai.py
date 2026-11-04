"""Remoção de fundo por IA (vídeos sem tela verde): segmentação com onnxruntime.

O modelo NÃO vem no executável: é baixado no primeiro uso para %APPDATA%\\Chromaqui\\models (Windows)
ou ~/.local/share/Chromaqui/models, conferido por SHA-256, e depois funciona offline.
O alfa da IA substitui o alfa "bruto" da cor-chave; refinamento de borda, limpeza (encolher, suavizar,
contraste), retoque e garbage matte continuam valendo."""
from __future__ import annotations

import hashlib
import os
import sys
import threading
import urllib.request
from collections import OrderedDict

import cv2
import numpy as np

# Modelos pequenos (licenças Apache-2.0). URLs fixadas numa revisão + SHA-256.
MODELS = {
    "modnet": {
        "label": "Pessoas — MODNet (26 MB)",
        "file": "modnet_portrait.onnx",
        "url": "https://huggingface.co/Xenova/modnet/resolve/fa2fa546052fba4c08921230a26cc69a333fca12/onnx/model.onnx",
        "sha256": "07c308cf0fc7e6e8b2065a12ed7fc07e1de8febb7dc7839d7b7f15dd66584df9",
        "size": 25888640,
        "kind": "modnet",
    },
    "u2netp": {
        "label": "Objetos — U²-Net pequeno (4,6 MB)",
        "file": "u2netp.onnx",
        "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx",
        "sha256": "309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8",
        "size": 4574861,
        "kind": "u2net",
    },
}


class AIError(Exception):
    pass


def models_dir() -> str:
    d = os.environ.get("CHROMAQUI_MODELS_DIR")
    if not d:
        if sys.platform.startswith("win"):
            d = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Chromaqui", "models")
        else:
            d = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
                             "Chromaqui", "models")
    return d


def model_path(name: str) -> str:
    return os.path.join(models_dir(), MODELS[name]["file"])


def runtime_available() -> bool:
    try:
        import onnxruntime  # noqa: F401
        return True
    except Exception:
        return False


def is_downloaded(name: str) -> bool:
    if name not in MODELS:
        return False
    p = model_path(name)
    return os.path.isfile(p) and os.path.getsize(p) == MODELS[name]["size"]


def is_ready(name: str) -> bool:
    return is_downloaded(name) and runtime_available()


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def download(name: str, progress=None, should_cancel=None, timeout=30) -> str:
    """Baixa o modelo (progress(bytes, total)). Retorna o caminho; AIError se falhar/cancelar."""
    if name not in MODELS:
        raise AIError(f"modelo desconhecido: {name}")
    m = MODELS[name]
    dst = model_path(name)
    if is_downloaded(name):
        return dst
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".part"
    try:
        req = urllib.request.Request(m["url"], headers={"User-Agent": "Chromaqui"})
        with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or m["size"])
            got = 0
            while True:
                if should_cancel and should_cancel():
                    raise AIError("cancelado")
                b = r.read(1 << 16)
                if not b:
                    break
                f.write(b)
                got += len(b)
                if progress:
                    progress(got, total)
        if _sha256(tmp) != m["sha256"]:
            raise AIError("arquivo baixado está corrompido (SHA-256 não confere)")
        os.replace(tmp, dst)
        return dst
    except AIError:
        raise
    except Exception as e:  # rede, disco, HTTP...
        raise AIError(str(e) or e.__class__.__name__) from e
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


# ---------------------------------------------------------------------- inferência
_sessions: dict = {}
_lock = threading.Lock()
_cache: OrderedDict = OrderedDict()
_CACHE_MAX = 12


def session(name: str):
    with _lock:
        s = _sessions.get(name)
        if s is None:
            if not is_downloaded(name):
                raise AIError("modelo não baixado")
            import onnxruntime as ort
            so = ort.SessionOptions()
            so.log_severity_level = 3
            s = ort.InferenceSession(model_path(name), so, providers=["CPUExecutionProvider"])
            _sessions[name] = s
        return s


def _run_modnet(s, rgb):
    h, w = rgb.shape[:2]
    sc = 512.0 / max(1, min(h, w))      # lado menor = 512 (resolução de treino do MODNet)
    nh = max(32, int(round(h * sc / 32)) * 32)
    nw = max(32, int(round(w * sc / 32)) * 32)
    x = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_AREA).astype(np.float32) / 127.5 - 1.0
    y = s.run(None, {s.get_inputs()[0].name: x.transpose(2, 0, 1)[None]})[0][0, 0]
    return y


def _run_u2net(s, rgb):
    x = cv2.resize(rgb, (320, 320), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
    y = s.run(None, {s.get_inputs()[0].name: x.transpose(2, 0, 1)[None].astype(np.float32)})[0][0, 0]
    mn, mx = float(y.min()), float(y.max())
    return (y - mn) / max(mx - mn, 1e-6)


def predict(frame_bgr: np.ndarray, name: str = "modnet") -> np.ndarray:
    """Alfa float32 0..1 do tamanho do quadro. Resultado em cache (mudar controles não reprocessa)."""
    h, w = frame_bgr.shape[:2]
    small = np.ascontiguousarray(frame_bgr[::7, ::7])
    key = (name, h, w, hashlib.blake2b(small.tobytes(), digest_size=16).digest())
    with _lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
            return hit
    s = session(name)
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    y = _run_modnet(s, rgb) if MODELS[name]["kind"] == "modnet" else _run_u2net(s, rgb)
    a = np.clip(cv2.resize(y.astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR), 0, 1)
    a.setflags(write=False)
    with _lock:
        _cache[key] = a
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return a
