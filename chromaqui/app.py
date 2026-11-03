"""Chromaqui! — importa vídeo, remove o fundo (chroma key profissional) e exporta com transparência."""
from __future__ import annotations

import copy
import os
import sys

from PySide6.QtCore import QObject, QSize, Qt, QThread, QTimer
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPalette, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea,
    QSlider, QSpinBox, QStyle, QToolButton, QVBoxLayout, QWidget,
)

from . import APP_NAME, __version__, core, gpu, i18n, theme
from .dialogs import AboutDialog, SettingsDialog, app_icon, backend_text, logo_pixmap
from .exporters import FORMAT_BY_KEY, FORMATS, default_output_name, ffmpeg_available
from .fx import FX, fade_in, fade_window, set_neon
from .i18n import LANGUAGES, T
from .settings import Settings
from .widgets import (GradientTitle, PLAY_QUALITY, THUMB_H, ExportWorker, ParamCheck, ParamSlider, PlaybackWorker,
                      PreviewLabel, RenderWorker, Section, ThumbWorker, preview_frame)

MAX_THUMBS = 300
VIEWS = ["Resultado", "Máscara (alfa)", "Máscara da colorização", "Original", "Lado a lado"]
BACKGROUNDS = ["xadrez", "preto", "branco", "cor", "midia"]
BG_LABELS = ["Xadrez", "Preto", "Branco", "Cor…", "Imagem ou vídeo…"]
BG_MODES = [("fill", "Preencher"), ("fit", "Ajustar"), ("stretch", "Esticar")]
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff")
# formatos que usam cada opção de exportação
OPT_ROWS = {
    "prefix": {"png", "tga", "tiff", "webp_seq"},
    "bits": {"png", "tiff"},
    "comp": {"png"},
    "quality": {"webp", "webp_seq", "webm"},
    "lossless": {"webp", "webp_seq"},
    "fps": {"gif", "webp", "apng", "webm", "prores"},
    "loop": {"gif", "webp", "apng"},
    "gif": {"gif"},
    "tiffc": {"tiff"},
}


