"""Registro de erros e travamentos: grava em %APPDATA%/Chromaqui/logs (Windows) e mostra um aviso
em vez de o programa fechar em silêncio."""
from __future__ import annotations

import datetime
import faulthandler
import os
import sys
import threading
import time
import traceback

_state = {"dir": None, "fault": None, "last_dialog": 0.0, "installed": False}


def log_dir() -> str:
    d = os.environ.get("CHROMAQUI_LOG_DIR")
    if not d:
        from .paths import config_dir
        d = os.path.join(config_dir(), "logs")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        import tempfile
        d = os.path.join(tempfile.gettempdir(), "Chromaqui", "logs")
        os.makedirs(d, exist_ok=True)
    return d


def error_log_path() -> str:
    return os.path.join(_state["dir"] or log_dir(), "erros.log")


def crash_log_path() -> str:
    return os.path.join(_state["dir"] or log_dir(), "travamento.log")


def _write(text: str):
    try:
        with open(error_log_path(), "a", encoding="utf-8") as fh:
            fh.write(f"\n===== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} =====\n{text}\n")
    except Exception:  # noqa: BLE001
        pass
    if sys.stderr is not None:
        try:
            sys.stderr.write(text + "\n")
        except Exception:  # noqa: BLE001
            pass


def log_exception(where: str = "", exc_info=None):
    et, ev, tb = exc_info or sys.exc_info()
    _write((where + ":\n" if where else "") + "".join(traceback.format_exception(et, ev, tb)))


def _show_dialog(et, ev):
    """Mostra o erro (só na thread da interface, no máximo 1 aviso a cada 3 s)."""
    try:
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance()
        if app is None or QThread.currentThread() is not app.thread():
            return
        if os.environ.get("CHROMAQUI_NO_ERROR_DIALOG") or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            return
        now = time.monotonic()
        if now - _state["last_dialog"] < 3:
            return
        _state["last_dialog"] = now
        from .i18n import T
        QMessageBox.critical(None, "Chromaqui!",
                             T("Ocorreu um erro inesperado:") + f"\n\n{et.__name__}: {ev}\n\n"
                             + T("Detalhes salvos em:") + f"\n{error_log_path()}")
    except Exception:  # noqa: BLE001
        pass


def _excepthook(et, ev, tb):
    if issubclass(et, KeyboardInterrupt):
        sys.__excepthook__(et, ev, tb)
        return
    log_exception("Erro não tratado", (et, ev, tb))
    _show_dialog(et, ev)


def _thread_hook(args):
    if args.exc_type is SystemExit:
        return
    log_exception(f"Erro na thread {getattr(args.thread, 'name', '?')}", (args.exc_type, args.exc_value,
                                                                           args.exc_traceback))


def _qt_message(mode, ctx, msg):
    from PySide6.QtCore import QtMsgType
    if "propagateSizeHints" in msg:
        return
    if mode in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg) or "QThread" in msg:
        _write(f"Qt: {msg}")
    elif sys.stderr is not None:
        try:
            sys.stderr.write(msg + "\n")
        except Exception:  # noqa: BLE001
            pass


def install(qt_messages: bool = True):
    """Instala: sys.excepthook, threading.excepthook, faulthandler (travamentos nativos) e mensagens do Qt."""
    if _state["installed"]:
        return
    _state["installed"] = True
    _state["dir"] = log_dir()
    sys.excepthook = _excepthook
    threading.excepthook = _thread_hook
    for pth in (crash_log_path(), error_log_path()):     # não deixa os logs crescerem sem limite
        try:
            if os.path.getsize(pth) > 1_000_000:
                os.replace(pth, pth + ".old")
        except OSError:
            pass
    try:
        f = open(crash_log_path(), "a", encoding="utf-8")
        f.write(f"\n===== início {datetime.datetime.now():%Y-%m-%d %H:%M:%S} (pid {os.getpid()}) =====\n")
        f.flush()
        faulthandler.enable(f, all_threads=True)
        _state["fault"] = f
    except Exception:  # noqa: BLE001
        pass
    if qt_messages:
        try:
            from PySide6.QtCore import qInstallMessageHandler
            qInstallMessageHandler(_qt_message)
        except Exception:  # noqa: BLE001
            pass
