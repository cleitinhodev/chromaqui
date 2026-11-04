"""Testes da interface real (offscreen): exportar clicando no botão (diálogos simulados) para TODOS os
formatos, com configurações novas e já salvas; e estresse da reprodução trocando a qualidade.
Uso: python tests/test_ui_flows.py [export|crop|stress|all]"""
import os, sys, tempfile, time, shutil
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
OUT = os.path.join(HERE, "_out")
VID = os.path.join(OUT, "teste_verde.mp4")
VID1080 = os.path.join(OUT, "teste_1080p.mp4")
TMP = tempfile.mkdtemp(prefix="chromaqui_ui_")
os.environ["CHROMAQUI_SETTINGS"] = os.path.join(TMP, "settings.ini")
os.environ["CHROMAQUI_LOG_DIR"] = os.path.join(TMP, "logs")

import numpy as np
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from chromaqui.app import Controller
from chromaqui.exporters import FORMATS

app = QApplication.instance() or QApplication(sys.argv[:1])
from chromaqui import crashlog
crashlog.install(qt_messages=False)
import faulthandler
faulthandler.enable(sys.stderr, all_threads=True)      # no CI: travamento nativo aparece no log
import functools
print = functools.partial(print, flush=True)
errors = []
QMessageBox.critical = staticmethod(lambda *a, **k: errors.append(a[2] if len(a) > 2 else a) or QMessageBox.Ok)
QMessageBox.warning = QMessageBox.critical
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)


def pump(sec):
    t = time.time() + sec
    while time.time() < t:
        app.processEvents(); time.sleep(0.005)


def wait(cond, sec=120):
    t = time.time() + sec
    while time.time() < t:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def make_1080p():
    """Vídeo 1920×1080 (96 quadros) a partir do vídeo de teste, para estressar a qualidade 'Completa'."""
    if os.path.exists(VID1080):
        return
    import subprocess, imageio_ffmpeg
    src = os.path.join(OUT, "teste_cabelo_loiro.mp4")
    src = src if os.path.exists(src) else VID
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-v", "error", "-stream_loop", "3", "-i", src,
                    "-vf", "scale=1920:1080", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", VID1080],
                   check=True)


def make_window(video):
    ctrl = Controller(app); ctrl.quiet = True
    w = ctrl.create_window(); w.show(); app.processEvents()
    w.load_video(video); pump(0.3)
    return ctrl, w


def test_export():
    dialogs = {"save": [], "dir": []}

    def fake_save(parent, title, start, flt="", *a, **k):
        dialogs["save"].append(start)
        assert isinstance(start, str), start
        return os.path.join(target[0], "saida_sem_ext"), flt
    def fake_dir(parent, title, start="", *a, **k):
        dialogs["dir"].append(start)
        assert isinstance(start, str), start
        d = os.path.join(target[0], "seq"); os.makedirs(d, exist_ok=True); return d
    QFileDialog.getSaveFileName = staticmethod(fake_save)
    QFileDialog.getExistingDirectory = staticmethod(fake_dir)
    for round_ in ("novas", "salvas", "pasta_inexistente"):
        print(f"export: configurações {round_} …")
        if round_ == "novas" and os.path.exists(os.environ["CHROMAQUI_SETTINGS"]):
            os.remove(os.environ["CHROMAQUI_SETTINGS"])
        ctrl, w = make_window(VID)
        if round_ == "pasta_inexistente":
            ctrl.settings.set("last_dir", os.path.join(TMP, "nao_existe_mais"))
        w.sp_in.setValue(0); w.sp_out.setValue(min(5, w.video.frame_count - 1))
        for f in FORMATS:
            target = [os.path.join(TMP, round_, f.key)]; os.makedirs(target[0], exist_ok=True)
            w.cmb_fmt.setCurrentIndex([x.key for x in FORMATS].index(f.key)) if hasattr(w, "cmb_fmt") else None
            assert w.export_options().fmt == f.key, (w.export_options().fmt, f.key)
            print("  ", f.key)
            n_err = len(errors)
            w.btn_export.click()                       # fluxo real: sinal clicked(bool)
            assert wait(lambda: not w.is_exporting()), "exportação não terminou"
            pump(0.05)
            assert len(errors) == n_err, f"{f.key}: {errors[n_err:]}"
            n, canc, err, out = w.last_export
            assert not err and n > 0, (f.key, w.last_export)
            assert os.path.exists(out), out
            if f.single_file:
                assert out.lower().endswith(f.ext), out
        print(f"EXPORT pelo botão OK ({round_}): {len(FORMATS)} formatos")
        w.shutdown(); w.close(); w.deleteLater(); pump(0.1)
    assert ctrl.settings.get("last_dir"), "last_dir não salvo"


