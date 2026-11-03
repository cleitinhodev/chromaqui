"""Tema visual do Chromaqui! — toda a paleta deriva de UMA cor de destaque (ACCENT).

As cores vêm do logo: o "C" vai do lima (alto, ~#B6F21A/#7CF02A) ao verde (#1FD65F) e ao
esmeralda (~#0FA968, embaixo). `lime()` e `emerald()` são derivados de ACCENT girando o matiz,
então trocar só ACCENT (ou a configuração "accent") recolore tudo de forma coerente."""
from __future__ import annotations

import colorsys

ACCENT = "#1FD65F"          # verde do logo (troque aqui para retocar a paleta inteira)
THEMES = ("dark", "light")


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def _hls(hexc, dl=0.0, ds=0.0, l=None, s=None):
    r, g, b = (c / 255 for c in _rgb(hexc))
    h, L, S = colorsys.rgb_to_hls(r, g, b)
    L = l if l is not None else min(1, max(0, L + dl))
    S = s if s is not None else min(1, max(0, S + ds))
    return _hex(tuple(c * 255 for c in colorsys.hls_to_rgb(h, L, S)))


def _hue(hexc, dh=0.0, dl=0.0, ds=0.0):
    """Gira o matiz (graus) e ajusta luminosidade/saturação."""
    r, g, b = (c / 255 for c in _rgb(hexc))
    h, L, S = colorsys.rgb_to_hls(r, g, b)
    h = (h + dh / 360.0) % 1.0
    L, S = min(1, max(0, L + dl)), min(1, max(0, S + ds))
    return _hex(tuple(c * 255 for c in colorsys.hls_to_rgb(h, L, S)))


def lime(accent=None):
    """Topo do gradiente do logo (verde-limão). Com o ACCENT padrão ≈ #8DF02A."""
    return _hue(accent or ACCENT, dh=-50, dl=0.08, ds=0.15)


def emerald(accent=None):
    """Base do gradiente do logo (esmeralda). Com o ACCENT padrão ≈ #10A968."""
    return _hue(accent or ACCENT, dh=13, dl=-0.10, ds=0.05)


def gradient(accent=None, x2=1, y2=0, light=False):
    """qlineargradient lima → verde → esmeralda (botões principais, barras, neon)."""
    a = accent or ACCENT
    lo = emerald(a) if not light else _hls(emerald(a), dl=-0.03)
    return (f"qlineargradient(x1:0, y1:0, x2:{x2}, y2:{y2}, stop:0 {lime(a)}, stop:0.55 {a}, "
            f"stop:1 {lo})")


def mix(a, b, t):
    ra, rb = _rgb(a), _rgb(b)
    return _hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def rgba(hexc, alpha):
    r, g, b = _rgb(hexc)
    return f"rgba({r},{g},{b},{alpha})"


def palette(theme="dark", accent=None):
    a = accent or ACCENT
    if theme == "light":
        return {
            "accent": _hls(a, dl=-0.06), "accent_hi": lime(a), "accent_lo": emerald(a),
            "lime": lime(a), "emerald": emerald(a), "link": _hls(emerald(a), dl=-0.06),
            "ink": _hls(emerald(a), dl=-0.07), "title1": _hls(lime(a), dl=-0.14), "title2": _hls(emerald(a), dl=-0.06),
            "accent_text": "#06120A",
            "bg": mix("#F4F7F5", a, 0.03), "bg2": mix("#FFFFFF", a, 0.02), "panel": "#FFFFFF",
            "panel2": mix("#EEF3EF", a, 0.05), "border": mix("#D3DDD6", a, 0.08),
            "text": "#18211B", "muted": "#5D6B62", "input": "#FFFFFF",
            "head1": mix("#FFFFFF", a, 0.10), "head2": mix("#F1F5F2", a, 0.04),
            "preview": "#E9EEEA", "sel": rgba(a, 0.22), "disabled": "#A9B3AD",
        }
    return {
        "accent": a, "accent_hi": lime(a), "accent_lo": emerald(a),
        "lime": lime(a), "emerald": emerald(a), "link": _hls(lime(a), dl=-0.02),
        "ink": _hls(a, dl=0.06), "title1": lime(a), "title2": emerald(a),
        "accent_text": "#06120A",
        "bg": mix("#111613", a, 0.03), "bg2": mix("#161C18", a, 0.03), "panel": mix("#1A211C", a, 0.03),
        "panel2": mix("#212A24", a, 0.05), "border": mix("#2E3A32", a, 0.10),
        "text": "#E7EFE9", "muted": "#93A398", "input": mix("#0F1411", a, 0.02),
        "head1": mix("#26312A", a, 0.10), "head2": mix("#1C241F", a, 0.04),
        "preview": "#0C100D", "sel": rgba(a, 0.28), "disabled": "#56625A",
    }


