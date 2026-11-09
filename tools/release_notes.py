"""Gera as notas da Release a partir da seção da versão no CHANGELOG.md (uso: release_notes.py 3.0.1)."""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ver = sys.argv[1].lstrip("v")
text = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
m = re.search(rf"^## {re.escape(ver)}\b[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
body = m.group(1).strip() if m else "Veja o CHANGELOG.md."
sys.stdout.reconfigure(encoding="utf-8")
if any(t in ver for t in ("-alpha", "-beta", "-rc")):
    print("> 🧪 **Versão de testes (pré-release).** Os recursos novos podem mudar. A versão estável continua\n"
          "> sendo a marcada como **Latest** na página de Releases.\n")
print(f"## Chromaqui! {ver}\n\n{body}\n")
linux = "--linux" in sys.argv or os.environ.get("RELEASE_HAS_LINUX") == "1"
print("""### Download
#### Windows
- **Chromaqui-Windows.zip** — pasta com `Chromaqui.exe` (abre mais rápido; recomendado).
- **Chromaqui-Windows-onefile.zip** — um único `Chromaqui.exe` (demora alguns segundos para abrir).

Descompacte e execute; não precisa instalar. Windows 10/11 64 bits.

> ⚠️ **SmartScreen:** o executável não é assinado, então na primeira execução o Windows pode mostrar
> "O Windows protegeu o computador". Clique em **Mais informações → Executar assim mesmo**.""")
if linux:
    print("""
#### Linux (x86_64, glibc 2.35+ — Ubuntu 22.04+, Debian 12+, Fedora, Arch…)
- **Chromaqui-Linux-x86_64.AppImage** — um arquivo só: `chmod +x Chromaqui-Linux-x86_64.AppImage` e execute.
  Usa o FUSE (comando `fusermount3`, pacote `fuse3`; não precisa do `libfuse2`); sem FUSE: `./Chromaqui-Linux-x86_64.AppImage --appimage-extract-and-run`.
- **Chromaqui-Linux-x86_64.tar.gz** — pasta portátil: `tar xzf …` e rode `Chromaqui/Chromaqui`
  (`./install-desktop.sh` adiciona ao menu de aplicativos).""")
