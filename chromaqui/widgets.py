"""Workers (threads) e widgets básicos da interface."""
from __future__ import annotations

import sys
import threading
import time

import cv2
import numpy as np
from PySide6.QtCore import QEasingCurve, QMargins, QObject, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QSlider,
                               QSpinBox, QToolButton, QVBoxLayout, QWidget)

from . import core
from .exporters import export
from .fx import FX
from .i18n import T

THUMB_H = 72
PREVIEW_MAX_W = 960
PLAY_QUALITY = [("Rápida", 480), ("Média", 720), ("Completa", PREVIEW_MAX_W)]


def bgr_to_qimage(bgr: np.ndarray) -> QImage:
    rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()


def preview_frame(f, max_w=PREVIEW_MAX_W):
    """Reduz o quadro para a prévia. Retorna (quadro, px_scale)."""
    h, w = f.shape[:2]
    if w > max_w:
        sc = max_w / w
        return cv2.resize(f, (max_w, max(1, int(h * sc))), interpolation=cv2.INTER_AREA), sc
    return f, 1.0


def render_job(frame, idx, job, px_scale):
    """job = (params, view, bg, bg_rgb, background|None)"""
    params, view, bg, bg_rgb, background = job
    bg_img = None
    if background is not None and background.active and view in ("Resultado", "Lado a lado"):
        h, w = frame.shape[:2]
        bg_img = background.frame(idx, w, h)
    return core.render_view(frame, params, view, bg, bg_rgb, px_scale, bg_img=bg_img)


# ============================================================ workers
class ThumbWorker(QObject):
    thumb = Signal(int, QImage)
    done = Signal()

    def __init__(self, path, indices):
        super().__init__()
        self.path, self.indices, self._stop = path, indices, False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            v = core.Video(self.path)
            for idx in self.indices:
                if self._stop:
                    break
                f = v.read(idx)
                if f is None:
                    continue
                h, w = f.shape[:2]
                small = cv2.resize(f, (max(1, int(w * THUMB_H / h)), THUMB_H), interpolation=cv2.INTER_AREA)
                self.thumb.emit(idx, bgr_to_qimage(small))
            v.release()
        finally:
            self.done.emit()


class RenderWorker(QObject):
    """Processa a pré-visualização fora da thread da interface; só o pedido mais recente."""
    request = Signal()
    result = Signal(QImage, float)          # imagem, tempo (ms)

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._pending = None
        self.request.connect(self._process)

    def submit(self, job):
        with self._lock:
            self._pending = job
        self.request.emit()

    def _process(self):
        with self._lock:
            job, self._pending = self._pending, None
        if job is None:
            return
        frame, idx, j, px_scale = job
        try:
            t = time.perf_counter()
            img = render_job(frame, idx, j, px_scale)
            self.result.emit(bgr_to_qimage(img), (time.perf_counter() - t) * 1000)
        except Exception:  # noqa: BLE001
            from . import crashlog
            crashlog.log_exception("Erro na pré-visualização")


