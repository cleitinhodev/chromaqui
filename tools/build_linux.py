"""Gera o Chromaqui! nativo para Linux (x86_64) com PyInstaller, o AppImage e o .tar.gz portátil.

    python tools/build_linux.py                 # dist/Chromaqui/Chromaqui (pasta)
    python tools/build_linux.py --package       # + Chromaqui-Linux-x86_64.AppImage e Chromaqui-Linux-x86_64.tar.gz

Para máxima compatibilidade, compile numa distribuição antiga (o CI usa ubuntu-22.04, glibc 2.35).
O AppImage usa o appimagetool (baixado automaticamente; ou defina APPIMAGETOOL=/caminho).
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_exe import EXCLUDES, KEEP_QT_LANGS, NAME, ROOT  # noqa: E402

ARCH = "x86_64"
PKG = os.path.join(ROOT, "packaging", "linux")
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
TOOL_URL = "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
# o programa não usa: renderizadores/plataformas extras do Qt (economiza espaço)
DROP_QT_PLUGINS = ("platforms/libqvnc.so", "platforms/libqlinuxfb.so", "platforms/libqvkkhrdisplay.so",
                   "platforms/libqeglfs.so", "platforms/libqminimalegl.so", "egldeviceintegrations",
                   "qmltooling", "designer", "sqldrivers", "wayland-graphics-integration-server")


# Bibliotecas do sistema que NÃO devem ir no pacote (como na "excludelist" do AppImage): sempre existem
# num desktop Linux e versões antigas embutidas quebram drivers de vídeo, fontes e o tema GTK do sistema.
SYSTEM_LIBS = (
    "libstdc++.so", "libgcc_s.so", "libz.so.1", "libexpat.so", "libffi.so",
    "libX11.so", "libX11-xcb.so", "libXau.so", "libXdmcp.so", "libXext.so", "libXrender.so", "libXfixes.so",
    "libXi.so", "libXrandr.so", "libXcursor.so", "libXinerama.so", "libXcomposite.so", "libXdamage.so",
    "libfontconfig.so", "libfreetype.so", "libharfbuzz.so", "libgraphite2.so", "libfribidi.so",
    "libglib-2.0.so", "libgobject-2.0.so", "libgio-2.0.so", "libgmodule-2.0.so", "libgthread-2.0.so",
    "libgtk-3.so", "libgdk-3.so", "libgdk_pixbuf-2.0.so", "libatk-1.0.so", "libatk-bridge-2.0.so",
    "libatspi.so", "libcairo.so", "libcairo-gobject.so", "libpango-1.0.so", "libpangocairo-1.0.so",
    "libpangoft2-1.0.so", "libpixman-1.so", "libepoxy.so", "libcloudproviders.so", "libthai.so",
    "libdatrie.so", "libpcre2-8.so", "libmount.so", "libblkid.so", "libselinux.so", "libsystemd.so",
    "libcap.so", "libdbus-1.so", "libgssapi_krb5.so", "libkrb5.so", "libk5crypto.so", "libkrb5support.so",
    "libkeyutils.so", "libcom_err.so", "libmvec.so", "libatomic.so", "libpng16.so.16", "libjpeg.so.62",
    "libbrotlicommon.so", "libbrotlidec.so", "libbz2.so",
)


def pyinstaller():
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", NAME,
            "--add-data", "assets:assets", "--collect-data", "imageio_ffmpeg",
            "--hidden-import", "tifffile"]
    try:
        import onnxruntime  # noqa: F401
        args += ["--hidden-import", "onnxruntime", "--collect-binaries", "onnxruntime"]
    except ImportError:
        pass
    for m in EXCLUDES:
        args += ["--exclude-module", m]
    args += ["--onedir", "--distpath", "dist", "--workpath", "build", "run_chromaqui.py"]
    print(" ".join(args), flush=True)
    subprocess.check_call(args, cwd=ROOT)


def strip_onedir(base):
    removed = 0
    for p in glob.glob(os.path.join(base, "**", "translations", "*.qm"), recursive=True):
        lang = os.path.basename(p).split("_", 1)[-1].rsplit(".", 1)[0]
        if lang not in KEEP_QT_LANGS:
            removed += os.path.getsize(p)
            os.remove(p)
    plugdirs = glob.glob(os.path.join(base, "**", "Qt", "plugins"), recursive=True)
    for pd in plugdirs:
        for rel in DROP_QT_PLUGINS:
            p = os.path.join(pd, rel)
            if os.path.isdir(p):
                removed += sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(p) for f in fs)
                shutil.rmtree(p)
            elif os.path.isfile(p):
                removed += os.path.getsize(p)
                os.remove(p)
    for p in glob.glob(os.path.join(base, "_internal", "*.so*")):
        n = os.path.basename(p)
        if any(n.startswith(x) for x in SYSTEM_LIBS):
            removed += os.path.getsize(p)
            os.remove(p)
    # o ffmpeg embutido precisa poder ser executado
    for p in glob.glob(os.path.join(base, "**", "imageio_ffmpeg", "binaries", "ffmpeg*"), recursive=True):
        os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"strip: -{removed / 1e6:.1f} MB")
    plats = sorted(os.path.basename(p) for p in glob.glob(os.path.join(base, "**", "platforms", "*.so"), recursive=True))
    print("plataformas Qt:", plats)
    if not any("xcb" in p for p in plats) or not any("wayland" in p for p in plats):
        raise SystemExit("faltam os plugins xcb/wayland do Qt")


def icons_into(dst_root):
    from PIL import Image
    logo = Image.open(os.path.join(ROOT, "assets", "logo.png")).convert("RGBA")
    for s in ICON_SIZES:
        d = os.path.join(dst_root, f"{s}x{s}", "apps")
        os.makedirs(d, exist_ok=True)
        src = os.path.join(ROOT, "assets", "icons", f"icon_{s}.png")
        im = Image.open(src).convert("RGBA") if os.path.exists(src) else logo.resize((s, s), Image.LANCZOS)
        if im.size != (s, s):
            im = im.resize((s, s), Image.LANCZOS)
        im.save(os.path.join(d, "chromaqui.png"), optimize=True)


def _extras(dst):
    for extra in ("README.md", "LICENSE", "CHANGELOG.md"):
        p = os.path.join(ROOT, extra)
        if os.path.exists(p):
            shutil.copy(p, dst)


def make_tar(onedir, out):
    stage = os.path.join(ROOT, "build", "tar", f"{NAME}-Linux-{ARCH}")
    shutil.rmtree(os.path.dirname(stage), ignore_errors=True)
    os.makedirs(stage)
    shutil.copytree(onedir, os.path.join(stage, NAME), symlinks=True)
    shutil.copy(os.path.join(PKG, "chromaqui.desktop"), stage)
    shutil.copy(os.path.join(PKG, "install-desktop.sh"), stage)
    os.chmod(os.path.join(stage, "install-desktop.sh"), 0o755)
    icons_into(os.path.join(stage, "icons", "hicolor"))
    _extras(stage)
    with tarfile.open(out, "w:gz", compresslevel=9) as t:
        t.add(stage, arcname=os.path.basename(stage))
    print("tar:", out, f"{os.path.getsize(out) / 1e6:.1f} MB")


def appimagetool():
    t = os.environ.get("APPIMAGETOOL")
    if t and os.path.isfile(t):
        return t
    t = os.path.join(ROOT, "build", "appimagetool-x86_64.AppImage")
    if not os.path.isfile(t):
        os.makedirs(os.path.dirname(t), exist_ok=True)
        print("baixando appimagetool…", flush=True)
        urllib.request.urlretrieve(TOOL_URL, t)
    os.chmod(t, 0o755)
    return t


def make_appimage(onedir, out):
    app = os.path.join(ROOT, "build", "AppDir")
    shutil.rmtree(app, ignore_errors=True)
    shutil.copytree(onedir, os.path.join(app, "usr", "lib", "chromaqui"), symlinks=True)
    shutil.copy(os.path.join(PKG, "AppRun"), app)
    os.chmod(os.path.join(app, "AppRun"), 0o755)
    os.makedirs(os.path.join(app, "usr", "share", "applications"))
    for d in (app, os.path.join(app, "usr", "share", "applications")):
        shutil.copy(os.path.join(PKG, "chromaqui.desktop"), d)
    icons_into(os.path.join(app, "usr", "share", "icons", "hicolor"))
    shutil.copy(os.path.join(app, "usr", "share", "icons", "hicolor", "256x256", "apps", "chromaqui.png"), app)
    shutil.copy(os.path.join(app, "chromaqui.png"), os.path.join(app, ".DirIcon"))
    env = dict(os.environ, ARCH=ARCH, APPIMAGE_EXTRACT_AND_RUN="1")
    if os.path.exists(out):
        os.remove(out)
    subprocess.check_call([appimagetool(), "--no-appstream", app, out], env=env, cwd=ROOT)
    os.chmod(out, 0o755)
    print("AppImage:", out, f"{os.path.getsize(out) / 1e6:.1f} MB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--package", action="store_true", help="gera também o AppImage e o .tar.gz")
    ap.add_argument("--skip-build", action="store_true", help="reaproveita dist/Chromaqui já compilado")
    ap.add_argument("--out-dir", default=ROOT)
    a = ap.parse_args()
    if not sys.platform.startswith("linux"):
        raise SystemExit("use no Linux (para Windows: tools/build_exe.py)")
    onedir = os.path.join(ROOT, "dist", NAME)
    if not a.skip_build:
        pyinstaller()
        strip_onedir(onedir)
    if a.package:
        make_tar(onedir, os.path.join(a.out_dir, f"{NAME}-Linux-{ARCH}.tar.gz"))
        make_appimage(onedir, os.path.join(a.out_dir, f"{NAME}-Linux-{ARCH}.AppImage"))
    shutil.rmtree(os.path.join(ROOT, "build"), ignore_errors=True)
