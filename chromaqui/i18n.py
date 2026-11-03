"""Traduções simples: T("texto em português") -> texto no idioma atual.

As chaves são as frases originais em pt-BR; cada idioma fica em assets/i18n/<código>.json.
Frase sem tradução aparece em português (nunca quebra a interface)."""
from __future__ import annotations

import json
import os

from .paths import asset

DEFAULT = "pt-BR"
LANGUAGES = [
    ("pt-BR", "Português (Brasil)"),
    ("en", "English"),
    ("es", "Español"),
    ("fr", "Français"),
    ("de", "Deutsch"),
    ("it", "Italiano"),
    ("ja", "日本語"),
    ("zh-CN", "简体中文"),
]
_table: dict = {}
_lang = DEFAULT


def lang_file(code):
    return asset("i18n", f"{code}.json")


def set_language(code: str) -> str:
    global _table, _lang
    codes = [c for c, _ in LANGUAGES]
    code = code if code in codes else DEFAULT
    table = {}
    if code != DEFAULT:
        try:
            with open(lang_file(code), encoding="utf-8") as f:
                table = {k: v for k, v in json.load(f).items() if isinstance(v, str) and v and not k.startswith("@")}
        except (OSError, ValueError):
            table = {}
    _table, _lang = table, code
    return code


def language() -> str:
    return _lang


def T(s: str) -> str:
    return _table.get(s, s)


def coverage(code: str, keys) -> float:
    if code == DEFAULT:
        return 1.0
    try:
        with open(lang_file(code), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return 0.0
    keys = list(keys)
    return sum(1 for k in keys if d.get(k)) / max(1, len(keys))
