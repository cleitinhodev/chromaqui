"""Auto-teste do programa (também roda dentro do .exe):

    Chromaqui.exe --self-test [video] [pasta_saida]

Abre a janela sem exibir e testa tema, idioma, presets, visualizações, reprodução, fundo,
renderização CPU/GPU e TODOS os formatos de exportação. Grava selftest.log na pasta."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import traceback

import cv2
import numpy as np


def _pump(app, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.005)


def _wait(app, cond, timeout=120):
    t0 = time.time()
    while not cond() and time.time() - t0 < timeout:
        app.processEvents()
        time.sleep(0.01)
    return cond()


def _ffmpeg_info(path):
    from .exporters import _no_window, ffmpeg_exe
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", path], capture_output=True, **_no_window())
    return r.stderr.decode("utf-8", "replace")


def _ffmpeg_decode_alpha(path, vp9=False):
    from .exporters import _no_window, ffmpeg_exe
    args = [ffmpeg_exe(), "-hide_banner"] + (["-c:v", "libvpx-vp9"] if vp9 else []) + \
        ["-i", path, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "-"]
    r = subprocess.run(args, capture_output=True, **_no_window())
    a = np.frombuffer(r.stdout, np.uint8).reshape(-1, 4)[:, 3]
    return r.stderr.decode("utf-8", "replace"), int(a.min()), int(a.max())


def verify_output(key, out, expected):
    """Confere o arquivo/pasta exportado. Retorna descrição curta (ou lança AssertionError)."""
    from PIL import Image
    from .exporters import FORMAT_BY_KEY
    f = FORMAT_BY_KEY[key]
    if not f.single_file:
        files = sorted(n for n in os.listdir(out) if n.endswith(f.ext))
        assert len(files) == expected, (key, len(files))
        p = os.path.join(out, files[len(files) // 2])
        if key == "tga":
            arr = np.asarray(Image.open(p).convert("RGBA"))
        else:
            arr = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_UNCHANGED)
        assert arr.ndim == 3 and arr.shape[2] == 4, (key, arr.shape)
        a = arr[..., 3]
        assert a.min() == 0 and a.max() == a.dtype.type(np.iinfo(a.dtype).max), key
        return f"{len(files)} arquivos {arr.dtype}"
    assert os.path.getsize(out) > 0, key
    if key == "gif":
        g = Image.open(out)
        tr = g.info.get("transparency")
        n = g.n_frames
        g.seek(n // 2)
        a = np.asarray(g.convert("RGBA"))[..., 3]
        assert n == expected and tr is not None and a.min() == 0 and a.max() == 255, (n, tr)
        return f"{n} quadros, transparência (índice {tr}), {100 * (a == 0).mean():.0f}% transparente"
    if key in ("webp", "apng"):
        im = Image.open(out)
        n = im.n_frames
        im.seek(n // 2)
        a = np.asarray(im.convert("RGBA"))[..., 3]
        assert n == expected and a.min() < 10 and a.max() > 245, (key, n, a.min(), a.max())
        return f"{n} quadros, alfa {a.min()}..{a.max()}"
    if key == "webm":
        info = _ffmpeg_info(out)
        err, amin, amax = _ffmpeg_decode_alpha(out, vp9=True)
        assert "vp9" in info and re.search(r"alpha_mode\s*:\s*1", info, re.I), info[-400:]
        assert "yuva420p" in err and amin < 10 and amax > 245, (err[-300:], amin, amax)
        return f"vp9 yuva420p (alpha_mode=1), alfa {amin}..{amax}"
    if key == "prores":
        info = _ffmpeg_info(out)
        err, amin, amax = _ffmpeg_decode_alpha(out)
        assert "prores" in info and "4444" in info and "yuva444p" in info, info[-400:]
        assert amin < 10 and amax > 245, (amin, amax)
        m = re.search(r"yuva444p\w*", info)
        return f"prores 4444 {m.group(0) if m else ''}, alfa {amin}..{amax}"
    return "ok"


def self_test(argv):
    args = [a for a in argv[1:] if a != "--self-test"]
    log_dir = args[1] if len(args) > 1 else os.getcwd()
    os.makedirs(log_dir, exist_ok=True)
    os.environ["CHROMAQUI_SETTINGS"] = os.path.join(log_dir, "selftest_settings.ini")
    try:
        os.remove(os.environ["CHROMAQUI_SETTINGS"])
    except OSError:
        pass
    lines, code = [], 0
    log_path = os.path.join(log_dir, "selftest.log")
    live = open(log_path, "w", encoding="utf-8")  # gravado a cada linha (diagnóstico se travar)
    try:
        import faulthandler
        crash = open(os.path.join(log_dir, "selftest_crash.log"), "w", encoding="utf-8")
        faulthandler.enable(crash, all_threads=True)
    except Exception:  # noqa: BLE001
        pass

    def log(s):
        lines.append(s)
        try:
            live.write(s + "\n")
            live.flush()
        except Exception:  # noqa: BLE001
            pass
        try:
            print(s, flush=True)
        except Exception:  # console sem UTF-8 (cp1252) ou sem stdout (--windowed)
            try:
                enc = getattr(sys.stdout, "encoding", None) or "ascii"
                print(s.encode(enc, "replace").decode(enc), flush=True)
            except Exception:
                pass

    try:
        from PySide6.QtWidgets import QApplication
        from . import APP_NAME, __version__, core, gpu, i18n, theme
        from .app import BACKGROUNDS, VIEWS, Controller
        from .exporters import FORMATS, ffmpeg_exe
        from .dialogs import AboutDialog, SettingsDialog
        from PySide6.QtCore import qInstallMessageHandler
        _prev = {}

        def _qt_msg(mode, ctx, msg):          # silencia avisos inofensivos da plataforma "offscreen"
            if "propagateSizeHints" in msg:
                return
            if "QThread" in msg or "ASSERT" in msg or mode.name in ("QtCriticalMsg", "QtFatalMsg"):
                try:
                    live.write(f"QT {mode.name}: {msg}\n")
                    live.flush()
                except Exception:  # noqa: BLE001
                    pass
            if sys.stderr is not None:          # .exe --windowed não tem stderr
                try:
                    sys.stderr.write(msg + "\n")
                except Exception:  # noqa: BLE001
                    pass
        _prev["h"] = qInstallMessageHandler(_qt_msg)
        app = QApplication.instance() or QApplication(sys.argv[:1])
        ctrl = Controller(app)
        ctrl.quiet = True
        w = ctrl.create_window()
        w.show()
        app.processEvents()
        assert w.windowTitle().startswith(APP_NAME)
        log(f"GUI OK {APP_NAME} {__version__}")

        # ---- tema
        for t in ("light", "dark"):
            ctrl.set_theme(t)
            app.processEvents()
            pal = theme.palette(t, ctrl.accent())
            assert pal["bg"] in app.styleSheet() and ctrl.settings.get("theme") == t
        log(f"THEME OK (claro/escuro, destaque {ctrl.accent()}, salvo nas configurações)")
        ctrl.set_fx(animations=False, neon=False)
        assert w.btn_export.graphicsEffect() is None
        ctrl.set_fx(animations=True, neon=True)
        assert w.btn_export.graphicsEffect() is not None
        log("FX OK (animações e neon ligam/desligam)")
        from .dialogs import app_icon, logo_pixmap
        sizes = sorted(sz.width() for sz in app_icon().availableSizes())
        assert {16, 32, 48, 256} <= set(sizes), sizes
        lp = logo_pixmap(112).toImage()
        assert not lp.isNull() and lp.hasAlphaChannel() and lp.pixelColor(1, 1).alpha() == 0
        log(f"ÍCONE OK (icon.ico {sizes}, logo.png transparente)")
        ab = AboutDialog(w)
        assert "github.com/cleitinhodev" in ab.links.text() and "bugzinho.com/donate" in ab.links.text()
        ab.deleteLater()
        sd = SettingsDialog(ctrl, w)
        sd.deleteLater()
        log("SOBRE OK (versão, ícone, 3 links) · CONFIGURAÇÕES OK")

        if args:
            video = args[0]
            w.load_video(video)
            # ---- idioma (troca na hora, mantendo vídeo e quadro)
            w.slider.setValue(5)
            _pump(app, 0.2)
            keys = set()
            for code_, _name in i18n.LANGUAGES:
                if code_ == "pt-BR":
                    continue
                import json
                with open(i18n.lang_file(code_), encoding="utf-8") as fh:
                    d = json.load(fh)
                keys |= set(k for k in d if not k.startswith("@"))
            covs = {}
            for code_, _name in i18n.LANGUAGES:
                w = ctrl.set_language(code_)
                app.processEvents()
                exp_txt = i18n.T("Exportar…")
                assert w.btn_export.text() == exp_txt and w.path == video and w.slider.value() == 5, \
                    (code_, w.btn_export.text(), w.slider.value())
                covs[code_] = i18n.coverage(code_, keys)
            ctrl.set_language("en")
            assert ctrl.window.btn_export.text() == "Export…", ctrl.window.btn_export.text()
            w = ctrl.set_language("pt-BR")
            assert w.btn_export.text() == "Exportar…" and ctrl.settings.get("lang") == "pt-BR"
            log("LANG OK (" + ", ".join(f"{c} {v * 100:.0f}%" for c, v in covs.items()) + "; troca na hora)")

            # ---- presets
            for k, v in {"choke": 10, "soften": 10, "spill": 70, "desaturate": 30, "saturation": 110,
                         "cw_amount": 55, "cw_keyonly": 0, "cw_reach": 40}.items():
                w.sliders[k].setValue(v)
            pp = os.path.join(log_dir, "preset_teste.json")
            core.save_preset(pp, w.params())
            w.reset_defaults()
            w.apply_params(core.load_preset(pp))
            assert w.sliders["choke"].value() == 10 and w.sliders["cw_keyonly"].value() == 0
            log("PRESET OK")
            w.reset_defaults()
            for i in range(len(VIEWS)):
                w.cmb_view.setCurrentIndex(i)
                w.render_preview()
                _pump(app, 0.4)
            log(f"VIEWS OK ({len(VIEWS)})")
            w.cmb_view.setCurrentIndex(0)

            # ---- renderização
            res = []
            for m in ("cpu", "gpu", "auto"):
                ctrl.set_render(m)
                w.render_preview()
                _pump(app, 0.4)
                res.append(f"{m}→{'GPU' if gpu.enabled() else 'CPU'}")
            log("RENDER OK (" + ", ".join(res) + f"; em uso: {gpu.describe()}; {w.lbl_perf.text()})")

            # ---- fundo (imagem)
            bgp = os.path.join(log_dir, "fundo_teste.png")
            h0, w0 = w.video.height, w.video.width
            grad = np.zeros((h0 // 2, w0 // 2, 3), np.uint8)
            grad[..., 0] = np.linspace(0, 255, w0 // 2)[None]
            grad[..., 2] = 200
            cv2.imencode(".png", grad)[1].tofile(bgp)
            for mode in ("fit", "stretch", "fill"):
                assert w.set_background(bgp, mode)
                w.render_preview()
                _pump(app, 0.3)
            assert BACKGROUNDS[w.cmb_bg.currentIndex()] == "midia" and w.background.active
            fr = w.background.frame(0, 320, 180)
            assert fr.shape == (180, 320, 3)
            log("BG OK (imagem de fundo: ajustar/esticar/preencher na prévia)")

            # ---- reprodução
            got = []
            w.sp_fps.setValue(24)
            w.chk_loop.setChecked(True)
            w.slider.setValue(0)
            w.start_play()
            w.play_worker.frame.connect(lambda i, *_: got.append(i))
            _pump(app, 2.5)
            assert w.is_playing() and len(got) > 5, f"reprodução não avançou ({len(got)})"
            fps_txt = w.lbl_fps.text()
            w.toggle_play()
            app.processEvents()
            assert not w.is_playing()
            log(f"PLAY OK {len(got)} quadros em 2,5 s com fundo, {fps_txt}")
            # trocar a qualidade e reiniciar várias vezes durante a reprodução (antes: travava/fechava)
            w.start_play()
            for k in range(90):
                w.cmb_playq.setCurrentIndex(k % 3)
                if k % 3 == 0:
                    w.stop_play()
                    w.start_play()
                _pump(app, 0.0 if k % 2 else 0.03)
            w.cmb_playq.setCurrentIndex(2)
            _pump(app, 1.0)
            assert w.is_playing(), "reprodução parou ao trocar a qualidade"
            w.stop_play()
            w.cmb_playq.setCurrentIndex(0)
            app.processEvents()
            log("PLAY QUALIDADE OK (90 trocas Rápida/Média/Completa + reinícios, sem travar)")

            # ---- exportação: todos os formatos (pela interface)
            w.sp_in.setValue(3)
            w.sp_out.setValue(14)
            w.sp_step.setValue(2)
            w.cmb_scale.setCurrentIndex(3)          # 0,5x
            w.chk_include_bg.setChecked(False)
            expected = 6
            log(f"ffmpeg: {ffmpeg_exe()}")
            for i, f in enumerate(FORMATS):
                w.cmb_fmt.setCurrentIndex(i)
                out = os.path.join(log_dir, "export_" + f.key + (f.ext if f.single_file else ""))
                t0 = time.time()
                w.start_export(out)
                assert _wait(app, lambda: not w.is_exporting(), 300), "exportação travou"
                n, cancelled, err, output = w.last_export
                assert not err, f"{f.key}: {err}"
                assert n == expected, (f.key, n)
                desc = verify_output(f.key, output, expected)
                log(f"EXPORT {f.key.upper()} OK {desc} ({time.time() - t0:.1f} s)")
            # TIFF 16 bits (tifffile) e marcação do alfa (ExtraSamples) nos dois modos
            import tifffile
            from .core import ExportOptions
            from .exporters import _SeqWriter
            for b16 in (False, True):
                o = ExportOptions(fmt="tiff", bit16=b16, prefix="t16_" if b16 else "t8_")
                sw = _SeqWriter(os.path.join(log_dir, "export_tiff_bits"), o, ".tif")
                sw.write(np.random.rand(24, 32, 3).astype(np.float32), np.random.rand(24, 32).astype(np.float32))
                pg = tifffile.TiffFile(sw.files[0]).pages[0]
                assert pg.shape == (24, 32, 4) and pg.dtype == (np.uint16 if b16 else np.uint8), (pg.shape, pg.dtype)
                assert int(pg.extrasamples[0]) == 2, pg.extrasamples
            log("EXPORT TIFF 8/16 bits OK (alfa marcado como ExtraSamples)")
            # fundo incluído
            w.cmb_fmt.setCurrentIndex(0)
            w.chk_include_bg.setChecked(True)
            out = os.path.join(log_dir, "export_com_fundo")
            w.start_export(out)
            assert _wait(app, lambda: not w.is_exporting(), 300)
            img = cv2.imdecode(np.fromfile(os.path.join(out, "frame_00001.png"), np.uint8), cv2.IMREAD_UNCHANGED)
            assert img[..., 3].min() == 255, "fundo incluído deveria ser opaco"
            assert abs(int(img[2, 2, 2]) - 200) < 8, img[2, 2]
            log("EXPORT FUNDO OK (fundo composto, resultado opaco)")
            from .core import export_geometry as core_export_geometry
            # recorte da área exportada (automático + manual), com fundo e em formato de vídeo (pares)
            w.chk_include_bg.setChecked(False)
            w.last_auto_crop = None
            w.auto_crop()
            assert _wait(app, lambda: not w.is_auto_cropping() and w.last_auto_crop is not None, 120), \
                "recorte automático travou"
            _pump(app, 0.1)
            arect, aerr = w.last_auto_crop
            assert not aerr and arect and w.crop_rect == tuple(arect), w.last_auto_crop
            w.set_crop((101, 41, 301, 201))
            crop_sizes = []
            for key, bg in (("png", False), ("png", True), ("webm", False)):
                w.chk_include_bg.setChecked(bg)
                w.cmb_fmt.setCurrentIndex([f.key for f in FORMATS].index(key))
                o = w.export_options()
                _c, ow, oh = core_export_geometry(w.video.width, w.video.height, o)
                out = os.path.join(log_dir, f"export_recorte_{key}{'_fundo' if bg else ''}" + (".webm" if key == "webm" else ""))
                w.start_export(out)
                assert _wait(app, lambda: not w.is_exporting(), 300), "exportação com recorte travou"
                n, _c2, err, outp = w.last_export
                assert not err and n == expected, (key, w.last_export)
                if key == "png":
                    img = cv2.imdecode(np.fromfile(os.path.join(outp, "frame_00001.png"), np.uint8), cv2.IMREAD_UNCHANGED)
                    assert img.shape[:2] == (oh, ow), (img.shape, ow, oh)
                    if bg:
                        assert img[..., 3].min() == 255
                else:
                    info = _ffmpeg_info(outp)
                    assert f"{ow}x{oh}" in info and ow % 2 == 0 and oh % 2 == 0, (ow, oh, info[-300:])
                crop_sizes.append(f"{key}{'+fundo' if bg else ''} {ow}×{oh}")
            w.reset_crop()
            w.chk_include_bg.setChecked(False)
            log(f"RECORTE OK (automático {tuple(arect)}; {', '.join(crop_sizes)})")
            # exportar pelo BOTÃO (sinal clicked(bool)) com os diálogos simulados — antes dava
            # "expected str, bytes or os.PathLike object, not bool"
            from PySide6.QtWidgets import QFileDialog
            w.chk_include_bg.setChecked(False)
            saved = (QFileDialog.getExistingDirectory, QFileDialog.getSaveFileName)
            bdir = os.path.join(log_dir, "export_botao")
            os.makedirs(bdir, exist_ok=True)
            QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: bdir)
            QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (os.path.join(bdir, "botao"), ""))
            try:
                ctrl.settings.set("last_dir", os.path.join(log_dir, "pasta_que_nao_existe"))
                done = []
                for key in ("png", "gif", "webm"):
                    w.cmb_fmt.setCurrentIndex([f.key for f in FORMATS].index(key))
                    w.btn_export.click()
                    assert _wait(app, lambda: not w.is_exporting(), 300)
                    n, _c, err, outp = w.last_export
                    assert not err and n > 0 and os.path.exists(outp), (key, w.last_export)
                    done.append(key)
            finally:
                QFileDialog.getExistingDirectory, QFileDialog.getSaveFileName = saved
            log(f"EXPORT PELO BOTÃO OK ({', '.join(done)}; diálogo e pasta salva inexistente)")
            # cancelar
            w.chk_include_bg.setChecked(False)
            w.cmb_fmt.setCurrentIndex([f.key for f in FORMATS].index("webm"))
            w.sp_in.setValue(1)
            w.sp_out.setValue(w.video.frame_count)
            w.sp_step.setValue(1)
            out = os.path.join(log_dir, "cancelado.webm")
            w.start_export(out)
            w.cancel_export()
            assert _wait(app, lambda: not w.is_exporting(), 120)
            assert w.last_export[1] and not os.path.exists(out), w.last_export
            log("CANCELAR OK")
            w.cmb_scale.setCurrentIndex(0)
            w.render_preview()
            _pump(app, 0.8)
            w.grab().save(os.path.join(log_dir, "selftest_gui.png"))
        ctrl.window.shutdown()
        ctrl.window.close()
    except Exception:  # noqa: BLE001
        log("ERRO: " + traceback.format_exc())
        code = 1
    if code == 0:
        log("SELF-TEST OK")
    live.close()
    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return code
