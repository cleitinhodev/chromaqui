"""Testes da interface real (offscreen): exportar clicando no botão (diálogos simulados) para TODOS os
formatos, com configurações novas e já salvas; e estresse da reprodução trocando a qualidade.
Uso: python tests/test_ui_flows.py [export|stress|all]"""
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
    for k in range(60):                        # reinícios rápidos (corrida entre a thread antiga e a nova)
        w.stop_play(); w.start_play(); pump(0.0 if k % 2 else 0.02)
        assert w.is_playing(), "reinício falhou"
    w.cmb_playq.setCurrentIndex(2); w.start_play(); pump(1.5)
    assert w.is_playing(), "parou de reproduzir"
    w.stop_play(); pump(0.2)
    leaked = [t for t in getattr(w, "_old_play_threads", []) if t.isRunning()]
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


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("export", "all"):
        test_export()
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