class MainWindow(QMainWindow):
    def __init__(self, ctrl):
        super().__init__()
        self.ctrl = ctrl
        self.setWindowTitle(f"{APP_NAME} — " + T("removedor de fundo de vídeo"))
        self.setWindowIcon(app_icon())
        self.resize(1400, 900)
        self.video = None
        self.path = None
        self.frame = None
        self.px_scale = 1.0
        self.key_rgb = core.PRESETS["Verde"]
        self.bg_rgb = (40, 40, 40)
        self.gif_matte_rgb = (255, 255, 255)
        self.background = core.Background()
        self._last_bg = 0
        self.sliders: dict[str, ParamSlider] = {}
        self.play_thread = self.play_worker = None
        self._items = {}
        self.thumb_thread = self.thumb_worker = None
        self.exp_thread = self.exp_worker = None
        self.out_path = ""
        self._opt_rows = {}
        self._neon_widgets = []

        self.render_thread = QThread()
        self.render_worker = RenderWorker()
        self.render_worker.moveToThread(self.render_thread)
        self.render_worker.result.connect(self._on_render)
        self.render_thread.start()
        self._render_timer = QTimer(self, singleShot=True, interval=15)
        self._render_timer.timeout.connect(self.render_preview)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 6)
        root.setSpacing(6)
        root.addWidget(self._build_header())

        top = QHBoxLayout()
        self.lbl_info = QLabel(T("Nenhum vídeo carregado"))
        self.lbl_info.setObjectName("muted")
        top.addWidget(self.lbl_info, 1)
        top.addWidget(QLabel(T("Visualizar:")))
        self.cmb_view = QComboBox()
        self.cmb_view.addItems([T(v) for v in VIEWS])
        self.cmb_view.setToolTip(T("O que mostrar na prévia (não muda a exportação)."))
        self.cmb_view.currentIndexChanged.connect(self.schedule_render)
        top.addWidget(self.cmb_view)
        top.addWidget(QLabel(T("Fundo:")))
        self.cmb_bg = QComboBox()
        self.cmb_bg.addItems([T(b) for b in BG_LABELS])
        self.cmb_bg.setToolTip(T("Fundo da prévia. 'Imagem ou vídeo…' permite testar o recorte sobre um "
                                 "cenário; só entra na exportação se você marcar 'Incluir fundo na exportação'."))
        self.cmb_bg.activated.connect(self._on_bg_activated)
        top.addWidget(self.cmb_bg)
        self.cmb_bgmode = QComboBox()
        for k, label in BG_MODES:
            self.cmb_bgmode.addItem(T(label), k)
        self.cmb_bgmode.setToolTip(T("Como encaixar a imagem/vídeo de fundo: preencher (corta), ajustar (bordas) "
                                     "ou esticar."))
        self.cmb_bgmode.currentIndexChanged.connect(self._on_bgmode)
        self.cmb_bgmode.setVisible(False)
        top.addWidget(self.cmb_bgmode)
        root.addLayout(top)

        mid = QHBoxLayout()
        self.preview = PreviewLabel()
        self.preview.clicked.connect(self.pick_from_preview)
        mid.addWidget(self.preview, 1)
        mid.addWidget(self._build_panel())
        root.addLayout(mid, 1)

        srow = QHBoxLayout()
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self.on_frame_changed)
        self.lbl_frame = QLabel(T("Quadro {i} / {n}").format(i=0, n=0))
        self.lbl_frame.setMinimumWidth(150)
        srow.addWidget(self.slider, 1)
        srow.addWidget(self.lbl_frame)
        root.addLayout(srow)

        prow = QHBoxLayout()
        self.btn_play = QPushButton(T("Reproduzir"))
        self.btn_play.setObjectName("primary")
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.btn_play.setToolTip(T("Reproduzir / pausar com o recorte aplicado (barra de espaço)"))
        self.btn_play.setEnabled(False)
        self.btn_play.setMinimumWidth(130)
        self.btn_play.clicked.connect(self.toggle_play)
        prow.addWidget(self.btn_play)
        prow.addWidget(QLabel(T("FPS:")))
        self.sp_fps = QDoubleSpinBox()
        self.sp_fps.setRange(1, 120)
        self.sp_fps.setDecimals(2)
        self.sp_fps.setValue(24)
        self.sp_fps.setToolTip(T("Velocidade da reprodução (padrão = FPS do vídeo)"))
        self.sp_fps.valueChanged.connect(self._on_fps_changed)
        prow.addWidget(self.sp_fps)
        self.chk_loop = QCheckBox(T("Repetir"))
        self.chk_loop.setChecked(True)
        self.chk_loop.setToolTip(T("Volta ao início ao chegar no fim do vídeo."))
        self.chk_loop.toggled.connect(lambda on: self.play_worker and self.play_worker.set_loop(on))
        prow.addWidget(self.chk_loop)
        prow.addWidget(QLabel(T("Qualidade da reprodução:")))
        self.cmb_playq = QComboBox()
        self.cmb_playq.addItems([T(n) for n, _ in PLAY_QUALITY])
        self.cmb_playq.setCurrentIndex(max(0, min(2, ctrl.settings.get("play_quality"))))
        self.cmb_playq.setToolTip(T("Resolução da prévia durante a reprodução: 'Rápida' fica fluida; "
                                    "'Completa' mostra mais detalhe (pode descartar quadros). "
                                    "Não afeta a exportação."))
        self.cmb_playq.currentIndexChanged.connect(self._on_playq)
        prow.addWidget(self.cmb_playq)
        self.lbl_fps = QLabel("")
        self.lbl_fps.setObjectName("muted")
        self.lbl_fps.setMinimumWidth(210)
        prow.addWidget(self.lbl_fps)
        prow.addStretch(1)
        root.addLayout(prow)

        self.timeline = QScrollArea()
        self.timeline.setObjectName("timeline")
        self.timeline.setWidgetResizable(True)
        self.timeline.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.timeline.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.timeline.setFixedHeight(THUMB_H + 58)
        self._strip = QWidget()
        self._strip_lay = QHBoxLayout(self._strip)
        self._strip_lay.setContentsMargins(4, 4, 4, 4)
        self._strip_lay.setSpacing(4)
        self._strip_lay.addStretch(1)
        self.timeline.setWidget(self._strip)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        lt = QLabel(T("Linha do tempo (clique num quadro para visualizar):"))
        lt.setObjectName("muted")
        root.addWidget(lt)
        root.addWidget(self.timeline)

        exp = QHBoxLayout()
        self.btn_export = QPushButton(T("Exportar…"))
        self.btn_export.setObjectName("primary")
        self.btn_export.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        self.btn_export.setMinimumWidth(170)
        self.btn_export.setEnabled(False)
        self.btn_export.setToolTip(T("Exporta no formato escolhido em 'Opções de exportação'."))
        self.btn_export.clicked.connect(self.start_export)
        self.btn_cancel = QPushButton(T("Cancelar"))
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_export)
        self.progress = QProgressBar()
        self.progress.setFormat(T("%v / %m quadros"))
        exp.addWidget(self.btn_export)
        exp.addWidget(self.progress, 1)
        exp.addWidget(self.btn_cancel)
        root.addLayout(exp)

        self.lbl_backend = QLabel()
        self.lbl_perf = QLabel()
        self.statusBar().addPermanentWidget(self.lbl_perf)
        self.statusBar().addPermanentWidget(self.lbl_backend)
        self.update_backend_label()
        self.statusBar().showMessage(T("Pronto"))
        sc = QShortcut(QKeySequence(Qt.Key_Space), self)
        sc.activated.connect(self.toggle_play)
        self._neon_widgets = [(self.lbl_title, 18), (self.btn_export, 14), (self.btn_play, 12), (self.btn_open, 12)]
        self.apply_fx()
        self._on_format_changed()

    # ---------------------------------------------------------- cabeçalho
    def _build_header(self):
        fr = QFrame()
        fr.setObjectName("header")
        h = QHBoxLayout(fr)
        h.setContentsMargins(12, 6, 10, 6)
        ic = QLabel()
        ic.setPixmap(logo_pixmap(40, self))
        h.addWidget(ic)
        self.lbl_title = GradientTitle(APP_NAME)
        h.addWidget(self.lbl_title)
        v = QLabel("v" + __version__)
        v.setObjectName("appVersion")
        h.addWidget(v)
        h.addSpacing(14)
        self.btn_open = QPushButton(T("Importar vídeo…"))
        self.btn_open.setObjectName("primary")
        self.btn_open.setIcon(self.style().standardIcon(QStyle.SP_DialogOpenButton))
        self.btn_open.setToolTip(T("Abrir um vídeo (MP4, MOV, AVI, MKV, WebM…)"))
        self.btn_open.clicked.connect(self.open_video)
        h.addWidget(self.btn_open)
        h.addStretch(1)
        self.btn_theme = QPushButton()
        self.btn_theme.setToolTip(T("Alternar entre tema claro e escuro"))
        self.btn_theme.clicked.connect(lambda: self.ctrl.set_theme(
            "light" if self.ctrl.settings.get("theme") == "dark" else "dark"))
        h.addWidget(self.btn_theme)
        self.cmb_lang = QComboBox()
        codes = [c for c, _ in LANGUAGES]
        for code, name in LANGUAGES:
            self.cmb_lang.addItem(name, code)
        self.cmb_lang.setCurrentIndex(codes.index(i18n.language()) if i18n.language() in codes else 0)
        self.cmb_lang.setToolTip(T("Idioma da interface (muda na hora)"))
        self.cmb_lang.activated.connect(lambda _i: self.ctrl.set_language(self.cmb_lang.currentData()))
        h.addWidget(self.cmb_lang)
        b = QPushButton(T("Configurações"))
        b.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        b.setToolTip(T("Tema, idioma, animações, neon e renderização (CPU/GPU)"))
        b.clicked.connect(self.open_settings)
        h.addWidget(b)
        b = QPushButton(T("Sobre"))
        b.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxInformation))
        b.setToolTip(T("Sobre o {app}").format(app=APP_NAME))
        b.clicked.connect(self.open_about)
        h.addWidget(b)
        self.update_theme_button()
        return fr

    def update_theme_button(self):
        dark = self.ctrl.settings.get("theme") == "dark"
        self.btn_theme.setText(T("Tema claro") if dark else T("Tema escuro"))

    def open_about(self):
        AboutDialog(self).exec()

    def open_settings(self):
        SettingsDialog(self.ctrl, self).exec()

    def apply_fx(self):
        for w, r in self._neon_widgets:
            set_neon(w, FX.neon, r)

    def update_backend_label(self):
        self.lbl_backend.setText(T("Renderização: {b}").format(b=backend_text()))

    # ---------------------------------------------------------- painel lateral
    def _build_panel(self):
        scroll = QScrollArea()
        scroll.setObjectName("panel")
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(410)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        sec = Section(T("Cor-chave"), expanded=True)
        self.chk_enable = QCheckBox(T("Aplicar remoção de fundo"))
        self.chk_enable.setChecked(True)
        self.chk_enable.toggled.connect(self.schedule_render)
        sec.add_row("", self.chk_enable, T("Desligue para comparar com o vídeo original."))
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        for name in ("Verde", "Azul"):
            b = QPushButton(T(name))
            b.setToolTip(T("Usar a cor-chave padrão: {c}").format(c=T(name)))
            b.clicked.connect(lambda _=False, n=name: self.set_key(core.PRESETS[n]))
            rl.addWidget(b)
        b = QPushButton(T("Outra…"))
        b.setToolTip(T("Escolher qualquer cor como cor-chave"))
        b.clicked.connect(self.choose_color)
        rl.addWidget(b)
        sec.add_row("", row)
        self.btn_pick = QPushButton(T("Escolher cor clicando no vídeo"))
        self.btn_pick.setCheckable(True)
        self.btn_pick.setToolTip(T("Clique depois no fundo do vídeo, na prévia, para pegar a cor exata."))
        self.btn_pick.toggled.connect(self.toggle_pick)
        sec.add_row("", self.btn_pick)
        sw = QWidget()
        swl = QHBoxLayout(sw)
        swl.setContentsMargins(0, 0, 0, 0)
        self.swatch = QLabel()
        self.swatch.setFixedSize(60, 22)
        self.lbl_rgb = QLabel()
        swl.addWidget(self.swatch)
        swl.addWidget(self.lbl_rgb, 1)
        sec.add_row(T("Cor atual"), sw)
        lay.addWidget(sec)

        dc = T("(duplo clique: padrão)")
        for i, (title, items) in enumerate(core.PARAM_SECTIONS):
            sec = Section(T(title), expanded=(i <= 1))
            for key, label, lo, hi, default, tip in items:
                s = ParamCheck(default) if (lo, hi) == (0, 1) else ParamSlider(lo, hi, default)
                s.valueChanged.connect(self.schedule_render)
                self.sliders[key] = s
                sec.add_row(T(label), s, (T(tip) + "  " + dc) if tip else dc)
            lay.addWidget(sec)

        sec = Section(T("Presets"))
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        b1, b2, b3 = QPushButton(T("Salvar preset…")), QPushButton(T("Carregar preset…")), QPushButton(T("Restaurar padrão"))
        b1.setToolTip(T("Salva todos os ajustes num arquivo .json"))
        b2.setToolTip(T("Carrega ajustes salvos de um arquivo .json"))
        b3.setToolTip(T("Volta todos os parâmetros para o padrão"))
        b1.clicked.connect(self.save_preset)
        b2.clicked.connect(self.load_preset)
        b3.clicked.connect(self.reset_defaults)
        rl.addWidget(b1)
        rl.addWidget(b2)
        sec.add_row("", row)
        sec.add_row("", b3)
        lay.addWidget(sec)

        lay.addWidget(self._build_export_section())
        lay.addStretch(1)
        scroll.setWidget(panel)
        self._update_swatch()
        return scroll

    def _opt(self, sec, key, label, widget, tip=""):
        lbl, w = sec.add_row(label, widget, tip)
        self._opt_rows.setdefault(key, []).extend([x for x in (lbl, w) if x is not None])

    def _build_export_section(self):
        sec = Section(T("Opções de exportação"), expanded=True)
        self.cmb_fmt = QComboBox()
        for f in FORMATS:
            self.cmb_fmt.addItem(T(f.label), f.key)
        self.cmb_fmt.setToolTip(T("Sequências de imagens (uma por quadro) ou um único arquivo animado/vídeo, "
                                  "todos com transparência."))
        self.cmb_fmt.currentIndexChanged.connect(self._on_format_changed)
        sec.add_row(T("Formato"), self.cmb_fmt, self.cmb_fmt.toolTip())
        self.sp_in, self.sp_out = QSpinBox(), QSpinBox()
        for sp in (self.sp_in, self.sp_out):
            sp.setRange(1, 1)
        for sp, label, tip in ((self.sp_in, T("Quadro inicial"), T("Primeiro quadro a exportar.")),
                               (self.sp_out, T("Quadro final"), T("Último quadro a exportar (inclusive)."))):
            rw = QWidget()
            rl = QHBoxLayout(rw)
            rl.setContentsMargins(0, 0, 0, 0)
            b = QPushButton(T("Usar atual"))
            b.setToolTip(T("Usar o quadro mostrado na prévia"))
            b.clicked.connect(lambda _=False, t=sp: t.setValue(self.slider.value() + 1))
            rl.addWidget(sp, 1)
            rl.addWidget(b)
            sec.add_row(label, rw, tip)
        self.sp_step = QSpinBox()
        self.sp_step.setRange(1, 1000)
        sec.add_row(T("1 a cada N quadros"), self.sp_step, T("1 = todos; 2 = um sim, um não; etc."))
        sw = QWidget()
        sl = QHBoxLayout(sw)
        sl.setContentsMargins(0, 0, 0, 0)
        self.cmb_scale = QComboBox()
        self._scales = [1.0, 2.0, 4.0, 0.5, 0.25, None]
        self.cmb_scale.addItems(["1x", "2x", "4x", "0,5x", "0,25x", T("Personalizado")])
        self.sp_scale = QSpinBox()
        self.sp_scale.setRange(5, 800)
        self.sp_scale.setValue(100)
        self.sp_scale.setSuffix(" %")
        self.sp_scale.setEnabled(False)
        self.cmb_scale.currentIndexChanged.connect(lambda i: self.sp_scale.setEnabled(self._scales[i] is None))
        sl.addWidget(self.cmb_scale)
        sl.addWidget(self.sp_scale)
        sec.add_row(T("Escala"), sw, T("Ampliar recalcula as bordas na resolução final (Lanczos)."))
        self.sp_xfps = QDoubleSpinBox()
        self.sp_xfps.setRange(0, 120)
        self.sp_xfps.setDecimals(2)
        self.sp_xfps.setSpecialValueText(T("Automático"))
        self._opt(sec, "fps", T("FPS da animação"), self.sp_xfps,
                  T("Automático = FPS do vídeo ÷ passo (mantém a velocidade original)."))
        self.sp_loop = QSpinBox()
        self.sp_loop.setRange(0, 1000)
        self.sp_loop.setSpecialValueText(T("Infinito"))
        self._opt(sec, "loop", T("Repetições"), self.sp_loop, T("Quantas vezes a animação repete (Infinito = sempre)."))
        self.ed_prefix = QLineEdit("frame_")
        self._opt(sec, "prefix", T("Prefixo do nome"), self.ed_prefix, T("Ex.: frame_ → frame_00001.png"))
        self.cmb_bits = QComboBox()
        self.cmb_bits.addItems([T("8 bits por canal"), T("16 bits por canal")])
        self._opt(sec, "bits", T("Profundidade"), self.cmb_bits, T("16 bits: bordas/alfa mais precisos, arquivos maiores."))
        self.sp_comp = QSpinBox()
        self.sp_comp.setRange(0, 9)
        self.sp_comp.setValue(3)
        self._opt(sec, "comp", T("Compressão PNG"), self.sp_comp,
                  T("0 = mais rápido/maior, 9 = menor/mais lento (sem perda)."))
        self.chk_tiffc = QCheckBox(T("Compressão LZW (sem perda)"))
        self.chk_tiffc.setChecked(True)
        self._opt(sec, "tiffc", "", self.chk_tiffc, T("Arquivos TIFF menores, sem perder qualidade."))
        self.sp_quality = QSpinBox()
        self.sp_quality.setRange(1, 100)
        self.sp_quality.setValue(90)
        self._opt(sec, "quality", T("Qualidade"), self.sp_quality, T("Mais alto = melhor imagem e arquivo maior."))
        self.chk_lossless = QCheckBox(T("Sem perdas (lossless)"))
        self._opt(sec, "lossless", "", self.chk_lossless, T("Qualidade máxima; arquivos bem maiores."))
        # GIF
        self.sp_gif_thr = QSpinBox()
        self.sp_gif_thr.setRange(1, 255)
        self.sp_gif_thr.setValue(128)
        self._opt(sec, "gif", T("Limiar de transparência"), self.sp_gif_thr,
                  T("GIF só tem pixel 100% transparente ou opaco: alfa abaixo deste valor vira transparente."))
        self.sp_gif_colors = QSpinBox()
        self.sp_gif_colors.setRange(2, 256)
        self.sp_gif_colors.setValue(256)
        self._opt(sec, "gif", T("Cores da paleta"), self.sp_gif_colors, T("Máximo 256 (uma é reservada para a transparência)."))
        self.cmb_gif_pal = QComboBox()
        self.cmb_gif_pal.addItem(T("Alta (mediana)"), "alta")
        self.cmb_gif_pal.addItem(T("Rápida (octree)"), "rápida")
        self._opt(sec, "gif", T("Qualidade da paleta"), self.cmb_gif_pal, T("Método de redução de cores."))
        self.chk_gif_dither = QCheckBox(T("Pontilhado (dither)"))
        self.chk_gif_dither.setChecked(True)
        self._opt(sec, "gif", "", self.chk_gif_dither, T("Suaviza degradês com pontilhado (arquivo um pouco maior)."))
        mw = QWidget()
        ml = QHBoxLayout(mw)
        ml.setContentsMargins(0, 0, 0, 0)
        self.chk_gif_matte = QCheckBox(T("Misturar bordas com a cor"))
        self.chk_gif_matte.setChecked(True)
        self.btn_matte = QPushButton()
        self.btn_matte.setFixedWidth(70)
        self.btn_matte.clicked.connect(self.choose_matte)
        ml.addWidget(self.chk_gif_matte, 1)
        ml.addWidget(self.btn_matte)
        self._opt(sec, "gif", T("Borda (matte)"), mw,
                  T("As bordas semitransparentes são misturadas com esta cor (use a cor do fundo onde o GIF vai "
                    "aparecer) para não ficarem serrilhadas/escuras."))
        self._update_matte()
        self.chk_include_bg = QCheckBox(T("Incluir fundo na exportação"))
        self.chk_include_bg.setToolTip(T("Compõe a imagem/vídeo de fundo escolhido na prévia no arquivo exportado "
                                         "(resultado opaco)."))
        self.chk_include_bg.toggled.connect(self._update_export_info)
        sec.add_row("", self.chk_include_bg, self.chk_include_bg.toolTip())
        self.lbl_out_info = QLabel("")
        self.lbl_out_info.setObjectName("muted")
        self.lbl_out_info.setWordWrap(True)
        sec.add_row("", self.lbl_out_info)
        for w in (self.sp_in, self.sp_out, self.sp_step, self.sp_scale):
            w.valueChanged.connect(self._update_export_info)
        self.sp_xfps.valueChanged.connect(self._update_export_info)
        self.cmb_scale.currentIndexChanged.connect(self._update_export_info)
        return sec

    def _on_format_changed(self, *_):
        key = self.cmb_fmt.currentData()
        for opt, keys in OPT_ROWS.items():
            for w in self._opt_rows.get(opt, []):
                w.setVisible(key in keys)
        self._update_export_info()

    def choose_matte(self):
        c = QColorDialog.getColor(QColor(*self.gif_matte_rgb), self, T("Cor das bordas (matte) do GIF"))
        if c.isValid():
            self.gif_matte_rgb = (c.red(), c.green(), c.blue())
            self._update_matte()

    def _update_matte(self):
        r, g, b = self.gif_matte_rgb
        self.btn_matte.setStyleSheet(f"background: rgb({r},{g},{b}); border:1px solid #777; border-radius:6px;")
        self.btn_matte.setToolTip(f"#{r:02X}{g:02X}{b:02X}")

    # ---------------------------------------------------------- vídeo
    def open_video(self):
        exts = " ".join(f"*{e}" for e in core.VIDEO_EXTS)
        path, _ = QFileDialog.getOpenFileName(self, T("Importar vídeo"), self.ctrl.settings.get("last_dir"),
                                              f"{T('Vídeos')} ({exts});;{T('Todos')} (*.*)")
        if path:
            self.ctrl.settings.set("last_dir", os.path.dirname(path))
            self.load_video(path)

    def load_video(self, path, frame_idx=0):
        try:
            v = core.Video(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, T("Erro"), T("Não foi possível abrir o vídeo:") + f"\n{e}")
            return False
        self.stop_play()
        self._stop_thumbs()
        if self.video:
            self.video.release()
        self.video, self.path = v, path
        dur = v.frame_count / v.fps if v.fps else 0
        self.lbl_info.setText(T("{name} — {w}×{h}, {n} quadros, {fps} fps, {dur} s").format(
            name=os.path.basename(path), w=v.width, h=v.height, n=v.frame_count, fps=f"{v.fps:.2f}", dur=f"{dur:.1f}"))
        self.slider.setEnabled(True)
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(0, v.frame_count - 1))
        self.slider.blockSignals(False)
        for sp in (self.sp_in, self.sp_out):
            sp.setRange(1, max(1, v.frame_count))
        self.sp_in.setValue(1)
        self.sp_out.setValue(v.frame_count)
        self.btn_export.setEnabled(True)
        self.btn_play.setEnabled(True)
        self.sp_fps.blockSignals(True)
        self.sp_fps.setValue(min(120.0, max(1.0, v.fps or 24.0)))
        self.sp_fps.blockSignals(False)
        self.lbl_fps.setText("")
        self._clear_timeline()
        n = min(MAX_THUMBS, v.frame_count)
        indices = sorted(set(int(round(i * (v.frame_count - 1) / max(1, n - 1))) for i in range(n)))
        tw = int(THUMB_H * v.width / max(1, v.height))
        for idx in indices:
            b = QToolButton()
            b.setObjectName("thumb")
            b.setText(str(idx + 1))
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setIconSize(QSize(tw, THUMB_H))
            b.setFixedSize(tw + 12, THUMB_H + 30)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, i=idx: self.slider.setValue(i))
            self._group.addButton(b)
            self._strip_lay.insertWidget(self._strip_lay.count() - 1, b)
            self._items[idx] = b
        if len(indices) < v.frame_count:
            self.statusBar().showMessage(T("Vídeo longo: a linha do tempo mostra {n} amostras; use o controle "
                                           "deslizante para ver qualquer quadro.").format(n=len(indices)))
        frame_idx = max(0, min(frame_idx, v.frame_count - 1))
        self.slider.setValue(frame_idx)
        self.on_frame_changed(frame_idx)
        self._start_thumbs(indices)
        self._update_export_info()
        fade_in(self.preview)
        return True

    def _clear_timeline(self):
        for b in self._items.values():
            self._group.removeButton(b)
            b.deleteLater()
        self._items = {}

    def _start_thumbs(self, indices):
        self.thumb_thread = QThread()
        self.thumb_worker = ThumbWorker(self.path, indices)
        self.thumb_worker.moveToThread(self.thumb_thread)
        self.thumb_thread.started.connect(self.thumb_worker.run)
        self.thumb_worker.thumb.connect(self._on_thumb)
        self.thumb_worker.done.connect(self.thumb_thread.quit)
        self.thumb_thread.start()

    def _stop_thumbs(self):
        if self.thumb_thread and self.thumb_thread.isRunning():
            self.thumb_worker.stop()
            self.thumb_thread.quit()
            self.thumb_thread.wait(10000)

    def _on_thumb(self, idx, qimg):
        it = self._items.get(idx)
        if it:
            it.setIcon(QIcon(QPixmap.fromImage(qimg)))

    def on_frame_changed(self, idx):
        if not self.video:
            return
        if self.is_playing():
            self.play_worker.seek(idx)
            self._mark_frame(idx)
            return
        f = self.video.read(idx)
        if f is None:
            return
        self.frame, self.px_scale = preview_frame(f)
        self._mark_frame(idx)
        self.schedule_render()

    def _mark_frame(self, idx):
        self.lbl_frame.setText(T("Quadro {i} / {n}").format(i=idx + 1, n=self.video.frame_count))
        it = self._items.get(idx)
        if it:
            it.setChecked(True)
            self.timeline.ensureWidgetVisible(it, 60, 0)

    # ---------------------------------------------------------- reprodução
    def is_playing(self):
        return self.play_thread is not None and self.play_thread.isRunning()

    def _job(self):
        view = "Original" if self.preview.picking else VIEWS[self.cmb_view.currentIndex()]
        bgk = BACKGROUNDS[self.cmb_bg.currentIndex()]
        return (copy.deepcopy(self.params()), view, bgk, self.bg_rgb,
                self.background if bgk == "midia" and self.background.active else None)

    def toggle_play(self):
        if self.is_playing():
            self.stop_play()
        else:
            self.start_play()

    def start_play(self):
        if not self.path or self.is_playing():
            return
        start = self.slider.value()
        if start >= self.video.frame_count - 1:
            start = 0
        self.play_thread = QThread()
        self.play_worker = PlaybackWorker(self.path, start, self.sp_fps.value(), self.chk_loop.isChecked(),
                                          self._job(), PLAY_QUALITY[self.cmb_playq.currentIndex()][1])
        self.play_worker.moveToThread(self.play_thread)
        self.play_thread.started.connect(self.play_worker.run)
        self.play_worker.frame.connect(self._on_play_frame)
        self.play_worker.finished.connect(self.play_thread.quit)
        self.play_thread.finished.connect(self._on_play_stopped)
        self.btn_play.setText(T("Pausar"))
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        self.play_thread.start()

    def stop_play(self):
        if self.play_worker:
            self.play_worker.stop()
        if self.play_thread and self.play_thread.isRunning():
            self.play_thread.quit()
            self.play_thread.wait(5000)
        self._on_play_stopped()

    def _on_play_stopped(self):
        if self.play_thread is None:
            return
        self.play_thread = self.play_worker = None
        self.btn_play.setText(T("Reproduzir"))
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        if self.video:
            self.on_frame_changed(self.slider.value())

    def _on_play_frame(self, idx, frame, sc, qimg, fps, dropped):
        if not self.is_playing():
            return
        self.frame, self.px_scale = frame, sc
        self.preview.set_image(qimg)
        self.slider.blockSignals(True)
        self.slider.setValue(idx)
        self.slider.blockSignals(False)
        self._mark_frame(idx)
        self.lbl_fps.setText(T("real: {fps} fps · {n} descartados").format(fps=f"{fps:.1f}", n=dropped))

    def _on_playq(self, i):
        self.ctrl.settings.set("play_quality", int(i))
        self._restart_play()

    def _restart_play(self, *_):
        if self.is_playing():
            self.stop_play()
            self.start_play()

    def _on_fps_changed(self, v):
        if self.play_worker:
            self.play_worker.set_fps(v)

    # ---------------------------------------------------------- parâmetros
    def params(self) -> core.KeyParams:
        return core.KeyParams(tuple(self.key_rgb), {k: s.value() for k, s in self.sliders.items()},
                              self.chk_enable.isChecked())

    def apply_params(self, p: core.KeyParams):
        for s in self.sliders.values():
            s.blockSignals(True)
        for k, s in self.sliders.items():
            s.setValue(p.values.get(k, s.default))
        for s in self.sliders.values():
            s.blockSignals(False)
        self.chk_enable.setChecked(p.enabled)
        self.set_key(p.key_rgb)

    def reset_defaults(self):
        self.apply_params(core.KeyParams())
        self.statusBar().showMessage(T("Parâmetros restaurados para o padrão."))

    def save_preset(self):
        path, _ = QFileDialog.getSaveFileName(self, T("Salvar preset"), "meu_preset.json", "Preset (*.json)")
        if path:
            core.save_preset(path, self.params())
            self.statusBar().showMessage(T("Preset salvo: {p}").format(p=path))

    def load_preset(self):
        path, _ = QFileDialog.getOpenFileName(self, T("Carregar preset"), "", "Preset (*.json)")
        if path:
            try:
                self.apply_params(core.load_preset(path))
                self.statusBar().showMessage(T("Preset carregado: {p}").format(p=path))
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(self, T("Erro"), T("Preset inválido:") + f"\n{e}")

    def export_options(self) -> core.ExportOptions:
        i = self.cmb_scale.currentIndex()
        scale = self._scales[i] if self._scales[i] is not None else self.sp_scale.value() / 100.0
        a, b = sorted((self.sp_in.value(), self.sp_out.value()))
        return core.ExportOptions(
            start=a - 1, end=b - 1, step=self.sp_step.value(), prefix=self.ed_prefix.text() or "frame_",
            scale=scale, bit16=self.cmb_bits.currentIndex() == 1, compression=self.sp_comp.value(),
            fmt=self.cmb_fmt.currentData(), fps=self.sp_xfps.value(), loop=self.sp_loop.value(),
            quality=self.sp_quality.value(), lossless=self.chk_lossless.isChecked(),
            gif_colors=self.sp_gif_colors.value(), gif_dither=self.chk_gif_dither.isChecked(),
            gif_alpha_threshold=self.sp_gif_thr.value(), gif_palette=self.cmb_gif_pal.currentData(),
            gif_matte=self.chk_gif_matte.isChecked(), gif_matte_rgb=tuple(self.gif_matte_rgb),
            include_bg=self.chk_include_bg.isChecked() and self.background.active,
            tiff_compress=self.chk_tiffc.isChecked())

    def _update_export_info(self, *_):
        if not self.video:
            return
        o = self.export_options()
        f = FORMAT_BY_KEY[o.fmt]
        n = (o.end - o.start) // o.step + 1
        size = f"{int(round(self.video.width * o.scale))}×{int(round(self.video.height * o.scale))} px"
        if f.single_file:
            fps = o.fps if o.fps > 0 else (self.video.fps or 30) / o.step
            txt = T("1 arquivo, {n} quadros, {size}, {fps} fps").format(n=n, size=size, fps=f"{fps:.2f}")
        else:
            txt = T("{n} arquivos, {size}").format(n=n, size=size)
        if o.include_bg:
            txt += " · " + T("com fundo (opaco)")
        if f.needs_ffmpeg and not ffmpeg_available():
            txt += " · " + T("ffmpeg não encontrado")
        self.lbl_out_info.setText(txt)

    # ---------------------------------------------------------- prévia e fundo
    def schedule_render(self, *_):
        self._render_timer.start()

    def _on_bg_activated(self, i):
        key = BACKGROUNDS[i]
        if key == "cor":
            c = QColorDialog.getColor(QColor(*self.bg_rgb), self, T("Cor de fundo da prévia"))
            if c.isValid():
                self.bg_rgb = (c.red(), c.green(), c.blue())
        elif key == "midia":
            exts = " ".join(f"*{e}" for e in IMAGE_EXTS + core.VIDEO_EXTS)
            path, _ = QFileDialog.getOpenFileName(self, T("Imagem ou vídeo de fundo"), self.ctrl.settings.get("last_dir"),
                                                  f"{T('Imagens e vídeos')} ({exts});;{T('Todos')} (*.*)")
            if not path or not self.set_background(path):
                if not self.background.active:
                    self.cmb_bg.setCurrentIndex(self._last_bg)
        self._last_bg = self.cmb_bg.currentIndex()
        self.cmb_bgmode.setVisible(BACKGROUNDS[self._last_bg] == "midia")
        self._update_export_info()
        self.schedule_render()

    def set_background(self, path, mode=None):
        try:
            self.background.load(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, T("Erro"), T("Não foi possível abrir o fundo:") + f"\n{e}")
            return False
        if mode:
            self.cmb_bgmode.setCurrentIndex([k for k, _ in BG_MODES].index(mode))
        self.background.mode = self.cmb_bgmode.currentData()
        self.cmb_bg.setCurrentIndex(BACKGROUNDS.index("midia"))
        self._last_bg = self.cmb_bg.currentIndex()
        self.cmb_bgmode.setVisible(True)
        self.statusBar().showMessage(T("Fundo: {name}").format(name=os.path.basename(path)))
        self._update_export_info()
        self.schedule_render()
        return True

    def _on_bgmode(self, *_):
        self.background.mode = self.cmb_bgmode.currentData()
        self.background._cache = None
        self.schedule_render()

    def render_preview(self):
        if self.frame is None:
            return
        if self.is_playing():
            self.play_worker.set_job(self._job())
            return
        self.render_worker.submit((self.frame, self.slider.value(), self._job(), self.px_scale))

    def _on_render(self, qimg, ms):
        self.preview.set_image(qimg)
        self.lbl_perf.setText(T("prévia: {ms} ms").format(ms=f"{ms:.0f}"))

    def set_key(self, rgb):
        self.key_rgb = tuple(int(c) for c in rgb)
        self._update_swatch()
        self.schedule_render()

    def _update_swatch(self):
        r, g, b = self.key_rgb
        self.swatch.setStyleSheet(f"background: rgb({r},{g},{b}); border:1px solid #555; border-radius:4px;")
        self.lbl_rgb.setText(f"#{r:02X}{g:02X}{b:02X}")

    def choose_color(self):
        c = QColorDialog.getColor(QColor(*self.key_rgb), self, T("Escolha a cor do fundo"))
        if c.isValid():
            self.set_key((c.red(), c.green(), c.blue()))

    def toggle_pick(self, on):
        self.preview.picking = on
        self.preview.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)
        if on:
            self.statusBar().showMessage(T("Clique no fundo do vídeo para escolher a cor."))
        self.schedule_render()

    def pick_from_preview(self, rx, ry):
        if self.frame is None:
            return
        h, w = self.frame.shape[:2]
        x, y = int(rx * w), int(ry * h)
        patch = self.frame[max(0, y - 2):y + 3, max(0, x - 2):x + 3].reshape(-1, 3).mean(axis=0)
        b, g, r = (int(v) for v in patch)
        self.set_key((r, g, b))
        self.btn_pick.setChecked(False)
        self.toggle_pick(False)
        self.statusBar().showMessage(T("Cor escolhida: {c}").format(c=f"#{r:02X}{g:02X}{b:02X}"))

    # ---------------------------------------------------------- exportação
    def start_export(self, out=None):
        if not self.path:
            return
        opts = self.export_options()
        f = FORMAT_BY_KEY[opts.fmt]
        if f.needs_ffmpeg and not ffmpeg_available():
            QMessageBox.critical(self, T("Erro na exportação"), T("ffmpeg não encontrado"))
            return
        if out is None:
            last = self.ctrl.settings.get("last_dir")
            if f.single_file:
                flt = f"{T(f.label)} (*{f.ext})"
                out, _ = QFileDialog.getSaveFileName(self, T("Salvar como"),
                                                     os.path.join(last, default_output_name(self.path, f.key)), flt)
                if out and not out.lower().endswith(f.ext):
                    out += f.ext
            else:
                out = QFileDialog.getExistingDirectory(self, T("Escolha a pasta de destino"), last)
                if out and any(n.startswith(opts.prefix) and n.lower().endswith(f.ext) for n in os.listdir(out)):
                    r = QMessageBox.question(self, T("Pasta não vazia"),
                                             T("Esta pasta já tem arquivos {p}*{ext} que podem ser substituídos. "
                                               "Continuar?").format(p=opts.prefix, ext=f.ext))
                    if r != QMessageBox.Yes:
                        return
            if not out:
                return
            self.ctrl.settings.set("last_dir", out if os.path.isdir(out) else os.path.dirname(out))
        self.out_path = out
        self.progress.setRange(0, max(1, (opts.end - opts.start) // opts.step + 1))
        self.progress.setValue(0)
        self.btn_export.setEnabled(False)
        self.btn_open.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        bg = self.background.clone() if opts.include_bg else None
        self.exp_thread = QThread()
        self.exp_worker = ExportWorker(self.path, out, copy.deepcopy(self.params()), opts, bg)
        self.exp_worker.moveToThread(self.exp_thread)
        self.exp_thread.started.connect(self.exp_worker.run)
        self.exp_worker.progress.connect(self._on_progress)
        self.exp_worker.finished.connect(self._on_export_done)
        self.exp_worker.finished.connect(self.exp_thread.quit)
        self.exp_thread.start()
        self.statusBar().showMessage(T("Exportando…"))

    def is_exporting(self):
        return self.exp_thread is not None and self.exp_thread.isRunning()

    def _on_progress(self, c, t):
        if self.progress.maximum() != t:
            self.progress.setMaximum(t)
        self.progress.setValue(c)

    def cancel_export(self):
        if self.exp_worker:
            self.exp_worker.cancel()
            self.btn_cancel.setEnabled(False)

    def _on_export_done(self, n, cancelled, err, output):
        self.btn_export.setEnabled(True)
        self.btn_open.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.last_export = (n, cancelled, err, output)
        if err:
            if not getattr(self.ctrl, "quiet", False):
                QMessageBox.critical(self, T("Erro na exportação"), err)
            self.statusBar().showMessage(T("Erro na exportação") + ": " + err)
        elif cancelled:
            self.statusBar().showMessage(T("Exportação cancelada ({n} quadros salvos).").format(n=n))
        else:
            msg = T("{n} quadros exportados para:").format(n=n) + f"\n{output}"
            self.statusBar().showMessage(msg.replace("\n", " "))
            if not getattr(self.ctrl, "quiet", False):
                QMessageBox.information(self, T("Concluído"), msg)

    # ---------------------------------------------------------- estado (troca de idioma)
    def snapshot(self):
        return {
            "path": self.path, "idx": self.slider.value(), "params": self.params(), "view": self.cmb_view.currentIndex(),
            "bg": self.cmb_bg.currentIndex(), "bg_rgb": self.bg_rgb, "bg_path": self.background.path,
            "bg_mode": self.cmb_bgmode.currentIndex(), "fmt": self.cmb_fmt.currentIndex(),
            "matte": self.gif_matte_rgb, "fps": self.sp_fps.value(), "loop": self.chk_loop.isChecked(),
            "include_bg": self.chk_include_bg.isChecked(), "geometry": self.saveGeometry(),
            "maximized": self.isMaximized(),
        }

    def restore(self, st):
        if st.get("path") and os.path.isfile(st["path"]):
            self.load_video(st["path"], st.get("idx", 0))
        self.apply_params(st["params"])
        self.cmb_view.setCurrentIndex(st.get("view", 0))
        self.bg_rgb = st.get("bg_rgb", self.bg_rgb)
        self.cmb_bgmode.setCurrentIndex(st.get("bg_mode", 0))
        if st.get("bg_path") and os.path.isfile(st["bg_path"]):
            self.set_background(st["bg_path"])
        self.cmb_bg.setCurrentIndex(st.get("bg", 0))
        self._last_bg = self.cmb_bg.currentIndex()
        self.cmb_bgmode.setVisible(BACKGROUNDS[self._last_bg] == "midia")
        self.cmb_fmt.setCurrentIndex(st.get("fmt", 0))
        self.gif_matte_rgb = st.get("matte", self.gif_matte_rgb)
        self._update_matte()
        self.sp_fps.setValue(st.get("fps", self.sp_fps.value()))
        self.chk_loop.setChecked(st.get("loop", True))
        self.chk_include_bg.setChecked(st.get("include_bg", False))
        if st.get("geometry") is not None:
            self.restoreGeometry(st["geometry"])
        self.schedule_render()

    def shutdown(self):
        self.stop_play()
        if self.exp_worker:
            self.exp_worker.cancel()
        if self.exp_thread and self.exp_thread.isRunning():
            self.exp_thread.quit()
            self.exp_thread.wait(10000)
        self._stop_thumbs()
        if self.render_thread.isRunning():
            self.render_thread.quit()
            self.render_thread.wait(3000)
        if self.video:
            self.video.release()
            self.video = None
        self.background.clear()

    def closeEvent(self, e):
        if not getattr(self, "_replacing", False):
            self.shutdown()
        super().closeEvent(e)


# ============================================================ controlador
class Controller(QObject):
    """Guarda as preferências e aplica tema/idioma/efeitos/renderização (a janela pode ser recriada)."""

    def __init__(self, app, settings=None):
        super().__init__()
        self.app = app
        self.settings = settings or Settings()
        self.window = None
        self.quiet = False
        accent = self.settings.get("accent") or theme.ACCENT
        FX.accent = accent
        FX.animations = self.settings.get("animations")
        FX.neon = self.settings.get("neon")
        i18n.set_language(self.settings.get("lang"))
        gpu.set_mode(self.settings.get("render"))
        app.setWindowIcon(app_icon())
        self.apply_theme()

    def accent(self):
        return self.settings.get("accent") or theme.ACCENT

    def apply_theme(self):
        t = self.settings.get("theme")
        t = t if t in theme.THEMES else "dark"
        self.app.setStyle("Fusion")
        p = theme.palette(t, self.accent())
        pal = QPalette()
        for role, key in ((QPalette.Window, "bg"), (QPalette.Base, "input"), (QPalette.AlternateBase, "panel2"),
                          (QPalette.Button, "panel2"), (QPalette.WindowText, "text"), (QPalette.Text, "text"),
                          (QPalette.ButtonText, "text"), (QPalette.ToolTipBase, "panel2"), (QPalette.ToolTipText, "text"),
                          (QPalette.Highlight, "accent"), (QPalette.HighlightedText, "accent_text"),
                          (QPalette.Link, "accent"), (QPalette.PlaceholderText, "muted")):
            pal.setColor(role, QColor(p[key]))
        self.app.setPalette(pal)
        self.app.setStyleSheet(theme.stylesheet(t, self.accent()))
        if self.window:
            self.window.update_theme_button()

    def set_theme(self, t):
        self.settings.set("theme", t)
        self.apply_theme()

    def set_fx(self, animations=None, neon=None):
        if animations is not None:
            FX.animations = bool(animations)
            self.settings.set("animations", bool(animations))
        if neon is not None:
            FX.neon = bool(neon)
            self.settings.set("neon", bool(neon))
        if self.window:
            self.window.apply_fx()

    def set_render(self, mode):
        self.settings.set("render", mode)
        gpu.set_mode(mode)
        if self.window:
            self.window.update_backend_label()
            self.window.schedule_render()

    def create_window(self, state=None):
        w = MainWindow(self)
        if state:
            w.restore(state)
        self.window = w
        return w

    def set_language(self, code):
        code = i18n.set_language(code)
        self.settings.set("lang", code)
        old = self.window
        if old is None:
            return None
        if old.is_exporting():
            # não interrompe uma exportação: aplica ao reiniciar
            QMessageBox.information(old, APP_NAME, T("O idioma será aplicado quando a exportação terminar "
                                                     "ou ao reabrir o programa."))
            return None
        st = old.snapshot()
        old.shutdown()
        w = self.create_window(st)
        if not st.get("maximized"):
            w.setGeometry(old.geometry())          # mesma posição/tamanho da janela anterior
        if st.get("maximized"):
            w.showMaximized()
        else:
            w.show()
        old._replacing = True
        old.close()
        old.deleteLater()
        return w


def main():
    if "--self-test" in sys.argv:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from .selftest import self_test
        sys.exit(self_test(sys.argv))
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("bugzinho.Chromaqui")
        except Exception:  # noqa: BLE001
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("Chromaqui")
    app.setOrganizationName("bugzinho")
    ctrl = Controller(app)
    w = ctrl.create_window()
    w.show()
    fade_window(w)
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        w.load_video(sys.argv[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
