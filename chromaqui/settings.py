"""Preferências persistentes (QSettings: Registro no Windows, arquivo .ini se CHROMAQUI_SETTINGS)."""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings

from . import ORG_NAME
from .paths import IS_WINDOWS, config_dir

DEFAULTS = {"theme": "dark", "lang": "pt-BR", "animations": True, "neon": True, "render": "auto",
            "accent": "", "play_quality": 0, "last_dir": "",
            "crops": "", "crop_margin": 8, "crop_even": False}


def _migrate_native(ini):
    """Linux: copia as preferências do local antigo (~/.config/bugzinho/Chromaqui.conf) uma única vez."""
    if os.path.exists(ini):
        return
    try:
        os.makedirs(os.path.dirname(ini), exist_ok=True)
        old = QSettings(ORG_NAME, "Chromaqui")
        keys = old.allKeys()
        if keys:
            new = QSettings(ini, QSettings.IniFormat)
            for k in keys:
                new.setValue(k, old.value(k))
            new.sync()
    except Exception:  # noqa: BLE001
        pass


class Settings:
    def __init__(self):
        ini = os.environ.get("CHROMAQUI_SETTINGS")
        if not ini and not IS_WINDOWS:
            ini = os.path.join(config_dir(), "Chromaqui.ini")
            _migrate_native(ini)
        self.q = QSettings(ini, QSettings.IniFormat) if ini else QSettings(ORG_NAME, "Chromaqui")

    def get(self, key):
        d = DEFAULTS.get(key)
        v = self.q.value(key, d)
        if isinstance(d, bool):
            return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes")
        if isinstance(d, int):
            try:
                return int(v)
            except (TypeError, ValueError):
                return d
        return "" if v is None else str(v)

    def set(self, key, value):
        self.q.setValue(key, value)
        self.q.sync()