class PlaybackWorker(QObject):
    """Reproduz o vídeo com o recorte aplicado, numa thread própria (decodificação sequencial).

    Regras de segurança: a thread tem o próprio VideoCapture; só a thread da interface mexe em widgets
    (aqui só emitimos QImage já copiada); no máximo 1 quadro "em voo" — se a interface ainda não mostrou
    o anterior, o novo é descartado em vez de ir para uma fila (que cresceria sem limite em resolução alta);
    a qualidade (largura máxima) pode mudar a qualquer momento sem reiniciar a thread."""
    frame = Signal(int, int, object, float, QImage, float, int)  # geração, idx, quadro, px_scale, imagem, fps, descartados
    finished = Signal()

    def __init__(self, path, start, fps, loop, job, max_w=480, gen=0):
        super().__init__()
        self.gen = gen
        self.path, self.start, self.fps, self.loop = path, start, fps, loop
        self.max_w = int(max_w)
        self._job = job
        self._lock = threading.Lock()
        self._stop = False
        self._free = threading.Event()
        self._free.set()
        self.pb = None
        self.ui_dropped = 0

    def set_job(self, job):
        with self._lock:
            self._job = job

    def set_max_w(self, w):
        with self._lock:
            self.max_w = max(64, int(w))

    def set_fps(self, fps):
        self.fps = fps
        pb = self.pb
        if pb:
            pb.set_fps(fps)

    def set_loop(self, on):
        self.loop = on
        pb = self.pb
        if pb:
            pb.loop = on

    def seek(self, idx):
        pb = self.pb
        if pb:
            pb.seek(idx)

    def ack(self):
        """Chamado pela interface quando terminou de usar o último quadro."""
        self._free.set()

    def stop(self):
        self._stop = True
        self._free.set()

    def run(self):
        try:
            self.pb = core.Playback(self.path, self.start, self.fps, self.loop)
            while not self._stop:
                r = self.pb.next_frame()
                if r is None:
                    break
                idx, f = r
                with self._lock:
                    job, max_w = self._job, self.max_w
                small, sc = preview_frame(f, max_w)
                small = np.ascontiguousarray(small)
                qimg = bgr_to_qimage(render_job(small, idx, job, sc))
                wt = self.pb.wait_time()
                while wt > 0 and not self._stop:
                    time.sleep(min(wt, 0.01))
                    wt = self.pb.wait_time()
                if self._stop:
                    break
                if not self._free.wait(0.25):        # interface ocupada: descarta este quadro
                    self.ui_dropped += 1
                    self.pb.dropped += 1
                    continue
                self._free.clear()
                self.pb.mark_shown()
                self.frame.emit(self.gen, idx, small, sc, qimg, self.pb.actual_fps, self.pb.dropped)
        except Exception:  # noqa: BLE001
            from . import crashlog
            crashlog.log_exception("Erro na reprodução")
        finally:
            if self.pb:
                self.pb.release()
            self.finished.emit()


class ExportWorker(QObject):
    progress = Signal(int, int)
    finished = Signal(int, bool, str, str)       # n, cancelado, erro, saída

    def __init__(self, path, out, params, opts, background=None):
        super().__init__()
        self.path, self.out, self.params, self.opts = path, out, params, opts
        self.background = background
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            r = export(self.path, self.out, self.params, self.opts,
                       progress=lambda c, t: self.progress.emit(c, t),
                       should_cancel=lambda: self._cancel, background=self.background)
            self.finished.emit(r["count"], r["cancelled"], "", r["output"] or "")
        except Exception as e:  # noqa: BLE001
            self.finished.emit(0, self._cancel, str(e), "")
        finally:
            if self.background is not None:
                self.background.clear()


