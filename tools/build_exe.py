"""Gera o Chromaqui.exe com PyInstaller (Windows, ou Linux via Wine) e os .zip de distribuição.

    python tools/build_exe.py              # pasta (onedir)  -> dist/Chromaqui/Chromaqui.exe
    python tools/build_exe.py --onefile    # arquivo único   -> dist1/Chromaqui.exe
    python tools/build_exe.py --both --zip # os dois + Chromaqui-Windows.zip / Chromaqui-Windows-onefile.zip

Inclui assets/ (ícones, traduções) e o ffmpeg do imageio-ffmpeg (WebM/ProRes/WebP/APNG).
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "Chromaqui"
KEEP_QT_LANGS = ("pt_BR", "pt", "en", "es", "fr", "de", "it", "ja", "zh_CN")
EXCLUDES = ["tkinter", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtOpenGL",
            "PySide6.QtPdf", "PySide6.QtWebEngineCore", "matplotlib", "scipy", "IPython"]


def pyinstaller(onefile: bool):
    sep = ";" if os.name == "nt" else ":"
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
            "--name", NAME, "--icon", os.path.join("assets", "icon.ico"),
            "--add-data", f"assets{sep}assets", "--collect-data", "imageio_ffmpeg",
            "--hidden-import", "tifffile"]
    for m in EXCLUDES:
        args += ["--exclude-module", m]
    if onefile:
        args += ["--onefile", "--distpath", "dist1", "--workpath", "build1"]
    else:
        args += ["--onedir", "--distpath", "dist", "--workpath", "build"]
    args.append("run_chromaqui.py")
    print(" ".join(args), flush=True)
    subprocess.check_call(args, cwd=ROOT)


def strip_onedir():
    """Remove o que o programa não usa (~20 MB): renderizador OpenGL por software e traduções do Qt extras."""
    base = os.path.join(ROOT, "dist", NAME)
    removed = 0
    for p in glob.glob(os.path.join(base, "**", "opengl32sw.dll"), recursive=True):
        removed += os.path.getsize(p)
        os.remove(p)
    for p in glob.glob(os.path.join(base, "**", "translations", "*.qm"), recursive=True):
        lang = os.path.basename(p).split("_", 1)[-1].rsplit(".", 1)[0]
        if lang not in KEEP_QT_LANGS:
            removed += os.path.getsize(p)
            os.remove(p)
    print(f"strip: -{removed / 1e6:.1f} MB")


def make_zip(src, out, arc_root):
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        if os.path.isfile(src):
            z.write(src, os.path.join(arc_root, os.path.basename(src)))
        else:
            for d, _, files in os.walk(src):
                for f in files:
                    p = os.path.join(d, f)
                    z.write(p, os.path.join(arc_root, os.path.relpath(p, src)))
        for extra in ("README.md", "LICENSE", "CHANGELOG.md"):
            p = os.path.join(ROOT, extra)
            if os.path.exists(p):
                z.write(p, os.path.join(arc_root, extra))
    print("zip:", out, f"{os.path.getsize(out) / 1e6:.1f} MB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--onefile", action="store_true")
    ap.add_argument("--both", action="store_true")
    ap.add_argument("--zip", action="store_true")
    ap.add_argument("--zip-dir", default=ROOT)
    a = ap.parse_args()
    modes = [False, True] if a.both else [a.onefile]
    for one in modes:
        pyinstaller(one)
        if not one:
            strip_onedir()
    if a.zip:
        if False in modes:
            make_zip(os.path.join(ROOT, "dist", NAME), os.path.join(a.zip_dir, f"{NAME}-Windows.zip"), NAME)
        if True in modes:
            make_zip(os.path.join(ROOT, "dist1", f"{NAME}.exe"),
                     os.path.join(a.zip_dir, f"{NAME}-Windows-onefile.zip"), NAME)
    shutil.rmtree(os.path.join(ROOT, "build"), ignore_errors=True)
    shutil.rmtree(os.path.join(ROOT, "build1"), ignore_errors=True)
