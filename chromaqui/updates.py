"""Verificação de atualizações (GitHub Releases). Sem bloquear a interface; falhas de rede são
silenciosas. Usa urllib (o executável não inclui o QtNetwork)."""
from __future__ import annotations

import json
import re
import urllib.request

REPO = "cleitinhodev/chromaqui"
API = f"https://api.github.com/repos/{REPO}/releases?per_page=20"
PAGE = f"https://github.com/{REPO}/releases"
_STAGES = {"alpha": 0, "a": 0, "beta": 1, "b": 1, "rc": 2}


def parse_version(v: str):
    """'3.2.0-beta.1' -> (3, 2, 0, 1, 1); estável > rc > beta > alpha."""
    v = str(v).strip().lstrip("vV")
    m = re.match(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-.]?([A-Za-z]+)\.?(\d*))?", v)
    if not m:
        return (0, 0, 0, -1, 0)
    a, b, c = (int(x or 0) for x in m.group(1, 2, 3))
    st = m.group(4)
    if st:
        return (a, b, c, _STAGES.get(st.lower(), 0), int(m.group(5) or 0))
    return (a, b, c, 9, 0)


def is_prerelease(v: str) -> bool:
    return parse_version(v)[3] < 9


def pick_update(releases, current: str, include_betas: bool):
    """Release mais nova que `current` (dict da API do GitHub) ou None."""
    cur = parse_version(current)
    best, best_v = None, cur
    for r in releases or []:
        if not isinstance(r, dict) or r.get("draft"):
            continue
        tag = r.get("tag_name") or ""
        pre = bool(r.get("prerelease")) or is_prerelease(tag)
        if pre and not include_betas:
            continue
        v = parse_version(tag)
        if v > best_v:
            best, best_v = r, v
    return best


def check(current: str, include_betas: bool, url: str = API, timeout: float = 6.0, raise_errors=False):
    """{"version", "url", "prerelease", "name"} se houver versão nova; None caso contrário ou em erro
    (raise_errors=True: repassa o erro, para a verificação manual mostrar a falha)."""
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": "Chromaqui-update-check"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        rel = pick_update(data, current, include_betas)
        if rel is None:
            return None
        tag = rel.get("tag_name", "")
        return {"version": tag.lstrip("vV"), "url": rel.get("html_url") or PAGE,
                "prerelease": bool(rel.get("prerelease")) or is_prerelease(tag), "name": rel.get("name") or tag}
    except Exception:
        if raise_errors:
            raise
        return None