# ============================================================ widgets
class PreviewLabel(QLabel):
    clicked = Signal(float, float)

    def __init__(self):
        super().__init__(T("Importe um vídeo para começar"))
        self.setObjectName("preview")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(480, 300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._pix = None
        self.picking = False

    def set_image(self, qimg: QImage):
        self._pix = QPixmap.fromImage(qimg)
        self._rescale()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._rescale()

    def _rescale(self):
        if self._pix:
            self.setPixmap(self._pix.scaled(self.size().shrunkBy(QMargins(2, 2, 2, 2)), Qt.KeepAspectRatio,
                                            Qt.SmoothTransformation))

    def mousePressEvent(self, e):
        pm = self.pixmap()
        if not self.picking or pm is None or pm.isNull():
            return
        x0, y0 = (self.width() - pm.width()) / 2, (self.height() - pm.height()) / 2
        px, py = e.position().x() - x0, e.position().y() - y0
        if 0 <= px < pm.width() and 0 <= py < pm.height():
            self.clicked.emit(px / pm.width(), py / pm.height())


class Section(QWidget):
    """Seção recolhível com abertura/fechamento animados (opcional)."""

    def __init__(self, title, expanded=False):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.btn = QToolButton(text=title, checkable=True, checked=expanded)
        self.btn.setObjectName("sectionHeader")
        self.btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.body = QWidget()
        self.grid = QGridLayout(self.body)
        self.grid.setContentsMargins(8, 4, 6, 8)
        self.grid.setColumnStretch(1, 1)
        self.body.setVisible(expanded)
        self.btn.toggled.connect(self._toggle)
        self._anim = None
        lay.addWidget(self.btn)
        lay.addWidget(self.body)

    def _toggle(self, on):
        self.btn.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        if self._anim:
            self._anim.stop()
            self._anim = None
        if not FX.animations or not self.isVisible():
            self.body.setMaximumHeight(16777215)
            self.body.setVisible(on)
            return
        target = self.body.sizeHint().height()
        a = QPropertyAnimation(self.body, b"maximumHeight", self)
        a.setDuration(170)
        a.setEasingCurve(QEasingCurve.OutCubic)
        if on:
            self.body.setMaximumHeight(0)
            self.body.setVisible(True)
            a.setStartValue(0)
            a.setEndValue(target)
            a.finished.connect(lambda: self.body.setMaximumHeight(16777215))
        else:
            a.setStartValue(self.body.height())
            a.setEndValue(0)
            a.finished.connect(lambda: (self.body.setVisible(False), self.body.setMaximumHeight(16777215)))
        self._anim = a
        a.start()

    def add_row(self, label, widget, tip=""):
        r = self.grid.rowCount()
        lbl = None
        if label:
            lbl = QLabel(label)
            lbl.setToolTip(tip)
            self.grid.addWidget(lbl, r, 0)
            self.grid.addWidget(widget, r, 1)
        else:
            self.grid.addWidget(widget, r, 0, 1, 2)
        widget.setToolTip(tip)
        return lbl, widget


class ParamSlider(QWidget):
    valueChanged = Signal(int)

    def __init__(self, lo, hi, default):
        super().__init__()
        self.default = default
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(lo, hi)
        self.slider.setValue(default)
        self.spin = QSpinBox()
        self.spin.setRange(lo, hi)
        self.spin.setValue(default)
        self.spin.setFixedWidth(60)
        self.slider.setMinimumWidth(80)
        self.slider.valueChanged.connect(self.spin.setValue)
        self.spin.valueChanged.connect(self.slider.setValue)
        self.slider.valueChanged.connect(self.valueChanged)
        h.addWidget(self.slider, 1)
        h.addWidget(self.spin)

    def value(self):
        return self.slider.value()

    def setValue(self, v):
        self.slider.setValue(int(v))

    def mouseDoubleClickEvent(self, e):
        self.setValue(self.default)


class ParamCheck(QWidget):
    """Parâmetro liga/desliga (0/1) com a mesma interface do ParamSlider."""
    valueChanged = Signal(int)

    def __init__(self, default):
        super().__init__()
        self.default = default
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        self.chk = QCheckBox()
        self.chk.setChecked(bool(default))
        self.chk.toggled.connect(lambda on: self.valueChanged.emit(int(on)))
        h.addWidget(self.chk)
        h.addStretch(1)

    def value(self):
        return int(self.chk.isChecked())

    def setValue(self, v):
        self.chk.setChecked(bool(v))

    def blockSignals(self, b):
        self.chk.blockSignals(b)
        return super().blockSignals(b)


class GradientTitle(QLabel):
    """Título com o gradiente do logo (lima → verde → esmeralda) pintado sobre o texto."""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setObjectName("appTitle")

    def paintEvent(self, ev):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath
        from . import theme
        from .fx import FX
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        fm = self.fontMetrics()
        r = self.contentsRect()
        tw = fm.horizontalAdvance(self.text())
        x = r.left() + (r.width() - tw) / 2 if self.alignment() & Qt.AlignHCenter else r.left()
        y = r.top() + (r.height() + fm.ascent() - fm.descent()) / 2
        path = QPainterPath()
        path.addText(QPointF(x, y), self.font(), self.text())
        light = self.palette().window().color().lightnessF() > 0.5
        pal = theme.palette("light" if light else "dark", FX.accent)
        g = QLinearGradient(QPointF(x, r.top()), QPointF(x + tw, r.bottom()))
        g.setColorAt(0.0, QColor(pal["title1"]))
        g.setColorAt(0.5, QColor(pal["accent"]))
        g.setColorAt(1.0, QColor(pal["title2"]))
        p.fillPath(path, g)
        p.end()
