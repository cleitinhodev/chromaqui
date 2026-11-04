"""Exportação em lote (beta): uma fila de vídeos exportada com os ajustes atuais ou com um preset."""
from __future__ import annotations

import copy
import dataclasses
import os

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from . import core
from .dialogs import app_icon
from .exporters import FORMAT_BY_KEY, default_output_name, ffmpeg_available
from .i18n import T
from .widgets import BatchWorker


def batch_outputs(paths, out_dir, fmt_key):
    """Saída de cada vídeo: arquivo <nome>_chromaqui.ext (animações/vídeo) ou pasta <nome>/ (sequências).
    Nomes repetidos recebem _2, _3…"""
    f = FORMAT_BY_KEY[fmt_key]
    used, outs = set(), []
    for p in paths:
        name = default_output_name(p, fmt_key) if f.single_file else (
            os.path.splitext(os.path.basename(p))[0] or "video")
        stem, ext = (os.path.splitext(name) if f.single_file else (name, ""))
        cand, k = name, 2
        while cand.lower() in used:
            cand = f"{stem}_{k}{ext}"
            k += 1
        used.add(cand.lower())
        outs.append(os.path.join(out_dir, cand))
    return outs


class BatchDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.win = window
        self.thread = self.worker = None
        self.setWindowTitle(T("Exportação em lote (beta)"))
        self.setWindowIcon(app_icon())
        self.resize(720, 480)
        lay = QVBoxLayout(self)
        info = QLabel(T("Adicione vídeos à fila. Todos são exportados no formato e com as opções escolhidos em "
                        "'Opções de exportação' (vídeo inteiro). Retoque com pincel e quadros-chave não são "
                        "aplicados no lote."))
        info.setWordWrap(True)
        info.setObjectName("muted")
        lay.addWidget(info)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([T("Vídeo"), T("Situação")])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.btn_add = QPushButton(T("Adicionar vídeos…"))
        self.btn_add.clicked.connect(self.choose_videos)
        self.btn_remove = QPushButton(T("Remover"))
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_clear = QPushButton(T("Limpar fila"))
        self.btn_clear.clicked.connect(self.clear)
        for b in (self.btn_add, self.btn_remove, self.btn_clear):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel(T("Ajustes")))
        self.cmb_preset = QComboBox()
        self.cmb_preset.addItem(T("Ajustes atuais"), "")
        self.cmb_preset.addItem(T("Escolher preset (.json)…"), "?")
        self.cmb_preset.activated.connect(self._on_preset)
        row.addWidget(self.cmb_preset, 1)
        lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel(T("Pasta de destino")))
        self.ed_out = QLineEdit(window.ctrl.settings.get("last_dir") or "")
        row.addWidget(self.ed_out, 1)
        b = QPushButton(T("Escolher…"))
        b.clicked.connect(self.choose_out)
        row.addWidget(b)
        lay.addLayout(row)
        self.chk_crop = QCheckBox(T("Usar o recorte salvo para cada tamanho de vídeo"))
        self.chk_crop.setChecked(True)
        self.chk_crop.setToolTip(T("Se você já recortou um vídeo do mesmo tamanho, a mesma área é usada; senão, o "
                                   "quadro inteiro."))
        lay.addWidget(self.chk_crop)
        self.lbl_fmt = QLabel("")
        self.lbl_fmt.setObjectName("muted")
        lay.addWidget(self.lbl_fmt)
        self.pb_item = QProgressBar()
        self.pb_item.setFormat(T("%v / %m quadros"))
        self.pb_all = QProgressBar()
        self.pb_all.setFormat(T("Vídeo %v de %m"))
        lay.addWidget(self.pb_item)
        lay.addWidget(self.pb_all)
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_start = QPushButton(T("Iniciar"))
        self.btn_start.setObjectName("primary")
        self.btn_start.clicked.connect(lambda: self.start())
        self.btn_cancel = QPushButton(T("Cancelar"))
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel)
        self.btn_close = QPushButton(T("Fechar"))
        self.btn_close.clicked.connect(self.close)
        for b in (self.btn_start, self.btn_cancel, self.btn_close):
            row.addWidget(b)
        lay.addLayout(row)
        self.paths: list[str] = []
        self.results: list = []
        self.setAcceptDrops(True)
        self._refresh()

    # ----------------------------------------------------------- fila
    def add_videos(self, paths):
        for p in paths:
            p = os.fspath(p)
            if os.path.isfile(p) and p not in self.paths:
                self.paths.append(p)
                r = self.table.rowCount()
                self.table.insertRow(r)
                it = QTableWidgetItem(os.path.basename(p))
                it.setToolTip(p)
                self.table.setItem(r, 0, it)
                self.table.setItem(r, 1, QTableWidgetItem(T("Na fila")))
        self._refresh()

    def choose_videos(self):
        exts = " ".join(f"*{e}" for e in core.VIDEO_EXTS)
        paths, _ = QFileDialog.getOpenFileNames(self, T("Adicionar vídeos"), self.win.ctrl.settings.get("last_dir"),
                                                f"{T('Vídeos')} ({exts});;{T('Todos')} (*.*)")
        self.add_videos(paths)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_videos([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    def remove_selected(self):
        if self.running():
            return
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)
            del self.paths[r]
        self._refresh()

    def clear(self):
        if self.running():
            return
        self.table.setRowCount(0)
        self.paths = []
        self._refresh()

    def choose_out(self):
        d = QFileDialog.getExistingDirectory(self, T("Escolha a pasta de destino"), self.ed_out.text())
        if d:
            self.ed_out.setText(d)

    def _on_preset(self, i):
        if self.cmb_preset.itemData(i) != "?":
            return
        path, _ = QFileDialog.getOpenFileName(self, T("Carregar preset"), "", "Preset (*.json)")
        self.set_preset(path) if path else self.cmb_preset.setCurrentIndex(0)

    def set_preset(self, path):
        try:
            core.load_preset(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, T("Erro"), T("Preset inválido:") + f"\n{e}")
            self.cmb_preset.setCurrentIndex(0)
            return False
        k = self.cmb_preset.findData(path)
        if k < 0:
            self.cmb_preset.insertItem(1, os.path.basename(path), path)
            k = 1
        self.cmb_preset.setCurrentIndex(k)
        return True

    def _refresh(self):
        o = self.win.export_options()
        f = FORMAT_BY_KEY[o.fmt]
        self.lbl_fmt.setText(T("Formato: {fmt}").format(fmt=T(f.label)))
        run = self.running()
        self.btn_start.setEnabled(bool(self.paths) and not run)
        for b in (self.btn_add, self.btn_remove, self.btn_clear, self.cmb_preset, self.ed_out, self.chk_crop):
            b.setEnabled(not run)
        self.btn_cancel.setEnabled(run)

    def showEvent(self, e):
        self._refresh()
        super().showEvent(e)

    # ----------------------------------------------------------- execução
    def running(self):
        return self.thread is not None and self.thread.isRunning()

    def build_jobs(self):
        out_dir = self.ed_out.text().strip()
        base = self.win.export_options()
        src = self.cmb_preset.currentData()
        if src:
            params = core.load_preset(src)
        else:
            params = copy.deepcopy(self.win.params())
        params.retouch = None                    # o retoque é de um vídeo específico
        if params.source == "ai":
            from . import ai
            if not ai.is_ready(params.ai_model):
                params.source = "chroma"
        motion = "follow" if base.crop_motion == "follow" else "fixed"
        jobs = []
        for p, out in zip(self.paths, batch_outputs(self.paths, out_dir, base.fmt)):
            crop = None
            if self.chk_crop.isChecked() and motion == "fixed":
                try:
                    v = core.Video(p)
                    crop = self.win._saved_crop(v.width, v.height)
                    v.release()
                except Exception:  # noqa: BLE001
                    crop = None
            opts = dataclasses.replace(base, start=0, end=-1, crop=crop, crop_motion=motion, crop_keys={},
                                       include_bg=False)
            jobs.append((p, out, copy.deepcopy(params), opts))
        return jobs

    def start(self):
        if self.running() or not self.paths:
            return False
        out_dir = self.ed_out.text().strip()
        if not out_dir:
            self.choose_out()
            out_dir = self.ed_out.text().strip()
            if not out_dir:
                return False
        os.makedirs(out_dir, exist_ok=True)
        f = FORMAT_BY_KEY[self.win.export_options().fmt]
        if f.needs_ffmpeg and not ffmpeg_available():
            QMessageBox.critical(self, T("Erro na exportação"), T("ffmpeg não encontrado"))
            return False
        jobs = self.build_jobs()
        self.results = [None] * len(jobs)
        for r in range(self.table.rowCount()):
            self.table.item(r, 1).setText(T("Na fila"))
        self.pb_all.setRange(0, len(jobs))
        self.pb_all.setValue(0)
        self.pb_item.setValue(0)
        from .app import retire_thread
        retire_thread(self.thread, self.worker)
        self.thread = QThread()
        self.worker = BatchWorker(jobs)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.item_started.connect(self._on_item_started)
        self.worker.progress.connect(self._on_progress)
        self.worker.item_done.connect(self._on_item_done)
        self.worker.finished.connect(self._on_finished)
        self.worker.finished.connect(self.thread.quit)
        self.thread.start()
        self._refresh()
        return True

    def cancel(self):
        if self.worker:
            self.worker.cancel()
            self.btn_cancel.setEnabled(False)

    def _on_item_started(self, i):
        self.table.item(i, 1).setText(T("Exportando…"))
        self.table.scrollToItem(self.table.item(i, 0))
        self.pb_all.setValue(i)
        self.pb_item.setValue(0)

    def _on_progress(self, i, c, t):
        if self.pb_item.maximum() != t:
            self.pb_item.setMaximum(max(1, t))
        self.pb_item.setValue(c)

    def _on_item_done(self, i, n, err, out):
        self.results[i] = (n, err, out)
        it = self.table.item(i, 1)
        if err:
            it.setText(T("Erro") + ": " + err)
            it.setToolTip(err)
        else:
            it.setText(T("{n} quadros").format(n=n))
            it.setToolTip(out)
        self.pb_all.setValue(i + 1)

    def _on_finished(self, cancelled):
        self.last_result = (cancelled, list(self.results))
        if cancelled:
            for r, res in enumerate(self.results):
                if res is None:
                    self.table.item(r, 1).setText(T("Cancelado"))
        ok = sum(1 for r in self.results if r and not r[1])
        msg = T("Lote concluído: {ok} de {n} vídeos exportados.").format(ok=ok, n=len(self.results))
        if cancelled:
            msg = T("Lote cancelado: {ok} de {n} vídeos exportados.").format(ok=ok, n=len(self.results))
        self.win.statusBar().showMessage(msg)
        self._refresh()

    def closeEvent(self, e):
        if self.running():
            if getattr(self.win.ctrl, "quiet", False) or QMessageBox.question(
                    self, T("Exportação em lote"), T("Cancelar a exportação em lote?")) == QMessageBox.Yes:
                self.cancel()
            else:
                e.ignore()
                return
        super().closeEvent(e)

    def shutdown(self):
        from .app import retire_thread
        if self.worker:
            self.worker.cancel()
        retire_thread(self.thread, self.worker, wait_ms=10000)
