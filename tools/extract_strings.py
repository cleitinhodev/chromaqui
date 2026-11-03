"""Lista todas as frases traduzíveis (chaves pt-BR) e confere a cobertura de cada idioma.

    python tools/extract_strings.py            # relatório de cobertura
    python tools/extract_strings.py --template # grava assets/i18n/_template.json
"""
import ast
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def keys():
    out = []
    pkg = os.path.join(ROOT, "chromaqui")
    for fn in sorted(os.listdir(pkg)):
        if not fn.endswith(".py") or fn == "selftest.py":
            continue
        tree = ast.parse(open(os.path.join(pkg, fn), encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "T" and node.args:
                a = node.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    out.append(a.value)
    from chromaqui import core, app, dialogs, exporters, widgets
    for title, items in core.PARAM_SECTIONS:
        out.append(title)
        for _k, label, _lo, _hi, _d, tip in items:
            out.append(label)
            if tip:
                out.append(tip)
    out += [f.label for f in exporters.FORMATS] + app.VIEWS + app.BG_LABELS + [l for _, l in app.BG_MODES]
    out += [n for n, _ in widgets.PLAY_QUALITY] + [l for _, l in dialogs.RENDER_MODES] + list(core.PRESETS)
    seen, res = set(), []
    for k in out:
        if k not in seen:
            seen.add(k)
            res.append(k)
    return res


if __name__ == "__main__":
    ks = keys()
    if "--template" in sys.argv:
        # mantém a ordem existente e acrescenta as frases novas no fim (os .txt numerados continuam válidos)
        tp = os.path.join(ROOT, "assets", "i18n", "_template.json")
        old = list(json.load(open(tp, encoding="utf-8"))) if os.path.exists(tp) else []
        order = old + [k for k in ks if k not in old]
        with open(tp, "w", encoding="utf-8") as f:
            json.dump({k: "" for k in order}, f, ensure_ascii=False, indent=1)
    from chromaqui import i18n
    bad = 0
    for code, name in i18n.LANGUAGES[1:]:
        with open(i18n.lang_file(code), encoding="utf-8") as f:
            d = json.load(f)
        miss = [k for k in ks if not d.get(k)]
        extra = [k for k in d if k not in ks and not k.startswith("@")]
        # placeholders {x} precisam existir na tradução
        ph = [k for k in ks if d.get(k) and set(__import__("re").findall(r"\{\w+\}", k)) !=
              set(__import__("re").findall(r"\{\w+\}", d[k]))]
        print(f"{code:6s} {name:20s} {len(ks) - len(miss)}/{len(ks)}  faltando={len(miss)} sobrando={len(extra)} placeholders_errados={len(ph)}")
        for k in (miss + ph)[:5]:
            print("   -", k[:90])
        bad += len(miss) + len(ph)
    print(len(ks), "frases")
    sys.exit(1 if bad else 0)
