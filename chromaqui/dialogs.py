"""Diálogos: Sobre e Configurações."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QVBoxLayout)

from . import APP_NAME, URL_DONATE, URL_REPO, URL_SITE, __version__, gpu
from .fx import set_neon, FX
from .widgets import GradientTitle
from .i18n import LANGUAGES, T
from .paths import asset

RENDER_MODES = [("auto", "Automático"), ("cpu", "CPU"), ("gpu", "GPU (OpenCL)")]


def app_icon():
    return QIcon(asset("icon.ico"))


def logo_pixmap(n, widget=None):
    """Logo em alta qualidade (assets/logo.png reduzido com suavização, nítido em telas HiDPI)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    dpr = widget.devicePixelRatioF() if widget is not None else 1.0
    pm = QPixmap(asset("logo.png"))
    if pm.isNull():
        return app_icon().pixmap(n, n)
    pm = pm.scaled(int(n * dpr), int(n * dpr), Qt.KeepAspectRatio, Qt.SmoothTransformation)
    pm.setDevicePixelRatio(dpr)
    return pm


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(T("Sobre o {app}").format(app=APP_NAME))
        self.setWindowIcon(app_icon())
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(logo_pixmap(112, self))
        ic.setFixedSize(104, 104)
        ic.setAlignment(Qt.AlignCenter)
        top.addWidget(ic)
        col = QVBoxLayout()
        self.title = GradientTitle(APP_NAME)
        col.addWidget(self.title)
        ver = QLabel(T("Versão {v}").format(v=__version__))
        ver.setObjectName("appVersion")
        col.addWidget(ver)
        desc = QLabel(T("Remova o fundo verde ou azul (chroma key) de vídeos e exporte quadros e animações "
                        "com transparência: PNG, GIF, WebP, APNG, WebM e ProRes."))
        desc.setWordWrap(True)
        col.addWidget(desc)
        top.addLayout(col, 1)
        lay.addLayout(top)
        self.links = QLabel(
            f'<p style="line-height:150%">'
            f'<b>{T("Repositório")}:</b> <a href="{URL_REPO}">{URL_REPO}</a><br>'
            f'<b>{T("Site")}:</b> <a href="{URL_SITE}">{URL_SITE}</a><br>'
            f'<b>{T("Doar")}:</b> <a href="{URL_DONATE}">{URL_DONATE}</a></p>')
        self.links.setTextFormat(Qt.RichText)
        self.links.setOpenExternalLinks(True)
        self.links.setTextInteractionFlags(Qt.TextBrowserInteraction)
        lay.addWidget(self.links)
        lic = QLabel(T("Software livre sob a licença MIT."))
        lic.setObjectName("muted")
        lay.addWidget(lic)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Close).setText(T("Fechar"))
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        set_neon(self.title, FX.neon, 16)


class SettingsDialog(QDialog):
    """Preferências — as mudanças valem na hora (o idioma recria a janela mantendo o trabalho)."""

    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        s = ctrl.settings
        self.setWindowTitle(T("Configurações"))
        self.setWindowIcon(app_icon())
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)

        g1 = QGroupBox(T("Aparência"))
        f1 = QFormLayout(g1)
        self.cmb_theme = QComboBox()
        self.cmb_theme.addItem(T("Escuro"), "dark")
        self.cmb_theme.addItem(T("Claro"), "light")
        self.cmb_theme.setCurrentIndex(0 if s.get("theme") == "dark" else 1)
        f1.addRow(T("Tema"), self.cmb_theme)
        self.cmb_lang = QComboBox()
        for code, name in LANGUAGES:
            self.cmb_lang.addItem(name, code)
        self.cmb_lang.setCurrentIndex(max(0, [c for c, _ in LANGUAGES].index(s.get("lang"))
                                          if s.get("lang") in [c for c, _ in LANGUAGES] else 0))
        self.cmb_lang.setToolTip(T("O idioma muda na hora; o vídeo e os ajustes são mantidos."))
        f1.addRow(T("Idioma"), self.cmb_lang)
        self.chk_anim = QCheckBox(T("Animações (abrir/fechar seções, transições, esmaecer)"))
        self.chk_anim.setChecked(s.get("animations"))
        f1.addRow(self.chk_anim)
        self.chk_neon = QCheckBox(T("Brilho neon nos destaques"))
        self.chk_neon.setChecked(s.get("neon"))
        f1.addRow(self.chk_neon)
        lay.addWidget(g1)

        g2 = QGroupBox(T("Desempenho"))
        f2 = QFormLayout(g2)
        self.cmb_render = QComboBox()
        for k, label in RENDER_MODES:
            self.cmb_render.addItem(T(label), k)
        keys = [k for k, _ in RENDER_MODES]
        self.cmb_render.setCurrentIndex(keys.index(s.get("render")) if s.get("render") in keys else 0)
        self.cmb_render.setToolTip(T("Automático: usa a placa de vídeo (OpenCL) se houver e passar no teste; "
                                     "senão, a CPU. O resultado é o mesmo; muda só a velocidade."))
        f2.addRow(T("Renderização"), self.cmb_render)
        self.lbl_backend = QLabel()
        self.lbl_backend.setWordWrap(True)
        self.lbl_backend.setObjectName("muted")
        f2.addRow(T("Em uso"), self.lbl_backend)
        lay.addWidget(g2)
        self._update_backend()

        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Close).setText(T("Fechar"))
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self.cmb_theme.currentIndexChanged.connect(lambda: ctrl.set_theme(self.cmb_theme.currentData()))
        self.cmb_lang.currentIndexChanged.connect(self._lang)
        self.chk_anim.toggled.connect(lambda on: ctrl.set_fx(animations=on))
        self.chk_neon.toggled.connect(lambda on: ctrl.set_fx(neon=on))
        self.cmb_render.currentIndexChanged.connect(self._render)

    def _lang(self):
        self.accept()
        self.ctrl.set_language(self.cmb_lang.currentData())

    def _render(self):
        self.ctrl.set_render(self.cmb_render.currentData())
        self._update_backend()

    def _update_backend(self):
        self.lbl_backend.setText(backend_text())


def backend_text():
    st = gpu.status()
    if st["enabled"]:
        return T("GPU (OpenCL): {dev}").format(dev=st["device"])
    reason = st.get("reason") or ""
    reasons = {"CPU escolhida": T("CPU escolhida"), "OpenCL indisponível": T("OpenCL indisponível"),
               "nenhum dispositivo OpenCL utilizável": T("nenhum dispositivo OpenCL utilizável"),
               "teste de conferência falhou": T("teste de conferência falhou")}
    if reason.startswith("sem placa de vídeo OpenCL"):
        r = T("sem placa de vídeo OpenCL")
    else:
        r = reasons.get(reason, reason)
    return T("CPU") + (f" — {r}" if r and reason != "CPU escolhida" else "")
