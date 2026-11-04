"""Preferências persistentes (QSettings: Registro no Windows, arquivo .ini se CHROMAQUI_SETTINGS)."""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings

from . import IS_BETA, ORG_NAME

DEFAULTS = {"theme": "dark", "lang": "pt-BR", "animations": True, "neon": True, "render": "auto",
            "accent": "", "play_quality": 0, "last_dir": "",
            "crops": "", "crop_margin": 8, "crop_even": False,
            "update_check": True, "update_betas": IS_BETA, "update_skip": "",
            "brush_size": 30, "brush_hardness": 50}


class Settings:
    def __init__(self):
        ini = os.environ.get("CHROMAQUI_SETTINGS")
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
