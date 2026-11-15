"""Projeto de demonstração: abre ao iniciar (se ligado), meio a meio sobre o cenário, e não vaza nada para
as preferências; 'Novo projeto' (Ctrl+N) e importar outro vídeo começam do zero.
Uso: python tests/test_demo.py"""
import os, sys, tempfile, time, json
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["CHROMAQUI_NO_UPDATE_CHECK"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
TMP = tempfile.mkdtemp(prefix="chromaqui_demo_")
os.environ["CHROMAQUI_SETTINGS"] = os.path.join(TMP, "settings.ini")
VID = os.path.join(HERE, "_out", "teste_verde.mp4")

import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from chromaqui import core, demo
from chromaqui.app import VIEWS, Controller
from chromaqui.dialogs import AboutDialog, SettingsDialog

QMessageBox.critical = staticmethod(lambda *a, **k: (_ for _ in ()).throw(AssertionError(a)))
app = QApplication.instance() or QApplication(sys.argv[:1])
ctrl = Controller(app); ctrl.quiet = True
ctrl.set_fx(animations=False)


def pump(s=0.3):
    t = time.time() + s
    while time.time() < t:
        app.processEvents(); time.sleep(0.005)


# ---- arquivos e ajustes da demonstração
assert demo.available(), demo.video_path()
assert os.path.basename(demo.video_path()) == "japanese_woman.mp4"
assert os.path.basename(demo.background_path()) == "scenery_shrine.webp"
v = core.Video(demo.video_path())
assert (v.width, v.height) == (1280, 720) and v.frame_count >= 140, (v.width, v.height, v.frame_count)
bg = cv2.imread(demo.background_path())
assert bg is not None and bg.shape[1] >= 1280, bg is None or bg.shape
p = demo.params()
for i in (0, 60, demo.FRAME, v.frame_count - 1):
    fr = v.read(i)
    a = core.compute_alpha(fr, p)
    corners = np.concatenate([a[:120, :200].ravel(), a[:120, -200:].ravel()])
    assert corners.max() < 0.02, (i, corners.max())                 # fundo verde some por inteiro
    m = cv2.erode((a > 0.5).astype(np.uint8), np.ones((11, 11))) > 0
    assert m.sum() > 20000 and a[m].mean() > 0.98, (i, m.sum(), a[m].mean())   # moça opaca
    out = core.render_view(fr, p, "Resultado", bg_img=core.fit_image(bg, 1280, 720, "fill"))
    g = out[:120, :200].astype(int)
    assert not ((g[..., 1] > g[..., 2] + 60) & (g[..., 1] > g[..., 0] + 60)).mean() > 0.2  # sem verde chapado
    # a divisória (meio) passa pela moça no quadro escolhido
    if i == demo.FRAME:
        cols = np.nonzero((a > 0.5).any(0))[0]
        assert cols.min() < 640 < cols.max(), (cols.min(), cols.max())
v.release()
print("DEMO ARQUIVOS OK")

# ---- abre na janela: meio a meio, banner, sem gravar nada
s0 = {k: ctrl.settings.q.value(k) for k in ctrl.settings.q.allKeys()}
w = ctrl.create_window(); w.resize(1300, 860); w.show(); pump(0.3)
assert w.video is None and not w.demo_active and not w.demo_banner.isVisible()
assert w.open_demo(); pump(1.0)
assert w.demo_active and w.demo_banner.isVisible() and w.btn_compare.isChecked() and w.preview.compare_active()
assert w.slider.value() == demo.FRAME and abs(w.preview.split - 0.5) < 1e-9
assert VIEWS[w.cmb_view.currentIndex()] == "Resultado" and w.background.active
assert w.sliders["tolerance"].value() == 24 and w.sliders["pedestal"].value() == 6
assert not w.btn_undo.isEnabled()
# mexer no recorte durante a demonstração não grava "crops"
w.set_crop((100, 50, 900, 600)); pump(0.6)
s1 = {k: ctrl.settings.q.value(k) for k in ctrl.settings.q.allKeys()}
assert s1 == s0, (s0, s1)
# banner dispensável
w.btn_demo_close.click(); assert not w.demo_banner.isVisible() and w.demo_active
print("DEMO JANELA OK")

# ---- troca de idioma mantém a demonstração
w = ctrl.set_language("en"); pump(0.6)
assert w.demo_active and w.btn_compare.isChecked() and w.background.active and not w.demo_banner.isVisible()
assert w.crop_rect == (100, 50, 900, 600), w.crop_rect
w = ctrl.set_language("pt-BR"); pump(0.4)
print("DEMO IDIOMA OK")

# ---- importar outro vídeo: começa limpo
w.demo_banner.setVisible(True)
assert w.load_video(VID); pump(0.6)
assert not w.demo_active and not w.demo_banner.isVisible()
assert w.params().values == core.PARAM_DEFAULTS, {k: v for k, v in w.params().values.items() if core.PARAM_DEFAULTS[k] != v}
assert not w.background.active and w.cmb_bg.currentIndex() == 0 and not w.btn_compare.isChecked()
assert w.crop_rect == core.full_rect(w.video.width, w.video.height)
assert ctrl.settings.get("crops") == ""
print("DEMO -> OUTRO VÍDEO OK")

# ---- Novo projeto (Ctrl+N) depois da demonstração
w.open_demo(); pump(0.5)
QTest.keyClick(w, Qt.Key_N, Qt.ControlModifier); pump(0.6)
w2 = ctrl.window
assert w2 is not w and w2.video is None and not w2.demo_active and not w2.demo_banner.isVisible()
assert w2.params().values == core.PARAM_DEFAULTS and not w2.background.active and not w2.btn_compare.isChecked()
assert w2.lbl_info.text() == "Nenhum vídeo carregado" and not w2.btn_export.isEnabled()
w = w2
# Novo projeto com vídeo comum também limpa
w.load_video(VID); w.sliders["tolerance"].setValue(40); pump(0.2)
w.btn_new.click(); pump(0.5); w = ctrl.window
assert w.video is None and w.sliders["tolerance"].value() == core.PARAM_DEFAULTS["tolerance"]
print("NOVO PROJETO OK")

# ---- preferência e ações nos diálogos
assert ctrl.settings.get("show_demo") is True
sd = SettingsDialog(ctrl, w)
sd.chk_demo.setChecked(False); assert ctrl.settings.get("show_demo") is False
sd.chk_demo.setChecked(True); assert ctrl.settings.get("show_demo") is True
sd.btn_demo.click(); pump(0.5)
assert w.demo_active
w.new_project(); pump(0.4); w = ctrl.window
ab = AboutDialog(w)
ab.btn_demo.click(); pump(0.5)
assert w.demo_active and w.btn_compare.isChecked()
print("CONFIGURAÇÕES/SOBRE OK")

w.shutdown(); w.close(); pump(0.2)
print("TEST DEMO OK")
