"""Testes da interface real (offscreen): exportar clicando no botão (diálogos simulados) para TODOS os
formatos, com configurações novas e já salvas; e estresse da reprodução trocando a qualidade.
Uso: python tests/test_ui_flows.py [export|crop|beta|stress|all]"""
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


def test_beta_ui():
    """Recursos da 3.2 (beta) pela interface: pincel + desfazer/refazer, comparar, sombra/brilho, IA (erro e
    modelo local), recorte que segue / quadros-chave, sprite sheet, lote, atualização e troca de idioma."""
    from PIL import Image
    from chromaqui import ai, core
    print("beta: interface …")
    os.environ["CHROMAQUI_MODELS_DIR"] = os.path.join(TMP, "models")
    ctrl, w = make_window(VID)
    W, H = w.video.width, w.video.height
    pv = w.preview
    w.render_preview(); pump(0.3)
    # ---- pincel: manter/remover, só neste quadro, desfazer/refazer
    assert w.retouch is not None and w.retouch.is_empty() and w.btn_brush.isEnabled()
    w.btn_crop.setChecked(True)
    w.btn_brush.setChecked(True); pump(0.05)
    assert pv.brush_mode and not w.btn_crop.isChecked(), "pincel e recorte devem se excluir"
    pane = pv._panes()[0]
    sx = pane.width() / W
    to = lambda x, y: (pane.left() + x * sx, pane.top() + y * sx)
    w.sl_brush_size.setValue(20)
    w.set_brush_mode_key("remove")
    _drag(pv, to(100, 180), to(160, 180))           # remove um trecho do objeto
    assert not w.retouch.is_empty() and w.retouch.static is not None, "pincelada não registrada"
    p = w.params()
    f0 = w.video.read(0)
    a = core.compute_alpha(f0, p)
    assert a[180, 130] < 0.05, a[180, 130]
    assert len(w._undo) == 1 and w._undo[-1][0] == "brush", w._undo
    w.undo(); pump(0.05)
    assert w.retouch.is_empty() or not w.retouch.static.any(), "desfazer o pincel"
    w.redo(); pump(0.05)
    assert w.retouch.static.any(), "refazer o pincel"
    w.chk_brush_frame.setChecked(True); w.set_brush_mode_key("keep")
    w.slider.setValue(3); pump(0.1)
    _drag(pv, to(400, 80), to(440, 80))             # mantém um trecho do fundo, só no quadro 4
    assert w.retouch.frame_count() == 1 and 3 in w.retouch.frames, w.retouch.frames
    pf = w.params(); pf.frame_idx = 3
    assert core.compute_alpha(w.video.read(3), pf)[80, 420] > 0.95
    pf.frame_idx = 4
    assert core.compute_alpha(w.video.read(4), pf)[80, 420] < 0.05, "retoque de um quadro vazou para outro"
    w.btn_rt_clear_frame.click()
    assert w.retouch.frame_count() == 0 or not w.retouch.frames[3].any()
    w.undo()
    assert w.retouch.frames[3].any(), "desfazer 'limpar quadro'"
    w.btn_brush.setChecked(False)
    # ---- desfazer/refazer de parâmetros (Ctrl+Z / Ctrl+Y), agrupando mudanças seguidas
    key, s = next((k, s) for k, s in w.sliders.items() if hasattr(s, "slider") and
                  s.slider.maximum() - s.value() > 5)
    v0 = s.value()
    for v in (v0 + 1, v0 + 2, v0 + 3):
        s.setValue(v); pump(0.02)
    pump(0.6)
    v1 = s.value()
    w.set_key((0, 0, 255)); pump(0.6)
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    QTest.keyClick(w, Qt.Key_Z, Qt.ControlModifier); pump(0.05)
    assert tuple(w.key_rgb) != (0, 0, 255), w.key_rgb
    QTest.keyClick(w, Qt.Key_Z, Qt.ControlModifier); pump(0.05)
    assert s.value() == v0, (s.value(), v0)
    QTest.keyClick(w, Qt.Key_Y, Qt.ControlModifier); pump(0.05)
    assert s.value() == v1, (s.value(), v1)
    w.redo()
    assert tuple(w.key_rgb) == (0, 0, 255)
    w.undo(); w.undo()
    # ---- comparar antes/depois
    w.btn_compare.setChecked(True); w.render_preview(); pump(0.3)
    assert pv.compare_active() and pv._before is not None
    pv.set_split(0.3); pv.grab()
    w.btn_before.pressed.emit(); pump(0.05)
    assert pv.show_before
    pv.grab()
    w.btn_before.released.emit()
    assert not pv.show_before
    w.btn_compare.setChecked(False)
    # ---- sombra / brilho
    w.chk_glow.setChecked(True)
    w.cmb_glow_mode.setCurrentIndex(1); w._on_glow_mode()
    assert w.glow["on"] and w.glow["mode"] == "neon" and w.params().glow["mode"] == "neon"
    w.glow_sliders["opacity"].setValue(80)
    assert w.params().glow["opacity"] == 80
    out_dir = os.path.join(TMP, "beta"); os.makedirs(out_dir, exist_ok=True)
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: out_dir)
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (os.path.join(out_dir, "anim"), ""))
    w.retouch.clear()
    w.sp_in.setValue(1); w.sp_out.setValue(3)
    w.cmb_fmt.setCurrentIndex([f.key for f in FORMATS].index("png"))
    def export_alpha():
        w.btn_export.click()
        assert wait(lambda: not w.is_exporting()), "exportação não terminou"
        pump(0.05)
        n, canc, err, out = w.last_export
        assert not err and n == 3, w.last_export
        fn = sorted(f for f in os.listdir(out) if f.endswith(".png"))[0]
        return np.asarray(Image.open(os.path.join(out, fn)).convert("RGBA"))[..., 3]
    with_glow = export_alpha()
    w.chk_glow_export.setChecked(False)
    without = export_alpha()
    assert (with_glow > 0).sum() > (without > 0).sum() * 1.02, ((with_glow > 0).sum(), (without > 0).sum())
    w.chk_glow.setChecked(False); w.chk_glow_export.setChecked(True)
    # ---- IA: erro de download volta para a cor-chave; modelo presente ativa a IA
    orig = dict(ai.MODELS["u2netp"])
    ai.MODELS["u2netp"]["url"] = "http://127.0.0.1:9/nada.onnx"
    w.cmb_ai_model.setCurrentIndex(w.cmb_ai_model.findData("u2netp"))
    n_err = len(errors)
    w.cmb_source.setCurrentIndex(1); w._on_source()
    assert wait(lambda: not w.is_downloading(), 60)
    pump(0.1)
    assert w.matte_source == "chroma" and w.cmb_source.currentData() == "chroma", w.matte_source
    assert w.last_model_download[1] and "modelo" in w.lbl_ai.text().lower(), (w.last_model_download, w.lbl_ai.text())
    assert len(errors) == n_err and not w.btn_ai_dl.isHidden(), errors[n_err:]
    ai.MODELS["u2netp"].update(orig)
    local = os.path.join(os.environ.get("CHROMAQUI_TEST_MODELS", "/workspace/models"), "u2netp.onnx")
    if os.path.exists(local) and ai.runtime_available():
        ai.MODELS["u2netp"]["url"] = "file://" + local
        w.cmb_source.setCurrentIndex(1); w._on_source()
        assert wait(lambda: not w.is_downloading(), 60)
        pump(0.1)
        assert w.matte_source == "ai" and w.params().source == "ai" and w.params().ai_model == "u2netp", \
            w.last_model_download
        w.render_preview(); pump(0.5)
        ai.MODELS["u2netp"].update(orig)
        print("   IA: modelo local baixado e ativado")
    else:
        print("   IA: modelo local ausente (CI) — só o caminho de erro foi testado")
    w.cmb_source.setCurrentIndex(0); w._on_source()
    assert w.params().source == "chroma"
    # ---- recorte que segue o objeto
    w.cmb_motion.setCurrentIndex(w.cmb_motion.findData("follow")); w._on_motion()
    assert not w.btn_crop.isEnabled() and w.export_options().crop_motion == "follow"
    w.sp_in.setValue(1); w.sp_out.setValue(10)
    w.btn_track.click()
    assert wait(lambda: not w.is_tracking() and w.track_path, 60), "análise do movimento não terminou"
    pump(0.1)
    tw, th = next(iter(w.track_path.values()))[2:]
    w.slider.setValue(5); pump(0.1)
    assert w.crop_rect[2:] == (tw, th), (w.crop_rect, tw, th)
    assert f"{tw}×{th}" in w.lbl_out_info.text(), (w.lbl_out_info.text(), w._track_sig, w._track_signature())
    w.cmb_fmt.setCurrentIndex([f.key for f in FORMATS].index("gif"))
    w.btn_export.click()
    assert wait(lambda: not w.is_exporting()), "exportação não terminou"
    pump(0.05)
    n, canc, err, out = w.last_export
    assert not err and n == 10, w.last_export
    assert Image.open(out).size == (tw, th), (Image.open(out).size, (tw, th))
    # ---- quadros-chave: mover a área num quadro marca um quadro-chave
    w.cmb_motion.setCurrentIndex(w.cmb_motion.findData("keys")); w._on_motion()
    w.clear_crop_keys()
    w.slider.setValue(0); pump(0.1); w.set_crop((0, 0, 200, 120)); pump(0.5)   # pausa: passos de desfazer separados
    w.slider.setValue(9); pump(0.1); w.set_crop((400, 200, 200, 120)); pump(0.5)
    assert sorted(w.crop_keys) == [0, 9], w.crop_keys
    w.slider.setValue(4); pump(0.1)
    assert 0 < w.crop_rect[0] < 400 and sorted(w.crop_keys) == [0, 9], (w.crop_rect, w.crop_keys)
    o = w.export_options()
    assert o.crop_motion == "keys" and o.crop_keys[9] == (400, 200, 200, 120)
    w.undo()                                    # desfaz o último quadro-chave
    assert sorted(w.crop_keys) == [0], w.crop_keys
    w.cmb_motion.setCurrentIndex(0); w._on_motion()
    w.reset_crop()
    # ---- sprite sheet pelas opções da interface
    w.cmb_fmt.setCurrentIndex([f.key for f in FORMATS].index("sheet"))
    assert w.sp_sheet_cols.isVisible() or not w.isVisible()
    w.sp_sheet_cols.setValue(5); w.sp_sheet_pad.setValue(4); w.chk_sheet_trim.setChecked(False)
    w.cmb_sheet_json.setCurrentIndex(1)
    w.btn_export.click()
    assert wait(lambda: not w.is_exporting()), "exportação não terminou"
    pump(0.05)
    n, canc, err, out = w.last_export
    assert not err and n == 10, w.last_export
    import json as _json
    js = _json.load(open(os.path.splitext(out)[0] + ".json"))
    assert isinstance(js["frames"], list) and len(js["frames"]) == 10, js.keys()
    assert Image.open(out).size == (5 * W + 4 * 4, 2 * H + 4), Image.open(out).size
    assert "Sprite sheet" in w.lbl_out_info.text(), w.lbl_out_info.text()
    # ---- exportação em lote (2 vídeos) e cancelamento
    w.cmb_fmt.setCurrentIndex([f.key for f in FORMATS].index("gif"))
    d = w.open_batch()
    d.add_videos([VID, os.path.join(OUT, "teste_cabelo_loiro.mp4"), VID])     # repetido é ignorado
    assert len(d.paths) == 2
    bdir = os.path.join(TMP, "lote"); d.ed_out.setText(bdir)
    assert d.start()
    assert wait(lambda: not d.running(), 240), "lote não terminou"
    pump(0.1)
    canc, res = d.last_result
    assert not canc and all(r and not r[1] for r in res), res
    for r in res:
        assert os.path.exists(r[2]) and r[2].endswith(".gif"), r
    assert d.start(); pump(0.05); d.cancel()
    assert wait(lambda: not d.running(), 120)
    pump(0.1)
    assert d.last_result[0], "cancelamento do lote"
    d.close()
    # ---- atualização (sem rede: fetch simulado)
    info = {"version": "9.9.9", "url": "https://github.com/cleitinhodev/chromaqui/releases/tag/v9.9.9",
            "prerelease": False, "name": "v9.9.9"}
    w.last_update_info = "?"
    w.check_updates(manual=True, fetch=lambda cur, b: info)
    assert wait(lambda: w.last_update_info != "?", 10)
    assert w.last_update_info == info
    ctrl.quiet = False
    w.last_update_info = "?"
    w.check_updates(manual=False, fetch=lambda cur, b: info)
    assert wait(lambda: w.last_update_info != "?", 10)
    pump(0.05)
    assert w.update_box.isVisible() and "9.9.9" in w.update_box.text()
    w.update_box.close()
    ctrl.quiet = True
    def boom(cur, b):
        raise OSError("sem rede")
    w.last_update_info = "?"
    w.check_updates(manual=False, fetch=boom)              # falha de rede: silenciosa
    assert wait(lambda: w.last_update_info != "?", 10) and w.last_update_info is None
    os.environ["CHROMAQUI_NO_UPDATE_CHECK"] = "1"
    assert not w.schedule_update_check()
    # ---- troca de idioma mantém sombra, retoque e modo do recorte
    w.chk_glow.setChecked(True)
    w.btn_brush.setChecked(True); w.chk_brush_frame.setChecked(False)
    _drag(pv, to(300, 180), to(330, 180))
    rt = w.retouch
    w2 = ctrl.set_language("en") or ctrl.window; pump(0.4)
    assert w2.glow["on"] and w2.retouch is rt and w2.chk_glow.isChecked(), "estado perdido na troca de idioma"
    assert "beta" in w2.windowTitle().lower(), w2.windowTitle()
    ctrl.set_language("pt-BR"); pump(0.3); w = ctrl.window
    import chromaqui.app as appmod
    w.shutdown(); w.close(); pump(0.2)
    assert wait(lambda: not appmod._RETIRED, 30), "threads pendentes"
    assert not errors, errors
    print("BETA NA INTERFACE OK: pincel, desfazer/refazer, comparar, sombra/brilho, IA, seguir/quadros-chave, "
          "sprite sheet, lote, atualização e idioma")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("export", "all"):
        test_export()
    if what in ("crop", "all"):
        test_crop_ui()
    if what in ("beta", "all"):
        test_beta_ui()
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
