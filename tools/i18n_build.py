"""Monta assets/i18n/<idioma>.json a partir de tools/i18n_src/<idioma>.txt ("N|tradução", N = ordem do
_template.json gerado por extract_strings.py). Útil para tradutores: edite o .txt ou o .json direto."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(ROOT, "assets", "i18n", "_template.json")
NAMES = {"en": "English", "es": "Español", "fr": "Français", "de": "Deutsch", "it": "Italiano",
         "ja": "日本語", "zh-CN": "简体中文"}

if __name__ == "__main__":
    keys = list(json.load(open(TEMPLATE, encoding="utf-8")))
    for code in (sys.argv[1:] or NAMES):
        src = os.path.join(ROOT, "tools", "i18n_src", f"{code}.txt")
        tr = {}
        for line in open(src, encoding="utf-8"):
            line = line.rstrip("\n")
            if not line.strip():
                continue
            n, _, t = line.partition("|")
            tr[int(n)] = t
        assert len(tr) == len(keys), (code, len(tr), len(keys))
        out = {"@language": NAMES[code]}
        out.update({k: tr[i + 1] for i, k in enumerate(keys)})
        with open(os.path.join(ROOT, "assets", "i18n", f"{code}.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(code, len(keys))