def _luma(hexc):
    r, g, b = (c / 255 for c in _rgb(hexc))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def stylesheet(theme="dark", accent=None):
    p = palette(theme, accent)
    return f"""
* {{ font-family: "Segoe UI", "Noto Sans", "Microsoft YaHei UI", "Yu Gothic UI", sans-serif; font-size: 10pt; }}
QMainWindow, QDialog {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {p['bg2']}, stop:1 {p['bg']}); color: {p['text']}; }}
QWidget {{ color: {p['text']}; }}
QToolTip {{ background: {p['panel2']}; color: {p['text']}; border: 1px solid {p['accent']}; padding: 5px; border-radius: 6px; }}
QLabel#muted, QLabel[muted="true"] {{ color: {p['muted']}; }}
QLabel#appTitle {{ font-size: 17pt; font-weight: 800; letter-spacing: 0.5px;
    color: {p['accent']}; }}  /* o gradiente do texto é pintado por widgets.GradientTitle */
QLabel#appVersion {{ color: {p['muted']}; font-size: 9pt; }}
QFrame#header {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p['head1']}, stop:1 {p['head2']});
    border: 1px solid {p['border']}; border-radius: 12px; }}
QLabel#preview {{ background: {p['preview']}; color: {p['muted']}; font-size: 15px; border: 1px solid {p['border']}; border-radius: 12px; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollArea#panel {{ background: {p['panel']}; border: 1px solid {p['border']}; border-radius: 12px; }}
QScrollArea#timeline {{ background: {p['panel']}; border: 1px solid {p['border']}; border-radius: 10px; }}
QPushButton, QToolButton#tool {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {p['panel2']}, stop:1 {p['panel']});
    border: 1px solid {p['border']}; border-radius: 8px; padding: 6px 12px; }}
QPushButton:hover, QToolButton#tool:hover {{ border-color: {p['accent']}; background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {mix(p['panel2'], p['accent'], 0.12)}, stop:1 {p['panel']}); }}
QPushButton:pressed {{ background: {mix(p['panel'], p['accent'], 0.25)}; }}
QPushButton:checked {{ background: {p['sel']}; border-color: {p['accent']}; }}
QPushButton:disabled {{ color: {p['disabled']}; border-color: {p['border']}; }}
QPushButton#primary {{ color: {p['accent_text']}; font-weight: 700; border: 1px solid {p['emerald']};
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {p['lime']}, stop:0.55 {p['accent']}, stop:1 {p['emerald']}); }}
QPushButton#primary:hover {{ border-color: {p['lime']};
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {_hls(p['lime'], dl=0.06)}, stop:0.55 {_hls(p['accent'], dl=0.05)}, stop:1 {p['accent']}); }}
QPushButton#primary:pressed {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {p['accent']}, stop:1 {p['emerald']}); }}
QPushButton#primary:disabled {{ background: {p['panel2']}; color: {p['disabled']}; border-color: {p['border']}; }}
QToolButton#sectionHeader {{ font-weight: 700; text-align: left; padding: 7px 8px; border-radius: 8px; border: 1px solid {p['border']};
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p['head1']}, stop:1 {p['head2']}); }}
QToolButton#sectionHeader:hover {{ border-color: {p['accent']}; }}
QToolButton#sectionHeader:checked {{ color: {p['ink']}; }}
QToolButton#thumb {{ border: 2px solid transparent; border-radius: 6px; padding: 2px; background: transparent; }}
QToolButton#thumb:hover {{ border-color: {rgba(p['accent'], 0.5)}; }}
QToolButton#thumb:checked {{ border-color: {p['accent']}; background: {p['sel']}; }}
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{ background: {p['input']}; border: 1px solid {p['border']}; border-radius: 6px; padding: 3px 6px; min-height: 20px; }}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover, QLineEdit:focus, QSpinBox:focus {{ border-color: {p['accent']}; }}
QComboBox QAbstractItemView {{ background: {p['panel']}; border: 1px solid {p['border']}; selection-background-color: {p['sel']}; selection-color: {p['text']}; }}
QSlider::groove:horizontal {{ height: 6px; border-radius: 3px; background: {p['panel2']}; border: 1px solid {p['border']}; }}
QSlider::sub-page:horizontal {{ border-radius: 3px; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p['emerald']}, stop:0.6 {p['accent']}, stop:1 {p['lime']}); }}
QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; border: 2px solid {p['emerald']};
    background: qradialgradient(cx:0.35, cy:0.35, radius:0.8, fx:0.35, fy:0.35, stop:0 {_hls(p['lime'], dl=0.15)}, stop:1 {p['accent']}); }}
QSlider::handle:horizontal:hover {{ background: {p['accent']}; }}
QSlider::groove:horizontal:disabled {{ background: {p['panel']}; }}
QSlider::sub-page:horizontal:disabled {{ background: {p['disabled']}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {p['border']}; background: {p['input']}; }}
QCheckBox::indicator:hover {{ border-color: {p['accent']}; }}
QCheckBox::indicator:checked {{ border-color: {p['emerald']};
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {p['lime']}, stop:1 {p['emerald']}); }}
QProgressBar {{ border: 1px solid {p['border']}; border-radius: 7px; background: {p['input']}; text-align: center; min-height: 18px; }}
QProgressBar::chunk {{ border-radius: 6px; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p['emerald']}, stop:0.5 {p['accent']}, stop:1 {p['lime']}); }}
QScrollBar:vertical {{ width: 10px; background: transparent; margin: 2px; }}
QScrollBar:horizontal {{ height: 10px; background: transparent; margin: 2px; }}
QScrollBar::handle {{ background: {p['border']}; border-radius: 4px; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: {p['accent']}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none; width: 0; height: 0; }}
QStatusBar {{ background: {p['panel']}; border-top: 1px solid {p['border']}; color: {p['muted']}; }}
QStatusBar QLabel {{ color: {p['muted']}; padding: 0 6px; }}
QGroupBox {{ border: 1px solid {p['border']}; border-radius: 8px; margin-top: 12px; padding-top: 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; color: {p['ink']}; font-weight: 700; }}
QMessageBox {{ background: {p['bg']}; }}
a {{ color: {p['link']}; }}
"""
