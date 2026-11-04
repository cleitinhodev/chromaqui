"""Workers (threads) e widgets básicos da interface."""
from __future__ import annotations

import sys
import threading
import time

import cv2
import numpy as np
from PySide6.QtCore import QEasingCurve, QMargins, QObject, QPointF, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
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


class AutoCropWorker(QObject):
    """Calcula o recorte automático (caixa do objeto em vários quadros) fora da thread da interface."""
    progress = Signal(int, int)
    finished = Signal(object, str)              # (x, y, w, h) | None, erro

    def __init__(self, path, params, samples=30, margin=8):
        super().__init__()
        self.path, self.params, self.samples, self.margin = path, params, samples, margin
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            r = core.auto_crop(self.path, self.params, self.samples, self.margin,
                               progress=lambda c, t: self.progress.emit(c, t),
                               should_cancel=lambda: self._cancel)
            self.finished.emit(r, "")
        except Exception as e:  # noqa: BLE001
            from . import crashlog
            crashlog.log_exception("Erro no recorte automático")
            self.finished.emit(None, str(e))


# ============================================================ widgets
class PreviewLabel(QLabel):
    """Prévia do vídeo. Também desenha e edita o retângulo de recorte (em pixels do vídeo ORIGINAL,
    independente do zoom da prévia, da qualidade da reprodução e da escala de exportação)."""
    clicked = Signal(float, float)
    cropChanged = Signal(int, int, int, int)     # x, y, largura, altura (pixels do original)
    cropEditFinished = Signal()

    HANDLE = 5          # meia largura da alça (px de tela)
    GRAB = 9            # distância para "pegar" uma alça/borda

    def __init__(self):
        super().__init__(T("Importe um vídeo para começar"))
        self.setObjectName("preview")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(480, 300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._pix = None
        self.picking = False
        # recorte
        self.src_size = None            # (largura, altura) do vídeo original
        self.crop = None                # (x, y, w, h) no original; None = sem vídeo
        self.crop_mode = False
        self.side_by_side = False       # "Lado a lado": original | separador 4 px | resultado
        self._img_size = (0, 0)
        self._drag = None               # (modo, pane, ponto inicial no original, recorte inicial)
        self.setMouseTracking(True)

    # ------------------------------------------------------------- imagem
    def set_image(self, qimg: QImage):
        self._img_size = (qimg.width(), qimg.height())
        self._pix = QPixmap.fromImage(qimg)
        self._rescale()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._rescale()

    def _rescale(self):
        if self._pix:
            self.setPixmap(self._pix.scaled(self.size().shrunkBy(QMargins(2, 2, 2, 2)), Qt.KeepAspectRatio,
                                            Qt.SmoothTransformation))

    def _pm_rect(self):
        pm = self.pixmap()
        if pm is None or pm.isNull():
            return None
        x0, y0 = (self.width() - pm.width()) / 2, (self.height() - pm.height()) / 2
        return QRectF(x0, y0, pm.width(), pm.height())

    # ------------------------------------------------------------- recorte: geometria
    def set_crop_source(self, w, h, rect=None):
        self.src_size = (int(w), int(h))
        self.crop = tuple(rect) if rect else core.full_rect(w, h)
        self.update()

    def set_crop(self, rect):
        if self.src_size:
            self.crop = core.clamp_crop(rect, *self.src_size)
            self.update()

    def set_crop_mode(self, on):
        self.crop_mode = bool(on)
        self._drag = None
        if not on:
            self.unsetCursor()
        self.update()

    def set_side_by_side(self, on):
        if self.side_by_side != bool(on):
            self.side_by_side = bool(on)
            self.update()

    def _panes(self):
        """Retângulos (tela) onde o quadro inteiro do original aparece (1 ou 2 no "Lado a lado")."""
        pr = self._pm_rect()
        iw, ih = self._img_size
        if pr is None or not iw or not ih or not self.src_size:
            return []
        d = pr.width() / iw
        if self.side_by_side and iw > 8:
            wp = (iw - 4) / 2.0
            return [QRectF(pr.left(), pr.top(), wp * d, pr.height()),
                    QRectF(pr.left() + (wp + 4) * d, pr.top(), wp * d, pr.height())]
        return [pr]

    def _to_screen(self, pane, rect):
        sw, sh = self.src_size
        fx, fy = pane.width() / sw, pane.height() / sh
        x, y, w, h = rect
        return QRectF(pane.left() + x * fx, pane.top() + y * fy, w * fx, h * fy)

    def _to_src(self, pane, pos):
        sw, sh = self.src_size
        return ((pos.x() - pane.left()) * sw / max(1e-6, pane.width()),
                (pos.y() - pane.top()) * sh / max(1e-6, pane.height()))

    def _hit(self, pos):
        """(modo, índice do painel). modo: 'n','s','e','w','ne','nw','se','sw','move','new' ou None."""
        panes = self._panes()
        for i, pane in enumerate(panes):
            if not pane.adjusted(-self.GRAB, -self.GRAB, self.GRAB, self.GRAB).contains(pos):
                continue
            r = self._to_screen(pane, self.crop)
            g = self.GRAB
            near_l, near_r = abs(pos.x() - r.left()) <= g, abs(pos.x() - r.right()) <= g
            near_t, near_b = abs(pos.y() - r.top()) <= g, abs(pos.y() - r.bottom()) <= g
            in_x = r.left() - g <= pos.x() <= r.right() + g
            in_y = r.top() - g <= pos.y() <= r.bottom() + g
            v = "n" if (near_t and in_x) else "s" if (near_b and in_x) else ""
            hz = "w" if (near_l and in_y) else "e" if (near_r and in_y) else ""
            if v or hz:
                return v + hz, i
            if r.contains(pos):
                return "move", i
            return "new", i
        return None, -1

    _CURSORS = {"n": Qt.SizeVerCursor, "s": Qt.SizeVerCursor, "e": Qt.SizeHorCursor, "w": Qt.SizeHorCursor,
                "nw": Qt.SizeFDiagCursor, "se": Qt.SizeFDiagCursor, "ne": Qt.SizeBDiagCursor,
                "sw": Qt.SizeBDiagCursor, "move": Qt.SizeAllCursor, "new": Qt.CrossCursor}

    # ------------------------------------------------------------- mouse
    def mousePressEvent(self, e):
        if self.crop_mode and self.crop and e.button() == Qt.LeftButton:
            mode, i = self._hit(e.position())
            if mode:
                p0 = self._to_src(self._panes()[i], e.position())
                self._drag = (mode, i, p0, tuple(self.crop))
                if mode == "new":
                    self._apply_drag(e.position())
            return
        pm = self.pixmap()
        if not self.picking or pm is None or pm.isNull():
            return
        x0, y0 = (self.width() - pm.width()) / 2, (self.height() - pm.height()) / 2
        px, py = e.position().x() - x0, e.position().y() - y0
        if 0 <= px < pm.width() and 0 <= py < pm.height():
            self.clicked.emit(px / pm.width(), py / pm.height())

    def mouseMoveEvent(self, e):
        if not self.crop_mode or not self.crop:
            return
        if self._drag:
            self._apply_drag(e.position())
        else:
            mode, _ = self._hit(e.position())
            self.setCursor(self._CURSORS.get(mode, Qt.ArrowCursor))

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._apply_drag(e.position())
            self._drag = None
            self.cropEditFinished.emit()

    def _apply_drag(self, pos):
        mode, i, (sx, sy), (x, y, w, h) = self._drag
        panes = self._panes()
        if i >= len(panes):
            return
        W, H = self.src_size
        cx, cy = self._to_src(panes[i], pos)
        cx, cy = max(0.0, min(float(W), cx)), max(0.0, min(float(H), cy))
        m = core.CROP_MIN
        if mode == "new":
            x0, x1 = sorted((sx, cx))
            y0, y1 = sorted((sy, cy))
            x0, y0 = int(max(0, x0)), int(max(0, y0))
            x1, y1 = int(round(min(W, x1))), int(round(min(H, y1)))
            r = (x0, y0, max(m, x1 - x0), max(m, y1 - y0))
        elif mode == "move":
            dx, dy = int(round(cx - sx)), int(round(cy - sy))
            r = (max(0, min(W - w, x + dx)), max(0, min(H - h, y + dy)), w, h)
        else:
            l, t, rr, b = x, y, x + w, y + h
            ix, iy = int(round(cx)), int(round(cy))
            if "w" in mode:
                l = max(0, min(ix, rr - m))
            if "e" in mode:
                rr = min(W, max(ix, l + m))
            if "n" in mode:
                t = max(0, min(iy, b - m))
            if "s" in mode:
                b = min(H, max(iy, t + m))
            r = (l, t, rr - l, b - t)
        r = core.clamp_crop(r, W, H)
        if r != self.crop:
            self.crop = r
            self.update()
            self.cropChanged.emit(*r)

    # ------------------------------------------------------------- desenho
    def is_cropped(self):
        return bool(self.crop and self.src_size and tuple(self.crop) != core.full_rect(*self.src_size))

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if not self.crop or not (self.crop_mode or self.is_cropped()):
            return
        panes = self._panes()
        if not panes:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        accent = QColor(FX.accent or "#39d353")
        for pane in panes:
            r = self._to_screen(pane, self.crop)
            outside = QPainterPath()
            outside.addRect(pane)
            inner = QPainterPath()
            inner.addRect(r)
            p.fillPath(outside.subtracted(inner), QColor(0, 0, 0, 150 if self.crop_mode else 120))
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(0, 0, 0, 160), 3))
            p.drawRect(r)
            p.setPen(QPen(accent, 1.6, Qt.SolidLine if self.crop_mode else Qt.DashLine))
            p.drawRect(r)
            if self.crop_mode:
                # linhas dos terços (composição) e 8 alças
                p.setPen(QPen(QColor(255, 255, 255, 70), 1))
                for k in (1, 2):
                    xx = r.left() + r.width() * k / 3
                    yy = r.top() + r.height() * k / 3
                    p.drawLine(QPointF(xx, r.top()), QPointF(xx, r.bottom()))
                    p.drawLine(QPointF(r.left(), yy), QPointF(r.right(), yy))
                hs = self.HANDLE
                p.setPen(QPen(QColor(0, 0, 0, 200), 1))
                p.setBrush(QBrush(accent))
                for hx in (r.left(), r.center().x(), r.right()):
                    for hy in (r.top(), r.center().y(), r.bottom()):
                        if hx == r.center().x() and hy == r.center().y():
                            continue
                        p.drawRect(QRectF(hx - hs, hy - hs, 2 * hs, 2 * hs))
            # tamanho em pixels (do original)
            txt = f"{self.crop[2]} × {self.crop[3]} px"
            f = QFont(self.font())
            f.setBold(True)
            p.setFont(f)
            fm = p.fontMetrics()
            tw, th = fm.horizontalAdvance(txt) + 12, fm.height() + 4
            ty = r.top() - th - 4 if r.top() - th - 4 >= pane.top() else r.top() + 4
            tx = max(pane.left(), min(r.left(), pane.right() - tw))
            box = QRectF(tx, ty, tw, th)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 185))
            p.drawRoundedRect(box, 5, 5)
            p.setPen(QColor("#ffffff"))
            p.drawText(box, Qt.AlignCenter, txt)
        p.end()


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
