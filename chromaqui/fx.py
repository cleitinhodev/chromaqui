"""Efeitos visuais opcionais: brilho neon (sombra colorida) e animações suaves.
Tudo pode ser desligado nas Configurações (FX.animations / FX.neon)."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QGraphicsOpacityEffect


class _FX:
    animations = True
    neon = True
    accent = "#1FD65F"


FX = _FX()


class GlowHover(QObject):
    """Ao passar o mouse, o brilho neon cresce suavemente (só se animações ligadas)."""

    def __init__(self, widget, base=14, hover=30):
        super().__init__(widget)
        self.w, self.base, self.hover = widget, base, hover
        self.anim = None
        widget.installEventFilter(self)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t in (QEvent.Enter, QEvent.Leave):
            eff = self.w.graphicsEffect()
            if isinstance(eff, QGraphicsDropShadowEffect):
                target = self.hover if t == QEvent.Enter and self.w.isEnabled() else self.base
                if FX.animations:
                    self.anim = QPropertyAnimation(eff, b"blurRadius", self)
                    self.anim.setDuration(180)
                    self.anim.setEndValue(float(target))
                    self.anim.setEasingCurve(QEasingCurve.OutCubic)
                    self.anim.start()
                else:
                    eff.setBlurRadius(target)
        return False


def set_neon(widget, on, radius=14, strength=0.85):
    if on:
        eff = widget.graphicsEffect()
        if not isinstance(eff, QGraphicsDropShadowEffect):
            eff = QGraphicsDropShadowEffect(widget)
            widget.setGraphicsEffect(eff)
        from .theme import lime, mix
        c = QColor(mix(lime(FX.accent), FX.accent, 0.4))     # brilho neon puxado para o lima do logo
        c.setAlphaF(strength)
        eff.setColor(c)
        eff.setOffset(0, 0)
        eff.setBlurRadius(radius)
        if not hasattr(widget, "_glow"):
            widget._glow = GlowHover(widget, radius, radius * 2)
    elif isinstance(widget.graphicsEffect(), QGraphicsDropShadowEffect):
        widget.setGraphicsEffect(None)


def fade_in(widget, ms=320, start=0.25):
    """Esmaece o widget de `start` até 1 e remove o efeito ao terminar (sem custo depois)."""
    if not FX.animations or widget.graphicsEffect() is not None:
        return None
    eff = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(eff)
    a = QPropertyAnimation(eff, b"opacity", widget)
    a.setDuration(ms)
    a.setStartValue(start)
    a.setEndValue(1.0)
    a.setEasingCurve(QEasingCurve.OutCubic)
    a.finished.connect(lambda: widget.setGraphicsEffect(None))
    a.start()
    widget._fade = a
    return a


def fade_window(win, ms=260):
    if not FX.animations:
        return None
    win.setWindowOpacity(0.0)
    a = QPropertyAnimation(win, b"windowOpacity", win)
    a.setDuration(ms)
    a.setStartValue(0.0)
    a.setEndValue(1.0)
    a.setEasingCurve(QEasingCurve.OutCubic)
    a.start()
    win._fade = a
    return a
