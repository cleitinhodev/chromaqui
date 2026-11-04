"""Pincel de retoque da máscara: pinta áreas para MANTER (+) ou REMOVER (−) que entram no alfa.

As camadas são int8 (−127..127) na resolução do vídeo original (lado maior limitado a MAX_SIDE):
uma camada estática (vale para todos os quadros) e camadas opcionais por quadro. A cópia
(`copy.deepcopy`, feita para cada trabalho de renderização/exportação) é rasa e barata: as camadas
são compartilhadas e trocadas por cópias novas no início de cada pincelada (copy-on-write)."""
from __future__ import annotations

import itertools
import threading

import cv2
import numpy as np

MAX_SIDE = 2048
_uid = itertools.count(1)
_cache: dict = {}
_cache_lock = threading.Lock()
_CACHE_MAX = 8


class Retouch:
    def __init__(self, width: int, height: int):
        self.src_w, self.src_h = int(width), int(height)
        k = min(1.0, MAX_SIDE / max(1, self.src_w, self.src_h))
        self.k = k
        self.w, self.h = max(1, int(round(self.src_w * k))), max(1, int(round(self.src_h * k)))
        self.static: np.ndarray | None = None
        self.frames: dict[int, np.ndarray] = {}
        self.uid = next(_uid)
        self.version = 0

    # ----------------------------------------------------------------- cópias
    def __deepcopy__(self, memo):
        c = Retouch.__new__(Retouch)
        c.__dict__.update(self.__dict__)
        c.frames = dict(self.frames)
        return c

    def frozen(self) -> "Retouch":
        """Cópia independente (para exportação em segundo plano)."""
        c = self.__deepcopy__({})
        c.static = None if self.static is None else self.static.copy()
        c.frames = {i: m.copy() for i, m in self.frames.items()}
        return c

    def is_empty(self) -> bool:
        return (self.static is None or not self.static.any()) and not any(m.any() for m in self.frames.values())

    def frame_count(self) -> int:
        return sum(1 for m in self.frames.values() if m.any())

    def clear(self, frame: int | None = None):
        if frame is None:
            self.static, self.frames = None, {}
        else:
            self.frames.pop(int(frame), None)
        self.version += 1

    # ------------------------------------------------------------- camadas
    def layer(self, frame: int | None, create=False):
        """Camada estática (frame=None) ou do quadro `frame`."""
        if frame is None:
            if self.static is None and create:
                self.static = np.zeros((self.h, self.w), np.int8)
            return self.static
        m = self.frames.get(int(frame))
        if m is None and create:
            m = self.frames[int(frame)] = np.zeros((self.h, self.w), np.int8)
        return m

    def begin_stroke(self, frame: int | None):
        """Copy-on-write: trabalhos já enviados continuam vendo a camada antiga."""
        m = self.layer(frame, create=True)
        new = m.copy()
        if frame is None:
            self.static = new
        else:
            self.frames[int(frame)] = new
        return new

    def set_patch(self, frame, box, patch):
        """Restaura um retângulo (desfazer/refazer): box = (x0, y0, x1, y1) na grade da camada."""
        m = self.begin_stroke(frame)
        x0, y0, x1, y1 = box
        m[y0:y1, x0:x1] = patch
        self.version += 1

    def get_patch(self, frame, box):
        m = self.layer(frame)
        x0, y0, x1, y1 = box
        if m is None:
            return np.zeros((y1 - y0, x1 - x0), np.int8)
        return m[y0:y1, x0:x1].copy()

    def dab_box(self, x, y, radius):
        """Retângulo (na grade da camada) afetado por uma pincelada em (x, y) px do original."""
        cx, cy, r = x * self.k, y * self.k, max(0.5, radius * self.k)
        x0, y0 = max(0, int(np.floor(cx - r - 1))), max(0, int(np.floor(cy - r - 1)))
        x1, y1 = min(self.w, int(np.ceil(cx + r + 2))), min(self.h, int(np.ceil(cy + r + 2)))
        return x0, y0, x1, y1

    def dab(self, x, y, radius, hardness=0.5, mode="keep", frame=None, strength=1.0):
        """Uma pincelada circular. mode: "keep" (+), "remove" (−) ou "erase" (volta a 0).
        hardness 0..1 (1 = borda dura). Retorna a caixa alterada (x0, y0, x1, y1) ou None."""
        m = self.layer(frame, create=True)
        x0, y0, x1, y1 = self.dab_box(x, y, radius)
        if x1 <= x0 or y1 <= y0:
            return None
        cx, cy, r = x * self.k, y * self.k, max(0.5, radius * self.k)
        yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        d = np.sqrt((xx + 0.5 - cx) ** 2 + (yy + 0.5 - cy) ** 2) / r
        h = float(np.clip(hardness, 0.0, 0.99))
        t = np.clip((1.0 - d) / max(1e-3, 1.0 - h), 0.0, 1.0)
        prof = t * t * (3 - 2 * t) * float(strength)
        target = {"keep": 127.0, "remove": -127.0}.get(mode, 0.0)
        cur = m[y0:y1, x0:x1].astype(np.float32)
        new = cur + (target - cur) * prof
        m[y0:y1, x0:x1] = np.clip(np.round(new), -127, 127).astype(np.int8)
        self.version += 1
        return x0, y0, x1, y1

    def mask(self, frame: int) -> np.ndarray | None:
        """Camada combinada (estática + do quadro), float32 −1..1, ou None se vazia."""
        st = self.static
        fr = self.frames.get(int(frame)) if frame is not None and frame >= 0 else None
        if st is None and fr is None:
            return None
        if fr is None:
            return st.astype(np.float32) / 127.0
        if st is None:
            return fr.astype(np.float32) / 127.0
        # por quadro tem prioridade onde foi pintado
        return np.where(fr != 0, fr, st).astype(np.float32) / 127.0

    # -------------------------------------------------------------- aplicação
    def _scaled(self, frame, FW, FH):
        fr = int(frame) if frame is not None and frame >= 0 and int(frame) in self.frames else -1
        key = (self.uid, self.version, fr, FW, FH)
        with _cache_lock:
            hit = _cache.get(key)
        if hit is not None:
            return hit
        m = self.mask(frame)
        if m is not None:
            m = cv2.resize(m, (FW, FH), interpolation=cv2.INTER_LINEAR if FW >= self.w else cv2.INTER_AREA)
        with _cache_lock:
            if len(_cache) >= _CACHE_MAX:
                _cache.pop(next(iter(_cache)))
            _cache[key] = m
        return m

    def apply(self, alpha: np.ndarray, frame: int, frame_box=None) -> np.ndarray:
        """alfa (de um quadro inteiro ou de um pedaço dele, ver core.compute_alpha) com o retoque."""
        h, w = alpha.shape
        bx, by, FW, FH = frame_box if frame_box is not None else (0, 0, w, h)
        M = self._scaled(frame, int(FW), int(FH))
        if M is None:
            return alpha
        sub = M[by:by + h, bx:bx + w]
        if sub.shape != alpha.shape:   # borda (arredondamento): completa com 0
            pad = np.zeros_like(alpha)
            pad[:sub.shape[0], :sub.shape[1]] = sub
            sub = pad
        keep = np.maximum(sub, 0)
        rem = np.maximum(-sub, 0)
        a = alpha + keep * (1.0 - alpha)
        return (a * (1.0 - rem)).astype(np.float32)
