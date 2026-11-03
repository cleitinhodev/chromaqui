"""Gera as capturas de tela de docs/ (tema escuro e claro, diálogos).

    python tests/screenshot.py
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ["CHROMAQUI_SETTINGS"] = os.path.join(tempfile.mkdtemp(), "shots.ini")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from chromaqui.app import VIEWS, Controller  # noqa: E402
from chromaqui.dialogs import AboutDialog, SettingsDialog  # noqa: E402
from chromaqui.i18n import T  # noqa: E402
from chromaqui.widgets import Section  # noqa: E402

DOCS = os.path.join(ROOT, "docs")
os.makedirs(DOCS, exist_ok=True)
qa = QApplication(sys.argv[:1])
ctrl = Controller(qa)
ctrl.quiet = True


def pump(s=0.6):
    t0 = time.time()
    while time.time() - t0 < s:
        qa.processEvents()
        time.sleep(0.01)


def scene(path, w=1280, h=720):
    """Fundo de exemplo: pôr do sol com colinas."""
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    top, bot = np.array([120, 60, 40], np.float32), np.array([90, 170, 255], np.float32)   # BGR
    img = np.broadcast_to((top * (1 - y) + bot * y)[:, None, :], (h, w, 3)).copy()
    cv2.circle(img, (w * 2 // 3, int(h * 0.62)), 110, (120, 210, 255), -1, cv2.LINE_AA)
    xs = np.arange(w)
    for amp, base, col in ((60, 0.72, (60, 90, 50)), (40, 0.82, (40, 60, 30))):
        ys = (h * base + amp * np.sin(xs / w * 6.0 + base * 10)).astype(np.int32)
        pts = np.concatenate([np.stack([xs, ys], 1), [[w - 1, h - 1], [0, h - 1]]]).astype(np.int32)
        cv2.fillPoly(img, [pts], col, cv2.LINE_AA)
    cv2.imwrite(path, cv2.GaussianBlur(img.astype(np.uint8), (0, 0), 1.2))


def open_sections(w, titles):
    for s in w.findChildren(Section):
        s.btn.setChecked(s.btn.text() in [T(t) for t in titles])


def shoot(theme, name):
    ctrl.set_theme(theme)
    w = ctrl.window
    pump(0.8)
    w.grab().save(os.path.join(DOCS, name))


ctrl.set_fx(animations=False)
w = ctrl.create_window()
w.resize(1440, 900)
w.show()
w.load_video(os.path.join(HERE, "_out", "teste_cabelo_loiro.mp4"))
pump(1.5)
w.toggle_pick(True)
w.pick_from_preview(0.03, 0.06)
bg = os.path.join(tempfile.mkdtemp(), "cenario.png")
scene(bg)
w.set_background(bg, "fill")
w.slider.setValue(12)
open_sections(w, ["Cor-chave", "Colorização de bordas"])
w.render_preview()
shoot("dark", "screenshot_escuro.png")
shoot("light", "screenshot_claro.png")

w.cmb_view.setCurrentIndex(VIEWS.index("Lado a lado"))
open_sections(w, ["Opções de exportação"])
w.render_preview()
shoot("dark", "screenshot_exportar_escuro.png")
shoot("light", "screenshot_exportar_claro.png")

for theme in ("dark", "light"):
    ctrl.set_theme(theme)
    for cls, nm in ((AboutDialog, "sobre"), (SettingsDialog, "configuracoes")):
        d = cls(ctrl.window) if cls is AboutDialog else cls(ctrl, ctrl.window)
        d.show()
        pump(0.6)
        d.grab().save(os.path.join(DOCS, f"{nm}_{'escuro' if theme == 'dark' else 'claro'}.png"))
        d.close()

# Interface em inglês (troca na hora)
ctrl.set_theme("dark")
ctrl.set_language("en")
pump(1.5)
ctrl.window.cmb_view.setCurrentIndex(0)
ctrl.window.render_preview()
shoot("dark", "screenshot_en.png")
print("ok:", sorted(os.listdir(DOCS)))
ctrl.window.shutdown()
ctrl.window.close()
