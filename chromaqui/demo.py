"""Projeto de demonstração (abre ao iniciar): assets/demo/japanese_woman.mp4 (tela verde) sobre o cenário
assets/demo/scenery_shrine.webp, com ajustes prontos e a prévia dividida meio a meio (original | resultado).

Nada daqui é gravado nas preferências: ao abrir outro vídeo ou um projeto novo, tudo volta ao padrão."""
from __future__ import annotations

import os

from . import core
from .paths import asset

VIDEO = "japanese_woman.mp4"
BACKGROUND = "scenery_shrine.webp"
FRAME = 120                    # pose de frente, no centro: a divisória passa no meio da moça
SPLIT = 0.5
BG_MODE = "fill"
# ajustes calibrados para este vídeo: tolerância um pouco maior e pedestal tiram o véu de ~2% de
# alfa que sobrava no fundo verde; o resto (bordas, colorização, spill) fica no padrão.
VALUES = {"tolerance": 28, "pedestal": 6}


def video_path() -> str:
    return asset("demo", VIDEO)


def background_path() -> str:
    return asset("demo", BACKGROUND)


def available() -> bool:
    return os.path.isfile(video_path()) and os.path.isfile(background_path())


def params() -> core.KeyParams:
    p = core.KeyParams()
    p.values.update(VALUES)
    return p


def is_demo_path(path) -> bool:
    try:
        return bool(path) and os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(video_path()))
    except (TypeError, ValueError):
        return False
