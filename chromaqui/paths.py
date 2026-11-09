"""Caminhos de recursos (funciona no código-fonte e no executável do PyInstaller) e pastas do usuário.

Pastas do usuário:
    Windows: %APPDATA%\\Chromaqui\\(logs, models)
    Linux:   $XDG_CONFIG_HOME/Chromaqui (ou ~/.config/Chromaqui) -> configurações e logs/
             $XDG_DATA_HOME/Chromaqui/models (ou ~/.local/share/Chromaqui/models) -> modelos de IA
"""
import os
import sys

IS_WINDOWS = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")


def base_dir():
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def asset(*parts):
    return os.path.join(base_dir(), "assets", *parts)


def _xdg(var, default):
    v = os.environ.get(var, "")
    return v if os.path.isabs(v) else os.path.join(os.path.expanduser("~"), default)


def config_dir() -> str:
    """Pasta de configuração/logs do usuário (não cria)."""
    if IS_WINDOWS:
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Chromaqui")
    return os.path.join(_xdg("XDG_CONFIG_HOME", ".config"), "Chromaqui")


def data_dir() -> str:
    """Pasta de dados grandes (modelos de IA). No Windows continua em %APPDATA%\\Chromaqui."""
    if IS_WINDOWS:
        return config_dir()
    return os.path.join(_xdg("XDG_DATA_HOME", os.path.join(".local", "share")), "Chromaqui")


def platform_tag() -> str:
    """'windows', 'linux' ou 'other' (para escolher o arquivo certo nas atualizações)."""
    return "windows" if IS_WINDOWS else "linux" if IS_LINUX else "other"
