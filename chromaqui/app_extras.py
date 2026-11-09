"""Recursos da 3.2 (beta) na janela principal: remoção por IA, retoque com pincel, sombra/brilho,
recorte que segue o objeto / quadros-chave, opções de sprite sheet, exportação em lote,
desfazer/refazer, comparação antes/depois e verificação de atualizações.
(Mixin de MainWindow: usa os widgets e métodos definidos em app.py.)"""
from __future__ import annotations

import copy
import json
import os

from PySide6.QtCore import Qt, QThread, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QHBoxLayout, QLabel, QMessageBox,
                               QProgressBar, QPushButton, QSpinBox, QWidget)

from . import IS_BETA, __version__, ai, core
from .i18n import T
from .retouch import Retouch
from .widgets import (ModelDownloadWorker, ParamSlider, Section, TrackWorker, UpdateWorker, bgr_to_qimage)

UNDO_LIMIT = 200
UNDO_IDLE_MS = 400           # mudanças seguidas (arrastar um controle) viram UM passo de desfazer
BRUSH_MODES = [("keep", "Manter"), ("remove", "Remover"), ("erase", "Borracha")]
MOTIONS = [("fixed", "Fixo"), ("follow", "Seguir o objeto"), ("keys", "Quadros-chave")]
SHEET_MAX = [1024, 2048, 4096, 8192, 16384]
GLOW_KEYS = [("blur", "Desfoque", 0, 100), ("dx", "Deslocamento X", -300, 300), ("dy", "Deslocamento Y", -300, 300),
             ("opacity", "Opacidade", 0, 100), ("spread", "Expansão", 0, 60)]


def _retire(thread, worker, wait_ms=0):
    from .app import retire_thread
    retire_thread(thread, worker, wait_ms)


