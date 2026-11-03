"""Caminhos de recursos (funciona no código-fonte e no .exe do PyInstaller)."""
import os
import sys


def base_dir():
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def asset(*parts):
    return os.path.join(base_dir(), "assets", *parts)