def test_stress(video, seconds=20):
    print(f"stress: {os.path.basename(video)} …")
    ctrl, w = make_window(video)
    w.sp_fps.setValue(60)
    w.cmb_view.setCurrentIndex(0)
    t_end = time.time() + seconds
    i = toggles = seeks = 0
    rng = np.random.default_rng(1)
    w.start_play()
    while time.time() < t_end:
        i += 1
        w.cmb_playq.setCurrentIndex(int(rng.integers(0, 3))); toggles += 1
        pump(float(rng.choice([0.0, 0.01, 0.05, 0.2])))
        if i % 5 == 0:
            w.slider.setValue(int(rng.integers(0, w.video.frame_count))); seeks += 1
        if i % 7 == 0:
            s = next(iter(w.sliders.values())); s.setValue(int(rng.integers(s.minimum(), s.maximum() + 1)) if hasattr(s, "minimum") else s.value())
        if i % 11 == 0:
            w.toggle_play()
        if i % 13 == 0 and not w.is_playing():
            w.start_play()
        assert len(errors) == 0, errors
    import chromaqui.app as appmod
    for nowait in (False, True):               # True: sem esperar a thread antiga (força o caminho "pendente")
        appmod.PLAY_STOP_WAIT_MS = 0 if nowait else 3000
        for k in range(60):                    # reinícios rápidos (corrida entre a thread antiga e a nova)
            w.cmb_playq.setCurrentIndex(k % 3)
            w.stop_play(); w.start_play(); pump(0.0 if k % 2 else 0.02)
            assert w.is_playing(), "reinício falhou"
    appmod.PLAY_STOP_WAIT_MS = 3000
    assert wait(lambda: not appmod._RETIRED, 30), f"threads pendentes não liberadas: {len(appmod._RETIRED)}"
    w.cmb_playq.setCurrentIndex(2); w.start_play(); pump(1.5)
    assert w.is_playing(), "parou de reproduzir"
    w.stop_play(); pump(0.2)
    leaked = list(appmod._RETIRED)
    # fim do vídeo sem repetir: a interface tem de voltar a "Reproduzir"
    w.chk_loop.setChecked(False); w.sp_fps.setValue(120)
    w.slider.setValue(w.video.frame_count - 8); w.start_play()
    assert wait(lambda: not w.is_playing(), 30), "não parou no fim"
    pump(0.1)
    assert w.play_thread is None and w.btn_play.text() != w.windowTitle(), "estado da interface"
    # trocar o idioma durante a reprodução (janela recriada) não pode derrubar o programa
    w.chk_loop.setChecked(True); w.start_play(); pump(0.3)
    w2 = ctrl.set_language("en"); pump(0.5)
    w2 = w2 or ctrl.window
    w2.start_play(); pump(0.5); w2.cmb_playq.setCurrentIndex(0); pump(0.2)
    ctrl.set_language("pt-BR"); pump(0.5)
    w = ctrl.window
    w.shutdown(); w.close(); pump(0.2)
    print(f"STRESS OK ({os.path.basename(video)}): {toggles} trocas de qualidade, {seeks} buscas, {seconds}s, "
          f"threads pendentes: {len(leaked)}")


def _drag(prev, a, b, steps=6):
    from PySide6.QtCore import Qt, QPoint
    from PySide6.QtTest import QTest
    a, b = QPoint(int(a[0]), int(a[1])), QPoint(int(b[0]), int(b[1]))
    QTest.mousePress(prev, Qt.LeftButton, Qt.NoModifier, a)
    for i in range(1, steps + 1):
        QTest.mouseMove(prev, a + (b - a) * i / steps)
    QTest.mouseRelease(prev, Qt.LeftButton, Qt.NoModifier, b)
    app.processEvents()


