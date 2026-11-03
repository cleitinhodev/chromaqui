"""Aceleração por placa de vídeo via OpenCV OpenCL (T-API / cv2.UMat).

Funciona em placas comuns no Windows (NVIDIA, AMD, Intel) sem CUDA, usando o driver
OpenCL da placa. Se não houver OpenCL, ou se o teste de conferência falhar, volta para a
CPU automaticamente (nunca quebra o programa)."""
from __future__ import annotations

import threading

import cv2
import numpy as np

MODES = ("auto", "cpu", "gpu")
MIN_ELEMS = 120_000            # imagens pequenas: CPU é mais rápida (custo de envio p/ GPU)
_lock = threading.Lock()
_state = {"mode": "auto", "enabled": False, "device": "", "reason": ""}


def _device_info():
    try:
        d = cv2.ocl.Device.getDefault()
        t = int(d.type())
        kind = "GPU" if t & cv2.ocl.DEVICE_TYPE_GPU else "CPU" if t & cv2.ocl.DEVICE_TYPE_CPU else "outro"
        return d.name().strip(), kind
    except Exception:  # noqa: BLE001
        return "", ""


def _self_check():
    """Confere se o OpenCL dá o mesmo resultado que a CPU (driver bugado = desliga)."""
    rng = np.random.default_rng(0)
    x = rng.random((96, 128, 3), dtype=np.float32) * 255
    ref = cv2.GaussianBlur(x, (0, 0), 3.0)
    got = cv2.GaussianBlur(cv2.UMat(x), (0, 0), 3.0).get()
    rs = cv2.resize(cv2.UMat(x), (64, 48), interpolation=cv2.INTER_AREA).get()
    return float(np.abs(ref - got).max()) < 0.05 and rs.shape == (48, 64, 3)


def set_mode(mode: str) -> dict:
    """mode: 'auto' (usa GPU de verdade se houver), 'cpu', ou 'gpu' (qualquer dispositivo OpenCL)."""
    mode = mode if mode in MODES else "auto"
    with _lock:
        _state.update(mode=mode, enabled=False, device="", reason="")
        if mode == "cpu":
            _state["reason"] = "CPU escolhida"
        else:
            try:
                if not cv2.ocl.haveOpenCL():
                    raise RuntimeError("OpenCL indisponível")
                cv2.ocl.setUseOpenCL(True)
                if not cv2.ocl.useOpenCL():
                    raise RuntimeError("nenhum dispositivo OpenCL utilizável")
                name, kind = _device_info()
                if mode == "auto" and kind != "GPU":
                    raise RuntimeError(f"sem placa de vídeo OpenCL ({kind or '?'})")
                if not _self_check():
                    raise RuntimeError("teste de conferência falhou")
                _state.update(enabled=True, device=f"{name} ({kind})")
            except Exception as e:  # noqa: BLE001
                _state["reason"] = str(e)
        try:
            cv2.ocl.setUseOpenCL(_state["enabled"])
        except Exception:  # noqa: BLE001
            pass
        return dict(_state)


def enabled() -> bool:
    return _state["enabled"]


def status() -> dict:
    return dict(_state)


def describe() -> str:
    s = _state
    return f"GPU — OpenCL: {s['device']}" if s["enabled"] else f"CPU ({s['reason']})" if s["reason"] else "CPU"


def _use(x) -> bool:
    return _state["enabled"] and getattr(x, "size", 0) >= MIN_ELEMS


# ---- operações aceleradas (mesma assinatura do OpenCV; entrada/saída numpy) ----------
def GaussianBlur(x, ksize, sig):
    if _use(x):
        try:
            return cv2.GaussianBlur(cv2.UMat(np.ascontiguousarray(x)), ksize, sig).get()
        except cv2.error:
            pass
    return cv2.GaussianBlur(x, ksize, sig)


def resize(x, size, interpolation=cv2.INTER_LINEAR):
    if _use(x):
        try:
            return cv2.resize(cv2.UMat(np.ascontiguousarray(x)), size, interpolation=interpolation).get()
        except cv2.error:
            pass
    return cv2.resize(x, size, interpolation=interpolation)


def gblur_reduced(x, k, sw, sh, sig_small):
    """reduz -> desfoca -> amplia, tudo na GPU (um envio e uma leitura)."""
    h, w = x.shape[:2]
    if _use(x):
        try:
            u = cv2.UMat(np.ascontiguousarray(x))
            u = cv2.resize(u, (sw, sh), interpolation=cv2.INTER_AREA)
            u = cv2.GaussianBlur(u, (0, 0), sig_small)
            return cv2.resize(u, (w, h), interpolation=cv2.INTER_LINEAR).get()
        except cv2.error:
            pass
    small = cv2.resize(x, (sw, sh), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), sig_small)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def guided_filter_gray(I, src, r, eps):
    """Guided filter (He et al.) com guia cinza; na GPU encadeia tudo em UMat."""
    k = (2 * r + 1, 2 * r + 1)
    if _use(I):
        try:
            box = lambda z: cv2.boxFilter(z, -1, k, borderType=cv2.BORDER_REFLECT)  # noqa: E731
            Iu, pu = cv2.UMat(np.ascontiguousarray(I)), cv2.UMat(np.ascontiguousarray(src))
            mI, mp = box(Iu), box(pu)
            cov = cv2.subtract(box(cv2.multiply(Iu, pu)), cv2.multiply(mI, mp))
            var = cv2.subtract(box(cv2.multiply(Iu, Iu)), cv2.multiply(mI, mI))
            A = cv2.divide(cov, cv2.add(var, float(eps)))
            B = cv2.subtract(mp, cv2.multiply(A, mI))
            return cv2.add(cv2.multiply(box(A), Iu), box(B)).get()
        except cv2.error:
            pass
    box = lambda z: cv2.boxFilter(z, -1, k, borderType=cv2.BORDER_REFLECT)  # noqa: E731
    mI, mp = box(I), box(src)
    cov = box(I * src) - mI * mp
    var = box(I * I) - mI * mI
    A = cov / (var + eps)
    B = mp - A * mI
    return box(A) * I + box(B)
