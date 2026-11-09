"""Chromaqui! — remove o fundo (chroma key) de vídeos e exporta quadros/animações com transparência."""
APP_NAME = "Chromaqui!"
APP_SLUG = "chromaqui"
__version__ = "3.2.0-beta.2"
ORG_NAME = "bugzinho"
URL_REPO = "https://github.com/cleitinhodev/"
URL_SITE = "https://www.bugzinho.com/"
URL_DONATE = "https://www.bugzinho.com/donate"

IS_BETA = any(t in __version__ for t in ("-alpha", "-beta", "-rc"))   # versão de testes (pré-lançamento)
