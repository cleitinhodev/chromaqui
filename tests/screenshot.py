"""Gera as capturas de tela de docs/ (tema escuro e claro, diálogos) com o projeto de demonstração
(assets/demo/japanese_woman.mp4 sobre assets/demo/scenery_shrine.webp).

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

from chromaqui import demo  # noqa: E402
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
# Projeto de demonstração (assets/demo): japanese_woman.mp4 sobre scenery_shrine.webp, meio a meio
assert w.open_demo()
pump(2.0)
open_sections(w, ["Cor-chave", "Colorização de bordas"])
w.render_preview()
shoot("dark", "demo_inicio_escuro.png")          # exatamente como o programa abre
shoot("light", "demo_inicio_claro.png")
w.demo_banner.setVisible(False)
w.statusBar().clearMessage()
shoot("dark", "screenshot_escuro.png")
shoot("light", "screenshot_claro.png")

w.btn_compare.setChecked(False)
w.cmb_view.setCurrentIndex(VIEWS.index("Lado a lado"))
open_sections(w, ["Opções de exportação"])
w.render_preview()
shoot("dark", "screenshot_exportar_escuro.png")
shoot("light", "screenshot_exportar_claro.png")

# Recorte da área exportada (modo Recortar + Auto)
w = ctrl.window
w.cmb_view.setCurrentIndex(VIEWS.index("Resultado"))
open_sections(w, ["Recorte da área exportada", "Opções de exportação"])
w.btn_crop.setChecked(True)
w.last_auto_crop = None
w.auto_crop()
t_end = time.time() + 60
while (w.is_auto_cropping() or w.last_auto_crop is None) and time.time() < t_end:
    pump(0.05)
w.render_preview()
shoot("dark", "recorte_escuro.png")
shoot("light", "recorte_claro.png")
w = ctrl.window
w.btn_crop.setChecked(False)
w.reset_crop()

# Recursos da 3.2 (beta): comparar antes/depois + brilho neon; recorte que segue o objeto; lote
w = ctrl.window
open_sections(w, ["Sombra e brilho", "Retoque com pincel"])
w.chk_glow.setChecked(True)
w.cmb_glow_mode.setCurrentIndex(w.cmb_glow_mode.findData("neon"))
w._on_glow_mode()
w.btn_compare.setChecked(True)
w.render_preview()
shoot("dark", "beta_comparar_brilho_escuro.png")
shoot("light", "beta_comparar_brilho_claro.png")
w = ctrl.window
w.btn_compare.setChecked(False)
w.chk_glow.setChecked(False)
open_sections(w, ["Recorte da área exportada", "Remoção por IA"])
w.cmb_motion.setCurrentIndex(w.cmb_motion.findData("follow"))
w._on_motion()
w.analyze_motion()
t_end = time.time() + 60
while (w.is_tracking() or w.track_path is None) and time.time() < t_end:
    pump(0.05)
w.slider.setValue(40)
pump(0.5)
w.render_preview()
shoot("dark", "beta_seguir_objeto_escuro.png")
w = ctrl.window
w.cmb_motion.setCurrentIndex(w.cmb_motion.findData("fixed"))
w._on_motion()
d = w.open_batch()
take2 = os.path.join(tempfile.mkdtemp(), "japanese_woman_take2.mp4")
_v = cv2.VideoCapture(demo.video_path())
_wr = cv2.VideoWriter(take2, cv2.VideoWriter_fourcc(*"mp4v"), 24, (1280, 720))
for _i in range(48):
    ok, fr = _v.read()
    if not ok:
        break
    _wr.write(cv2.flip(fr, 1))
_wr.release(); _v.release()
d.add_videos([demo.video_path(), take2])
d.resize(760, 480)
pump(0.6)
d.grab().save(os.path.join(DOCS, "beta_lote_escuro.png"))
d.close()

for theme in ("dark", "light"):
    ctrl.set_theme(theme)
    for cls, nm in ((AboutDialog, "sobre"), (SettingsDialog, "configuracoes")):
        d = cls(ctrl.window) if cls is AboutDialog else cls(ctrl, ctrl.window)
        d.show()
        pump(0.6)
        d.grab().save(os.path.join(DOCS, f"{nm}_{'escuro' if theme == 'dark' else 'claro'}.png"))
        d.close()

# Interface em inglês (troca na hora), como abre: demonstração meio a meio
ctrl.set_theme("dark")
ctrl.window.open_demo()
pump(1.0)
ctrl.set_language("en")
pump(1.5)
open_sections(ctrl.window, ["Cor-chave", "Colorização de bordas"])
ctrl.window.render_preview()
pump(1.0)
shoot("dark", "screenshot_en.png")
ctrl.set_language("pt-BR")
pump(1.0)
print("ok:", sorted(os.listdir(DOCS)))
ctrl.window.shutdown()
ctrl.window.close()