class ExtrasMixin:
    # =============================================================== estado
    def _init_extras(self):
        self.retouch: Retouch | None = None
        self.glow = dict(core.GLOW_DEFAULTS)
        self.matte_source = "chroma"
        self.ai_model = "modnet"
        self.track_path = None              # {quadro: recorte} da última análise (prévia)
        self._track_sig = None
        self.crop_keys: dict = {}
        self.dl_thread = self.dl_worker = None
        self.track_thread = self.track_worker = None
        self.upd_thread = self.upd_worker = None
        self.batch_dialog = None
        self._undo, self._redo = [], []
        self._committed = None
        self._restoring = False
        self._stroke = None
        self._undo_timer = QTimer(self, singleShot=True, interval=UNDO_IDLE_MS)
        self._undo_timer.timeout.connect(self._commit_state)

    def _install_extra_shortcuts(self):
        for keys, fn in (((QKeySequence.Undo,), self.undo), ((QKeySequence.Redo, "Ctrl+Y", "Ctrl+Shift+Z"), self.redo)):
            seen = set()
            for k in keys:
                ks = QKeySequence(k)
                if ks.toString() in seen or ks.isEmpty():
                    continue
                seen.add(ks.toString())
                sc = QShortcut(ks, self)
                sc.setContext(Qt.WindowShortcut)
                sc.activated.connect(fn)
        b = QShortcut(QKeySequence("B"), self)
        b.activated.connect(lambda: self.btn_brush.isEnabled() and self.btn_brush.toggle())
        for key, d in (("[", -1), ("]", 1)):
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(lambda d=d: self.sl_brush_size.setValue(
                max(1, int(self.sl_brush_size.value() * (1.2 if d > 0 else 1 / 1.2)) + d)))

    # =============================================================== barra da prévia
    def _build_view_tools(self, top):
        """Desfazer/refazer e comparação antes/depois (na linha acima da prévia)."""
        self.btn_undo = QPushButton(T("Desfazer"))
        self.btn_undo.setToolTip(T("Desfaz a última mudança de ajuste, recorte ou pincel (Ctrl+Z)"))
        self.btn_undo.clicked.connect(self.undo)
        self.btn_redo = QPushButton(T("Refazer"))
        self.btn_redo.setToolTip(T("Refaz a mudança desfeita (Ctrl+Y)"))
        self.btn_redo.clicked.connect(self.redo)
        self.btn_compare = QPushButton(T("Comparar"))
        self.btn_compare.setCheckable(True)
        self.btn_compare.setToolTip(T("Divide a prévia: original à esquerda, resultado à direita. Arraste a "
                                      "divisória."))
        self.btn_compare.toggled.connect(self._on_compare)
        self.btn_before = QPushButton(T("Antes"))
        self.btn_before.setToolTip(T("Segure para ver o vídeo original; solte para voltar ao resultado."))
        self.btn_before.pressed.connect(lambda: self._show_before(True))
        self.btn_before.released.connect(lambda: self._show_before(False))
        for b in (self.btn_undo, self.btn_redo, self.btn_compare, self.btn_before):
            top.addWidget(b)
        self._update_undo_buttons()

    def _on_compare(self, on):
        self.preview.set_compare(on)
        self._feed_before()

    def _show_before(self, on):
        self.preview.set_show_before(on)
        self._feed_before()

    def _feed_before(self):
        if self.frame is not None and (self.preview.compare or self.preview.show_before):
            self.preview.set_before(bgr_to_qimage(self.frame))

    # =============================================================== IA
    def _build_ai_section(self):
        sec = Section(T("Remoção por IA (beta)"))
        self.cmb_source = QComboBox()
        self.cmb_source.addItem(T("Cor-chave (tela verde/azul)"), "chroma")
        self.cmb_source.addItem(T("IA — sem tela verde"), "ai")
        self.cmb_source.activated.connect(self._on_source)
        sec.add_row(T("Origem do recorte"), self.cmb_source,
                    T("IA: separa a pessoa/objeto do fundo sem precisar de tela verde. O refinamento de borda, "
                      "a limpeza, o retoque e o restante dos ajustes continuam valendo."))
        self.cmb_ai_model = QComboBox()
        for k, m in ai.MODELS.items():
            self.cmb_ai_model.addItem(T(m["label"]), k)
        self.cmb_ai_model.activated.connect(self._on_ai_model)
        sec.add_row(T("Modelo"), self.cmb_ai_model,
                    T("Pessoas: retratos e corpo inteiro (melhor para vídeos de gente). Objetos: qualquer objeto "
                      "em destaque."))
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        self.btn_ai_dl = QPushButton(T("Baixar modelo"))
        self.btn_ai_dl.clicked.connect(lambda: self.download_model(self.cmb_ai_model.currentData()))
        self.btn_ai_cancel = QPushButton(T("Cancelar"))
        self.btn_ai_cancel.setVisible(False)
        self.btn_ai_cancel.clicked.connect(self.cancel_download)
        self.pb_ai = QProgressBar()
        self.pb_ai.setVisible(False)
        self.pb_ai.setFormat("%p%")
        rl.addWidget(self.btn_ai_dl)
        rl.addWidget(self.pb_ai, 1)
        rl.addWidget(self.btn_ai_cancel)
        sec.add_row("", row)
        self.lbl_ai = QLabel("")
        self.lbl_ai.setObjectName("muted")
        self.lbl_ai.setWordWrap(True)
        sec.add_row("", self.lbl_ai)
        self._update_ai_status()
        return sec

    def _update_ai_status(self, msg=None):
        name = self.cmb_ai_model.currentData()
        ready = ai.is_ready(name)
        downloading = self.dl_thread is not None and self.dl_thread.isRunning()
        self.btn_ai_dl.setVisible(not ready and not downloading)
        if msg is not None:
            self.lbl_ai.setText(msg)
        elif not ai.runtime_available():
            self.lbl_ai.setText(T("onnxruntime não está disponível nesta instalação."))
        elif ready:
            self.lbl_ai.setText(T("Modelo pronto (funciona offline). Pasta: {p}").format(p=ai.models_dir()))
        elif not downloading:
            mb = ai.MODELS[name]["size"] / 1e6
            self.lbl_ai.setText(T("O modelo ({mb} MB) é baixado uma vez, no primeiro uso, para {p}.").format(
                mb=f"{mb:.1f}", p=ai.models_dir()))

    def _on_source(self, *_):
        src = self.cmb_source.currentData()
        if src == "ai" and not ai.is_ready(self.cmb_ai_model.currentData()):
            self._set_source_combo(self.matte_source)
            self.download_model(self.cmb_ai_model.currentData(), activate=True)
            return
        self.matte_source = src
        self.schedule_render()

    def _set_source_combo(self, src):
        self.cmb_source.blockSignals(True)
        self.cmb_source.setCurrentIndex(max(0, self.cmb_source.findData(src)))
        self.cmb_source.blockSignals(False)

    def _on_ai_model(self, *_):
        name = self.cmb_ai_model.currentData()
        if self.matte_source == "ai" and not ai.is_ready(name):
            self.download_model(name, activate=True)
            return
        self.ai_model = name
        self._update_ai_status()
        self.schedule_render()

    def download_model(self, name, activate=False):
        if self.dl_thread is not None and self.dl_thread.isRunning():
            return
        if not ai.runtime_available():
            self._ai_error(T("onnxruntime não está disponível nesta instalação."))
            return
        if ai.is_ready(name):
            self._on_model_ready(name, "", activate)
            return
        _retire(self.dl_thread, self.dl_worker)
        self.dl_thread = QThread()
        self.dl_worker = ModelDownloadWorker(name)
        self.dl_worker.moveToThread(self.dl_thread)
        self.dl_thread.started.connect(self.dl_worker.run)
        self.dl_worker.progress.connect(self._on_dl_progress)
        self._dl_activate = activate
        self.dl_worker.finished.connect(self._on_dl_finished)     # método (não lambda): roda na thread da interface
        self.dl_worker.finished.connect(self.dl_thread.quit)
        self.pb_ai.setRange(0, 0)
        self.pb_ai.setVisible(True)
        self.btn_ai_cancel.setVisible(True)
        self.btn_ai_dl.setVisible(False)
        self.lbl_ai.setText(T("Baixando o modelo de IA…"))
        self.statusBar().showMessage(T("Baixando o modelo de IA…"))
        self.dl_thread.start()

    def is_downloading(self):
        return self.dl_thread is not None and self.dl_thread.isRunning()

    def _on_dl_progress(self, got, total):
        if total > 0:
            self.pb_ai.setRange(0, 1000)
            self.pb_ai.setValue(int(1000 * got / total))
        self.lbl_ai.setText(T("Baixando o modelo de IA: {a} de {b} MB").format(a=f"{got / 1e6:.1f}",
                                                                              b=f"{total / 1e6:.1f}"))

    def _on_dl_finished(self, name, err):
        self._on_model_ready(name, err, getattr(self, "_dl_activate", False))

    def cancel_download(self):
        if self.dl_worker:
            self.dl_worker.cancel()

    def _on_model_ready(self, name, err, activate):
        self.pb_ai.setVisible(False)
        self.btn_ai_cancel.setVisible(False)
        self.last_model_download = (name, err)
        if err:
            cancelled = self.dl_worker is not None and self.dl_worker._cancel
            if cancelled:
                self._update_ai_status(T("Download cancelado."))
                self.btn_ai_dl.setVisible(True)
                return
            self._ai_error(T("Não foi possível baixar o modelo de IA:") + f"\n{err}\n\n" +
                           T("Verifique a conexão e tente de novo. Enquanto isso, a cor-chave continua funcionando."))
            return
        self.ai_model = name
        self.cmb_ai_model.setCurrentIndex(max(0, self.cmb_ai_model.findData(name)))
        if activate:
            self.matte_source = "ai"
            self._set_source_combo("ai")
        self._update_ai_status()
        self.statusBar().showMessage(T("Modelo de IA pronto."))
        self.schedule_render()

    def _ai_error(self, msg):
        self._set_source_combo(self.matte_source)
        self._update_ai_status(msg.split("\n")[0] + " " + (msg.split("\n")[1] if "\n" in msg else ""))
        self.btn_ai_dl.setVisible(ai.runtime_available())
        self.statusBar().showMessage(msg.replace("\n", " "))
        if not getattr(self.ctrl, "quiet", False):
            QMessageBox.warning(self, T("Remoção por IA"), msg)

    # =============================================================== retoque (pincel)
    def _build_retouch_section(self):
        sec = Section(T("Retoque com pincel (beta)"))
        self.btn_brush = QPushButton(T("Pincel"))
        self.btn_brush.setCheckable(True)
        self.btn_brush.setEnabled(False)
        self.btn_brush.toggled.connect(self.toggle_brush)
        sec.add_row("", self.btn_brush, T("Pinte na prévia as áreas que devem ficar (Manter) ou sumir (Remover). "
                                          "Atalhos: B liga/desliga, [ e ] mudam o tamanho."))
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        self._brush_group = QButtonGroup(self)
        self._brush_btns = {}
        for i, (k, label) in enumerate(BRUSH_MODES):
            b = QPushButton(T(label))
            b.setCheckable(True)
            b.setChecked(i == 0)
            self._brush_group.addButton(b, i)
            self._brush_btns[k] = b
            rl.addWidget(b)
        self._brush_group.idToggled.connect(lambda *_: self._update_brush_cursor())
        sec.add_row(T("Modo"), row, T("Manter: força opaco. Remover: força transparente. Borracha: desfaz o "
                                      "retoque pintado."))
        self.sl_brush_size = ParamSlider(1, 400, self.ctrl.settings.get("brush_size"))
        self.sl_brush_size.valueChanged.connect(self._on_brush_size)
        sec.add_row(T("Tamanho"), self.sl_brush_size, T("Raio do pincel em pixels do vídeo original."))
        self.sl_brush_hard = ParamSlider(0, 100, self.ctrl.settings.get("brush_hardness"))
        self.sl_brush_hard.valueChanged.connect(
            lambda v: self.ctrl.settings.set("brush_hardness", int(v)))
        sec.add_row(T("Dureza"), self.sl_brush_hard, T("100 = borda dura; 0 = borda bem suave."))
        self.chk_brush_frame = QCheckBox(T("Só neste quadro"))
        sec.add_row("", self.chk_brush_frame, T("Desmarcado: o retoque vale para todos os quadros (máscara fixa). "
                                                "Marcado: só para o quadro mostrado."))
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        self.btn_rt_clear_frame = QPushButton(T("Limpar quadro"))
        self.btn_rt_clear_frame.clicked.connect(lambda: self.clear_retouch(frame_only=True))
        self.btn_rt_clear = QPushButton(T("Limpar tudo"))
        self.btn_rt_clear.clicked.connect(lambda: self.clear_retouch(frame_only=False))
        rl.addWidget(self.btn_rt_clear_frame)
        rl.addWidget(self.btn_rt_clear)
        sec.add_row("", row)
        self.lbl_rt = QLabel("")
        self.lbl_rt.setObjectName("muted")
        self.lbl_rt.setWordWrap(True)
        sec.add_row("", self.lbl_rt)
        self.preview.brushStroke.connect(self._on_brush)
        self._update_brush_cursor()
        return sec

    def brush_mode_key(self):
        return BRUSH_MODES[max(0, self._brush_group.checkedId())][0]

    def set_brush_mode_key(self, k):
        self._brush_btns[k].setChecked(True)

    def _on_brush_size(self, v):
        self.ctrl.settings.set("brush_size", int(v))
        self.preview.brush_radius = float(v)
        self.preview.update()

    def _update_brush_cursor(self):
        self.preview.brush_radius = float(self.sl_brush_size.value())
        self.preview.brush_color = {"keep": QColor(57, 211, 83), "remove": QColor(255, 80, 80),
                                    "erase": QColor(230, 230, 230)}[self.brush_mode_key()]
        self.preview.update()

    def toggle_brush(self, on):
        if on:
            if self.btn_pick.isChecked():
                self.btn_pick.setChecked(False)
            if self.btn_crop.isChecked():
                self.btn_crop.setChecked(False)
            self.statusBar().showMessage(T("Pincel: pinte na prévia. Verde = manter, vermelho = remover."))
        self.preview.set_brush_mode(on)

    def _brush_frame(self):
        return self.slider.value() if self.chk_brush_frame.isChecked() else None

    def _on_brush(self, phase, x, y):
        rt = self.retouch
        if rt is None:
            return
        if phase == "begin":
            self.flush_undo()
            fr = self._brush_frame()
            rt.begin_stroke(fr)
            self._stroke = {"frame": fr, "box": None, "before": rt.get_patch(fr, (0, 0, rt.w, rt.h)),
                            "last": None}
        st = self._stroke
        if st is None:
            return
        r = float(self.sl_brush_size.value())
        pts = [(x, y)]
        if st["last"] is not None:             # preenche o caminho entre eventos do mouse
            lx, ly = st["last"]
            d = ((x - lx) ** 2 + (y - ly) ** 2) ** 0.5
            n = int(d / max(1.0, r * 0.35))
            pts = [(lx + (x - lx) * k / (n + 1), ly + (y - ly) * k / (n + 1)) for k in range(1, n + 1)] + pts
        for px, py in pts:
            box = rt.dab(px, py, r, self.sl_brush_hard.value() / 100.0, self.brush_mode_key(), st["frame"],
                         strength=0.6 if self.sl_brush_hard.value() < 50 else 1.0)
            if box:
                b = st["box"]
                st["box"] = box if b is None else (min(b[0], box[0]), min(b[1], box[1]),
                                                   max(b[2], box[2]), max(b[3], box[3]))
        st["last"] = (x, y)
        self.schedule_render()
        if phase == "end":
            self._stroke = None
            if st["box"] is not None:
                x0, y0, x1, y1 = st["box"]
                before = st["before"][y0:y1, x0:x1].copy()
                after = rt.get_patch(st["frame"], st["box"])
                self._push_undo(("brush", st["frame"], st["box"], before, after))
            self._update_retouch_info()
            self._invalidate_track()

    def clear_retouch(self, frame_only=False):
        rt = self.retouch
        if rt is None:
            return
        self.flush_undo()
        frames = [self.slider.value()] if frame_only else [None] + sorted(rt.frames)
        for fr in frames:
            if rt.layer(fr) is None:
                continue
            box = (0, 0, rt.w, rt.h)
            before = rt.get_patch(fr, box)
            if not before.any():
                continue
            rt.set_patch(fr, box, 0)
            self._push_undo(("brush", fr, box, before, rt.get_patch(fr, box)))
        self._update_retouch_info()
        self.schedule_render()

    def _update_retouch_info(self):
        rt = self.retouch
        if rt is None or rt.is_empty():
            self.lbl_rt.setText(T("Nenhum retoque pintado."))
            return
        st = rt.static is not None and rt.static.any()
        n = rt.frame_count()
        parts = []
        if st:
            parts.append(T("máscara fixa (todos os quadros)"))
        if n:
            parts.append(T("{n} quadro(s) com retoque próprio").format(n=n))
        self.lbl_rt.setText(T("Retoque: {what}.").format(what=", ".join(parts)))

    def _reset_retouch_for_video(self):
        v = self.video
        self.retouch = Retouch(v.width, v.height) if v else None
        self.btn_brush.setEnabled(v is not None)
        self._update_retouch_info()

    # =============================================================== sombra / brilho
    def _build_glow_section(self):
        sec = Section(T("Sombra e brilho (beta)"))
        self.chk_glow = QCheckBox(T("Ativar sombra/brilho atrás do objeto"))
        self.chk_glow.toggled.connect(self._on_glow)
        sec.add_row("", self.chk_glow, T("Aparece na prévia (sobre o fundo de teste) e, se marcado abaixo, no "
                                         "arquivo exportado."))
        self.cmb_glow_mode = QComboBox()
        self.cmb_glow_mode.addItem(T("Sombra projetada"), "shadow")
        self.cmb_glow_mode.addItem(T("Brilho neon"), "neon")
        self.cmb_glow_mode.activated.connect(self._on_glow_mode)
        sec.add_row(T("Tipo"), self.cmb_glow_mode, T("Escolher o tipo aplica valores sugeridos (dá para ajustar "
                                                     "depois)."))
        self.btn_glow_color = QPushButton()
        self.btn_glow_color.setFixedWidth(70)
        self.btn_glow_color.clicked.connect(self._choose_glow_color)
        sec.add_row(T("Cor"), self.btn_glow_color)
        self.glow_sliders = {}
        for k, label, lo, hi in GLOW_KEYS:
            s = ParamSlider(lo, hi, core.GLOW_DEFAULTS[k])
            s.valueChanged.connect(self._on_glow)
            self.glow_sliders[k] = s
            sec.add_row(T(label), s, T("Em pixels do vídeo original.") if k != "opacity" else "")
        self.chk_glow_export = QCheckBox(T("Incluir na exportação"))
        self.chk_glow_export.setChecked(True)
        self.chk_glow_export.toggled.connect(self._on_glow)
        sec.add_row("", self.chk_glow_export, T("Desmarcado: o efeito aparece só na prévia."))
        self._sync_glow_widgets()
        return sec

    def _on_glow(self, *_):
        if getattr(self, "_glow_syncing", False):
            return
        g = self.glow
        g["on"] = self.chk_glow.isChecked()
        g["export"] = self.chk_glow_export.isChecked()
        g["mode"] = self.cmb_glow_mode.currentData()
        for k, s in self.glow_sliders.items():
            g[k] = s.value()
        self.schedule_render()

    def _on_glow_mode(self, *_):
        mode = self.cmb_glow_mode.currentData()
        self.glow.update(copy.deepcopy(core.GLOW_PRESETS[mode]), mode=mode, on=True)
        self._sync_glow_widgets()
        self.schedule_render()

    def _choose_glow_color(self):
        c = QColorDialog.getColor(QColor(*self.glow["color"]), self, T("Cor da sombra/brilho"))
        if c.isValid():
            self.glow["color"] = [c.red(), c.green(), c.blue()]
            self._sync_glow_widgets()
            self.schedule_render()

    def _sync_glow_widgets(self):
        self._glow_syncing = True
        try:
            g = self.glow
            self.chk_glow.setChecked(bool(g.get("on")))
            self.chk_glow_export.setChecked(bool(g.get("export", True)))
            self.cmb_glow_mode.setCurrentIndex(max(0, self.cmb_glow_mode.findData(g.get("mode", "shadow"))))
            for k, s in self.glow_sliders.items():
                s.setValue(int(g.get(k, core.GLOW_DEFAULTS[k])))
            r, gg, b = g.get("color", [0, 0, 0])
            self.btn_glow_color.setStyleSheet(f"background: rgb({r},{gg},{b}); border:1px solid #777; "
                                              "border-radius:6px;")
            self.btn_glow_color.setToolTip(f"#{r:02X}{gg:02X}{b:02X}")
        finally:
            self._glow_syncing = False

    # =============================================================== recorte que se move
    def _build_motion_rows(self, sec):
        self.cmb_motion = QComboBox()
        for k, label in MOTIONS:
            self.cmb_motion.addItem(T(label), k)
        self.cmb_motion.setEnabled(False)
        self.cmb_motion.activated.connect(self._on_motion)
        sec.add_row(T("Movimento"), self.cmb_motion,
                    T("Fixo: a mesma área em todos os quadros. Seguir o objeto: a área acompanha o objeto (tamanho "
                      "fixo = o maior necessário). Quadros-chave: você posiciona a área em alguns quadros e ela "
                      "é interpolada entre eles."))
        self.motion_row = QWidget()
        rl = QHBoxLayout(self.motion_row)
        rl.setContentsMargins(0, 0, 0, 0)
        self.sp_track_smooth = QSpinBox()
        self.sp_track_smooth.setRange(1, 99)
        self.sp_track_smooth.setValue(9)
        self.sp_track_smooth.setSuffix(" " + T("quadros"))
        self.sp_track_smooth.setToolTip(T("Suavização do movimento: valores maiores deixam a câmera mais estável."))
        self.sp_track_smooth.valueChanged.connect(self._invalidate_track)
        self.btn_track = QPushButton(T("Analisar movimento"))
        self.btn_track.setToolTip(T("Calcula o caminho do recorte para ver na prévia (a exportação calcula sozinha)."))
        self.btn_track.clicked.connect(lambda: self.analyze_motion())
        rl.addWidget(QLabel(T("Suavização")))
        rl.addWidget(self.sp_track_smooth)
        rl.addWidget(self.btn_track, 1)
        sec.add_row("", self.motion_row)
        self.keys_row = QWidget()
        rl = QHBoxLayout(self.keys_row)
        rl.setContentsMargins(0, 0, 0, 0)
        self.btn_key_add = QPushButton(T("Marcar quadro-chave"))
        self.btn_key_add.setToolTip(T("Guarda a área atual neste quadro. Mover/redimensionar a área num quadro "
                                      "também marca um quadro-chave."))
        self.btn_key_add.clicked.connect(lambda: self.add_crop_key())
        self.btn_key_del = QPushButton(T("Remover"))
        self.btn_key_del.setToolTip(T("Remove o quadro-chave do quadro atual."))
        self.btn_key_del.clicked.connect(lambda: self.remove_crop_key())
        self.btn_key_clear = QPushButton(T("Limpar"))
        self.btn_key_clear.clicked.connect(lambda: self.clear_crop_keys())
        rl.addWidget(self.btn_key_add, 1)
        rl.addWidget(self.btn_key_del)
        rl.addWidget(self.btn_key_clear)
        sec.add_row("", self.keys_row)
        self.lbl_motion = QLabel("")
        self.lbl_motion.setObjectName("muted")
        self.lbl_motion.setWordWrap(True)
        sec.add_row("", self.lbl_motion)
        self._update_motion_ui()

    def crop_motion(self):
        return self.cmb_motion.currentData()

    def _on_motion(self, *_):
        m = self.crop_motion()
        if m == "follow" and self.btn_crop.isChecked():
            self.btn_crop.setChecked(False)
        if m == "keys" and not self.crop_keys and self.video and self.crop_rect:
            self.crop_keys[self.slider.value()] = tuple(self.crop_rect)
        self._update_motion_ui()
        self._show_motion_crop(self.slider.value())
        self._note_change()
        self._update_export_info()

    def _set_motion_combo(self, m):
        self.cmb_motion.blockSignals(True)
        self.cmb_motion.setCurrentIndex(max(0, self.cmb_motion.findData(m)))
        self.cmb_motion.blockSignals(False)
        self._update_motion_ui()

    def _update_motion_ui(self):
        m = self.crop_motion()
        self.motion_row.setVisible(m == "follow")
        self.keys_row.setVisible(m == "keys")
        follow = m == "follow"
        has_video = self.video is not None
        for w in (self.btn_crop, self.btn_crop_auto, self.sp_cx, self.sp_cy, self.sp_cw, self.sp_ch):
            w.setEnabled(has_video and not follow)
        if m == "follow":
            if self.track_path and self._track_sig == self._track_signature():
                w, h = next(iter(self.track_path.values()))[2:]
                self.lbl_motion.setText(T("Caminho analisado: área de {w}×{h} px seguindo o objeto.").format(w=w, h=h))
            else:
                self.lbl_motion.setText(T("A área acompanha o objeto. Clique em 'Analisar movimento' para ver na "
                                          "prévia; a exportação calcula o caminho automaticamente."))
        elif m == "keys":
            n = len(self.crop_keys)
            ks = ", ".join(str(k + 1) for k in sorted(self.crop_keys)[:12]) + ("…" if n > 12 else "")
            self.lbl_motion.setText(T("{n} quadro(s)-chave: {list}").format(n=n, list=ks or "—"))
        else:
            self.lbl_motion.setText("")

    def _track_signature(self):
        o = self.export_options()
        return json.dumps([self.path, self.params().to_dict(), o.start, o.end, o.step, o.even, o.fmt,
                           self.sp_crop_margin.value(), self.sp_track_smooth.value(),
                           None if self.retouch is None else self.retouch.version])

    def _invalidate_track(self, *_):
        if self.track_path is not None and self._track_sig != self._track_signature():
            self._update_motion_ui()
            self._update_export_info()

    def analyze_motion(self):
        if not self.path or (self.track_thread is not None and self.track_thread.isRunning()):
            return
        opts = self.export_options()
        opts.crop_motion = "follow"
        _retire(self.track_thread, self.track_worker)
        self.track_thread = QThread()
        p = copy.deepcopy(self.params())
        if p.retouch is not None:
            p.retouch = p.retouch.frozen()
        self.track_worker = TrackWorker(self.path, p, opts)
        self.track_worker.moveToThread(self.track_thread)
        self.track_thread.started.connect(self.track_worker.run)
        self.track_worker.progress.connect(self._on_track_progress)
        self.track_worker.finished.connect(self._on_track)
        self.track_worker.finished.connect(self.track_thread.quit)
        self._track_pending_sig = self._track_signature()
        self.btn_track.setEnabled(False)
        self.btn_track.setText(T("Analisando…"))
        self.track_thread.start()

    def _on_track_progress(self, c, t):
        self.statusBar().showMessage(T("Analisando movimento: quadro {i} de {n}…").format(i=c, n=t))

    def is_tracking(self):
        return self.track_thread is not None and self.track_thread.isRunning()

    def _on_track(self, path, err):
        self.btn_track.setEnabled(True)
        self.btn_track.setText(T("Analisar movimento"))
        if err:
            self.statusBar().showMessage(T("Erro") + ": " + err)
            return
        if not path:
            self.statusBar().showMessage(T("Nenhum objeto encontrado para o recorte automático."))
            return
        self.track_path = path
        self._track_sig = self._track_pending_sig
        self._update_motion_ui()
        self._show_motion_crop(self.slider.value())
        self._update_export_info()
        self.statusBar().showMessage(T("Movimento analisado."))

    def _show_motion_crop(self, idx):
        """Mostra na prévia a área do quadro `idx` nos modos que se movem (sem marcar quadro-chave)."""
        if not self.video:
            return
        m = self.crop_motion()
        W, H = self.video.width, self.video.height
        r = None
        if m == "follow" and self.track_path:
            ks = sorted(self.track_path)
            k = min(ks, key=lambda q: abs(q - idx))
            r = self.track_path[k]
        elif m == "keys" and self.crop_keys:
            r = core.keyframe_rect(self.crop_keys, idx, W, H)
        if r is not None and tuple(r) != tuple(self.crop_rect or ()):
            self.crop_rect = tuple(r)
            self.preview.set_crop(r)
            self._sync_crop_spins()
            self._update_crop_info()

    def _crop_edited(self, rect):
        """Chamado quando o usuário muda o recorte (prévia/campos): no modo quadros-chave marca o quadro."""
        if self.crop_motion() == "keys" and self.video:
            self.crop_keys[self.slider.value()] = tuple(rect)
            self._update_motion_ui()

    def add_crop_key(self):
        if self.video and self.crop_rect:
            self.crop_keys[self.slider.value()] = tuple(self.crop_rect)
            self._update_motion_ui()
            self._note_change()
            self._update_export_info()

    def remove_crop_key(self):
        if self.crop_keys.pop(self.slider.value(), None) is not None:
            self._update_motion_ui()
            self._show_motion_crop(self.slider.value())
            self._note_change()
            self._update_export_info()

    def clear_crop_keys(self):
        if self.crop_keys:
            self.crop_keys = {}
            self._update_motion_ui()
            self._note_change()
            self._update_export_info()

    # =============================================================== sprite sheet
    def _build_sheet_rows(self, sec):
        self.sp_sheet_cols = QSpinBox()
        self.sp_sheet_cols.setRange(0, 1000)
        self.sp_sheet_cols.setSpecialValueText(T("Automático"))
        self._opt(sec, "sheet", T("Colunas"), self.sp_sheet_cols, T("Automático = grade o mais quadrada possível."))
        self.sp_sheet_pad = QSpinBox()
        self.sp_sheet_pad.setRange(0, 64)
        self.sp_sheet_pad.setValue(2)
        self.sp_sheet_pad.setSuffix(" px")
        self._opt(sec, "sheet", T("Espaçamento"), self.sp_sheet_pad, T("Espaço vazio entre os quadros na folha."))
        self.cmb_sheet_max = QComboBox()
        for v in SHEET_MAX:
            self.cmb_sheet_max.addItem(f"{v} px", v)
        self.cmb_sheet_max.setCurrentIndex(SHEET_MAX.index(4096))
        self._opt(sec, "sheet", T("Tamanho máximo"), self.cmb_sheet_max,
                  T("Se a folha passar disso, são geradas várias folhas (nome_0.png, nome_1.png…)."))
        self.chk_sheet_trim = QCheckBox(T("Recortar transparência (trim)"))
        self.chk_sheet_trim.setChecked(True)
        self._opt(sec, "sheet", "", self.chk_sheet_trim, T("Remove as bordas transparentes de cada quadro; o JSON "
                                                           "guarda o deslocamento (spriteSourceSize)."))
        self.cmb_sheet_json = QComboBox()
        self.cmb_sheet_json.addItem(T("Hash (Phaser, Pixi, Godot)"), "hash")
        self.cmb_sheet_json.addItem(T("Array (Phaser, Unity)"), "array")
        self._opt(sec, "sheet", T("JSON"), self.cmb_sheet_json, T("Formato JSON do TexturePacker."))
        for w in (self.sp_sheet_cols, self.sp_sheet_pad):
            w.valueChanged.connect(self._update_export_info)
        for w in (self.cmb_sheet_max, self.cmb_sheet_json):
            w.currentIndexChanged.connect(self._update_export_info)
        self.chk_sheet_trim.toggled.connect(self._update_export_info)

    def sheet_options(self):
        return dict(sheet_cols=self.sp_sheet_cols.value(), sheet_pad=self.sp_sheet_pad.value(),
                    sheet_max=int(self.cmb_sheet_max.currentData()), sheet_trim=self.chk_sheet_trim.isChecked(),
                    sheet_json=self.cmb_sheet_json.currentData())

    # =============================================================== exportação em lote
    def open_batch(self):
        from .batch import BatchDialog
        if self.batch_dialog is None:
            self.batch_dialog = BatchDialog(self)
        self.batch_dialog.show()
        self.batch_dialog.raise_()
        return self.batch_dialog

    # =============================================================== desfazer / refazer
    def ui_state(self):
        return {"key_rgb": list(self.key_rgb), "enabled": self.chk_enable.isChecked(),
                "values": {k: s.value() for k, s in self.sliders.items()},
                "source": self.matte_source, "ai_model": self.ai_model, "glow": copy.deepcopy(self.glow),
                # nos modos que se movem a área mostrada muda com o quadro: não é um passo de desfazer
                "crop": list(self.crop_rect) if self.crop_rect and self.crop_motion() == "fixed" else None,
                "motion": self.crop_motion(), "keys": {int(k): list(v) for k, v in self.crop_keys.items()}}

    def apply_ui_state(self, st):
        self._restoring = True
        try:
            p = core.KeyParams(tuple(st["key_rgb"]), dict(st["values"]), st["enabled"], st["source"],
                               st["ai_model"], copy.deepcopy(st["glow"]), self.retouch)
            self.apply_params(p)
            self.crop_keys = {int(k): tuple(v) for k, v in st["keys"].items()}
            self._set_motion_combo(st["motion"])
            if self.video and st["crop"]:
                self.set_crop(tuple(st["crop"]))
            self._update_motion_ui()
        finally:
            self._restoring = False
        self._committed = self.ui_state()

    def _note_change(self, *_):
        if not self._restoring and self._committed is not None:
            self._undo_timer.start()

    def _commit_state(self):
        if self._committed is None:
            self._committed = self.ui_state()
            return
        cur = self.ui_state()
        if cur != self._committed:
            self._push_undo(("state", self._committed, cur))
            self._committed = cur

    def flush_undo(self):
        if self._undo_timer.isActive():
            self._undo_timer.stop()
            self._commit_state()

    def _push_undo(self, entry):
        self._undo.append(entry)
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()
        self._update_undo_buttons()

    def reset_undo(self):
        self._undo_timer.stop()
        self._undo.clear()
        self._redo.clear()
        self._committed = self.ui_state()
        self._update_undo_buttons()

    def _apply_entry(self, e, forward):
        if e[0] == "state":
            self.apply_ui_state(e[2] if forward else e[1])
        else:
            _, fr, box, before, after = e
            if self.retouch is not None:
                self.retouch.set_patch(fr, box, after if forward else before)
                self._update_retouch_info()
                self.schedule_render()

    def undo(self):
        if self.preview._brushing is not None:
            return
        self.flush_undo()
        if not self._undo:
            self.statusBar().showMessage(T("Nada para desfazer."))
            return
        e = self._undo.pop()
        self._apply_entry(e, False)
        self._redo.append(e)
        self._update_undo_buttons()
        self.statusBar().showMessage(T("Desfeito."))

    def redo(self):
        if self.preview._brushing is not None:
            return
        self.flush_undo()
        if not self._redo:
            self.statusBar().showMessage(T("Nada para refazer."))
            return
        e = self._redo.pop()
        self._apply_entry(e, True)
        self._undo.append(e)
        self._update_undo_buttons()
        self.statusBar().showMessage(T("Refeito."))

    def _update_undo_buttons(self):
        if hasattr(self, "btn_undo"):
            self.btn_undo.setEnabled(bool(self._undo) or self._undo_timer.isActive())
            self.btn_redo.setEnabled(bool(self._redo))

    # =============================================================== atualizações
    def schedule_update_check(self):
        if (getattr(self.ctrl, "quiet", False) or os.environ.get("CHROMAQUI_NO_UPDATE_CHECK")
                or not self.ctrl.settings.get("update_check")):
            return False
        QTimer.singleShot(2500, lambda: self.check_updates(manual=False))
        return True

    def check_updates(self, manual=False, label=None, fetch=None):
        if getattr(self, "_upd_busy", False):
            return
        self._upd_busy = True
        from . import updates
        betas = self.ctrl.settings.get("update_betas")
        if fetch is None and manual:
            def fetch(cur, b):
                return updates.check(cur, b, raise_errors=True)
        _retire(self.upd_thread, self.upd_worker)
        self.upd_thread = QThread()
        self.upd_worker = UpdateWorker(__version__, betas, fetch)
        self.upd_worker.moveToThread(self.upd_thread)
        self.upd_thread.started.connect(self.upd_worker.run)
        self._upd_label = label
        self._upd_manual = manual
        self.upd_worker.finished.connect(self._on_update)
        self.upd_worker.finished.connect(self.upd_thread.quit)
        self.upd_thread.start()

    def _on_update(self, info):
        self._upd_busy = False
        self.last_update_info = info
        label, manual = getattr(self, "_upd_label", None), getattr(self, "_upd_manual", False)
        try:
            if label is not None:
                label.text()
        except RuntimeError:          # diálogo já fechado
            label = None
        if not info:
            if manual and label is not None:
                label.setText(T("Você já tem a versão mais recente ({v}).").format(v=__version__)
                              if self.upd_worker is None or not getattr(self.upd_worker, "error", "")
                              else T("Não foi possível verificar agora."))
            return
        if not manual and info["version"] == self.ctrl.settings.get("update_skip"):
            return
        if label is not None:
            label.setText(T("Nova versão disponível: {v}").format(v=info["version"]))
        if getattr(self.ctrl, "quiet", False):
            return
        kind = T("beta (de testes)") if info.get("prerelease") else T("estável")
        box = QMessageBox(self)
        box.setWindowTitle(T("Atualização disponível"))
        box.setIcon(QMessageBox.Information)
        box.setTextFormat(Qt.RichText)
        box.setText(T("Há uma nova versão do {app}: <b>{v}</b> ({kind}).<br>Você está usando a {cur}.").format(
            app="Chromaqui!", v=info["version"], kind=kind, cur=__version__) +
            f'<br><br><a href="{info["url"]}">{info["url"]}</a>' +
            (f'<br><a href="{info["download"]}">{info["asset"]}</a>' if info.get("download") else ""))
        b_open = box.addButton(T("Abrir página de download"), QMessageBox.AcceptRole)
        b_skip = box.addButton(T("Ignorar esta versão"), QMessageBox.DestructiveRole)
        box.addButton(T("Agora não"), QMessageBox.RejectRole)
        box.setModal(False)

        def done(btn):
            if btn is b_open:
                QDesktopServices.openUrl(QUrl(info["url"]))
            elif btn is b_skip:
                self.ctrl.settings.set("update_skip", info["version"])
        box.buttonClicked.connect(done)
        box.show()
        self.update_box = box

    # =============================================================== encerramento
    def shutdown_extras(self):
        if self.batch_dialog is not None:
            self.batch_dialog.shutdown()
        for th, wk in ((self.dl_thread, self.dl_worker), (self.track_thread, self.track_worker),
                       (self.upd_thread, self.upd_worker)):
            if wk is not None and hasattr(wk, "cancel"):
                wk.cancel()
            _retire(th, wk, wait_ms=5000)


def window_title_suffix():
    return f"  —  v{__version__} ({T('beta')})" if IS_BETA else ""