def test_crop_ui():
    """Recorte pela interface: desenhar/ajustar/mover na prévia, campos, Auto, Redefinir, preferências por
    tamanho de vídeo, troca de idioma, "Lado a lado" e exportação pelo botão com o recorte."""
    from PIL import Image
    print("recorte: interface …")
    ctrl, w = make_window(VID)
    W, H = w.video.width, w.video.height
    assert w.crop_rect == (0, 0, W, H) and w.crop_for_export() is None
    pv = w.preview
    w.btn_pick.setChecked(True)
    w.btn_crop.setChecked(True); pump(0.1)
    assert pv.crop_mode and not w.btn_pick.isChecked() and not pv.picking, "recorte e conta-gotas devem se excluir"
    w.render_preview(); pump(0.3)
    pane = pv._panes()[0]
    sx, sy = pane.width() / W, pane.height() / H
    to = lambda x, y: (pane.left() + x * sx, pane.top() + y * sy)
    # 1) desenhar um retângulo novo (arrastar no meio da imagem a partir de fora do recorte não existe:
    #    o recorte começa no quadro inteiro, então o clique no meio MOVE; primeiro encolhe pela alça)
    _drag(pv, to(W, H), to(400, 300))                  # alça "se" no canto
    x, y, cw, ch = w.crop_rect
    assert x == 0 and y == 0 and abs(cw - 400) <= 3 and abs(ch - 300) <= 3, w.crop_rect
    _drag(pv, to(500, 330), to(600, 350))              # fora do recorte: desenha um novo
    x, y, cw, ch = w.crop_rect
    assert abs(x - 500) <= 3 and abs(y - 330) <= 3 and abs(cw - 100) <= 4 and abs(ch - 20) <= 4, w.crop_rect
    _drag(pv, to(550, 340), to(450, 240))              # mover pelo meio (tamanho igual)
    x2, y2, cw2, ch2 = w.crop_rect
    assert (cw2, ch2) == (cw, ch) and abs(x2 - (x - 100)) <= 3 and abs(y2 - (y - 100)) <= 3, (w.crop_rect, (x, y, cw, ch))
    _drag(pv, to(x2 + cw2 / 2, y2 + ch2 / 2), to(x2 + cw2 / 2 + 2000, y2 + ch2 / 2 + 2000))   # não sai do quadro
    x3, y3, cw3, ch3 = w.crop_rect
    assert x3 + cw3 == W and y3 + ch3 == H and (cw3, ch3) == (cw, ch), w.crop_rect
    _drag(pv, to(x3, y3 + ch3 / 2), to(x3 - 50, y3 + ch3 / 2))   # alça "w": só a esquerda
    assert w.crop_rect[0] < x3 and w.crop_rect[0] + w.crop_rect[2] == W, w.crop_rect
    # campos sincronizados com a prévia e vice-versa
    assert (w.sp_cx.value(), w.sp_cy.value(), w.sp_cw.value(), w.sp_ch.value()) == w.crop_rect
    w.sp_cx.setValue(40); w.sp_cy.setValue(30); w.sp_cw.setValue(201); w.sp_ch.setValue(151)
    assert w.crop_rect == (40, 30, 201, 151) and pv.crop == (40, 30, 201, 151), (w.crop_rect, pv.crop)
    w.sp_cw.setValue(W)                                # largura maior que cabe: desloca para a esquerda
    assert w.crop_rect[0] == 0 and w.crop_rect[2] == W, w.crop_rect
    w.sp_cw.setValue(201)
    assert "201×151" in w.lbl_out_info.text().replace(" ", "") or "201×151" in w.lbl_out_info.text(), w.lbl_out_info.text()
    # Redefinir / Auto
    w.btn_crop_reset.click()
    assert w.crop_rect == (0, 0, W, H) and w.crop_for_export() is None
    w.sp_crop_margin.setValue(4)
    w.last_auto_crop = None
    w.btn_crop_auto.click()
    assert wait(lambda: not w.is_auto_cropping() and w.last_auto_crop is not None, 60), "recorte automático não terminou"
    pump(0.1)
    rect, err = w.last_auto_crop
    assert not err and rect and w.crop_rect == tuple(rect), (w.last_auto_crop, w.crop_rect)
    assert rect[2] < W and rect[3] < H, rect
    assert w.btn_crop_auto.isEnabled()
    auto = w.crop_rect
    # "Lado a lado": dois painéis, arrastar no da direita também funciona
    w.cmb_view.setCurrentIndex(4); w.render_preview(); pump(0.4)
    panes = pv._panes()
    assert pv.side_by_side and len(panes) == 2, (pv.side_by_side, len(panes))
    w.set_crop((200, 150, 200, 100))                    # (10, 10) fica fora: arrastar desenha um novo
    rp = panes[1]; f2 = rp.width() / W
    _drag(pv, (rp.left() + 10 * f2, rp.top() + 10 * f2), (rp.left() + 110 * f2, rp.top() + 60 * f2))
    x, y, cw, ch = w.crop_rect
    assert abs(x - 10) <= 4 and abs(y - 10) <= 4 and abs(cw - 100) <= 6 and abs(ch - 50) <= 6, w.crop_rect
    w.cmb_view.setCurrentIndex(0)
    w.set_crop(auto)
    pv.grab()                                          # pintura do overlay sem erro
    # exportar pelo botão com o recorte
    out_dir = os.path.join(TMP, "recorte_ui"); os.makedirs(out_dir, exist_ok=True)
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: out_dir)
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (os.path.join(out_dir, "anim"), ""))
    w.sp_in.setValue(1); w.sp_out.setValue(4)          # campos começam em 1
    for key, even in (("png", False), ("png", True), ("webm", False)):
        w.chk_crop_even.setChecked(even)
        w.cmb_fmt.setCurrentIndex([f.key for f in FORMATS].index(key))
        o = w.export_options()
        assert o.crop == auto and o.even == even, (o.crop, o.even)
        w.btn_export.click()
        assert wait(lambda: not w.is_exporting()), "exportação não terminou"
        pump(0.05)
        n, canc, err, out = w.last_export
        assert not err and n == 4, w.last_export
        ew, eh = auto[2], auto[3]
        if even or key == "webm":
            ew, eh = ew + ew % 2, eh + eh % 2
        if key == "png":
            fn = sorted(f for f in os.listdir(out) if f.endswith(".png"))[-1]
            size = Image.open(os.path.join(out, fn)).size
            assert size == (ew, eh), (size, (ew, eh))
        assert f"{ew}×{eh}" in w.lbl_out_info.text(), w.lbl_out_info.text()
    w.chk_crop_even.setChecked(False)
    assert not errors, errors
    # troca de idioma: janela recriada mantém recorte e o modo
    w2 = ctrl.set_language("en") or ctrl.window; pump(0.4)
    assert w2.crop_rect == auto and w2.btn_crop.isChecked() and w2.preview.crop == auto, (w2.crop_rect, auto)
    ctrl.set_language("pt-BR"); pump(0.4); w = ctrl.window
    w.shutdown(); w.close(); pump(0.2)
    # preferências: o recorte volta para vídeos do mesmo tamanho; outro tamanho é ignorado
    ctrl, w = make_window(VID)
    assert w.crop_rect == auto and not w.btn_crop.isChecked(), (w.crop_rect, auto)
    w.load_video(os.path.join(OUT, "teste_cabelo_loiro.mp4")); pump(0.3)
    assert w.crop_rect == (0, 0, w.video.width, w.video.height), w.crop_rect
    w.set_crop((900, 500, 60, 40)); w.shutdown(); w.close(); pump(0.2)   # grava o recorte do 960×540
    ctrl, w = make_window(VID)                          # 640×360: (900, 500…) não caberia
    assert w.crop_rect == auto
    w.load_video(os.path.join(OUT, "teste_cabelo_loiro.mp4")); pump(0.3)
    assert w.crop_rect == (900, 500, 60, 40), w.crop_rect
    w.reset_crop(); w.shutdown(); w.close(); pump(0.2)
    import json
    store = json.loads(ctrl.settings.get("crops"))
    assert "960x540" not in store and store.get("640x360") == list(auto), store
    # recorte salvo que não cabe (preferência corrompida/antiga) é ignorado
    store["640x360"] = [600, 300, 100, 100]; ctrl.settings.set("crops", json.dumps(store))
    ctrl, w = make_window(VID)
    assert w.crop_rect == (0, 0, 640, 360), w.crop_rect
    ctrl.settings.set("crops", "{lixo"); w.load_video(VID); pump(0.2)
    assert w.crop_rect == (0, 0, 640, 360)
    w.shutdown(); w.close(); pump(0.2)
    print(f"RECORTE NA INTERFACE OK: desenhar/alças/mover/lado a lado, campos, Auto={auto}, Redefinir, "
          f"exportação pelo botão (png/pares/webm), idioma e preferências por tamanho")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("export", "all"):
        test_export()
    if what in ("crop", "all"):
        test_crop_ui()
    if what in ("stress", "all"):
        test_stress(VID, 15)
        make_1080p()
        test_stress(VID1080, 25)
    # erro não tratado num slot: vai para o log em vez de fechar em silêncio
    from PySide6.QtCore import QTimer
    def boom():
        raise RuntimeError("teste do registro de erros")
    QTimer.singleShot(0, boom)
    try:
        pump(0.2)        # algumas versões do PySide6 repassam o erro para processEvents() após o hook
    except RuntimeError as e:
        sys.excepthook(type(e), e, e.__traceback__)   # em app.exec() o PySide chama o hook direto
    txt = open(crashlog.error_log_path(), encoding="utf-8").read()
    assert "teste do registro de erros" in txt, txt[-500:]
    assert os.path.exists(crashlog.crash_log_path())
    print("CRASHLOG OK:", crashlog.error_log_path())
    shutil.rmtree(TMP, ignore_errors=True)
    print("UI OK")
