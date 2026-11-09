"""Pastas do usuário por sistema, arquivo de atualização por sistema, ffmpeg executável e configurações
no Linux (python tests/test_platform.py all)."""
import importlib, os, shutil, stat, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from chromaqui import paths, updates, exporters as ex

TMP = tempfile.mkdtemp(prefix="chromaqui_plat_")


def test_paths():
    old = {k: os.environ.get(k) for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "HOME", "APPDATA", "CHROMAQUI_MODELS_DIR")}
    try:
        os.environ.pop("CHROMAQUI_MODELS_DIR", None)
        if paths.IS_WINDOWS:
            os.environ["APPDATA"] = os.path.join(TMP, "roaming")
            assert paths.config_dir() == os.path.join(TMP, "roaming", "Chromaqui")
            assert paths.data_dir() == paths.config_dir()
        else:
            os.environ["HOME"] = os.path.join(TMP, "home")
            os.environ.pop("XDG_CONFIG_HOME", None); os.environ.pop("XDG_DATA_HOME", None)
            assert paths.config_dir() == os.path.join(TMP, "home", ".config", "Chromaqui"), paths.config_dir()
            assert paths.data_dir() == os.path.join(TMP, "home", ".local", "share", "Chromaqui")
            os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg"); os.environ["XDG_DATA_HOME"] = os.path.join(TMP, "dat")
            assert paths.config_dir() == os.path.join(TMP, "cfg", "Chromaqui")
            os.environ["XDG_CONFIG_HOME"] = "relativo/nao/vale"          # XDG exige caminho absoluto
            assert paths.config_dir() == os.path.join(TMP, "home", ".config", "Chromaqui")
            os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg")
        from chromaqui import ai, crashlog
        assert ai.models_dir() == os.path.join(paths.data_dir(), "models"), ai.models_dir()
        saved = os.environ.pop("CHROMAQUI_LOG_DIR", None)
        try:
            assert crashlog.log_dir() == os.path.join(paths.config_dir(), "logs"), crashlog.log_dir()
        finally:
            if saved:
                os.environ["CHROMAQUI_LOG_DIR"] = saved
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    print(f"PASTAS OK ({paths.platform_tag()})")


def test_assets():
    rel = {"assets": [{"name": n, "browser_download_url": "https://x/" + n} for n in (
        "Chromaqui-Windows.zip", "Chromaqui-Windows-onefile.zip",
        "Chromaqui-Linux-x86_64.tar.gz", "Chromaqui-Linux-x86_64.AppImage")]}
    assert updates.pick_asset(rel, "windows") == ("Chromaqui-Windows.zip", "https://x/Chromaqui-Windows.zip")
    assert updates.pick_asset(rel, "linux")[0] == "Chromaqui-Linux-x86_64.AppImage"
    only_tar = {"assets": [a for a in rel["assets"] if a["name"].endswith(".tar.gz")]}
    assert updates.pick_asset(only_tar, "linux")[0] == "Chromaqui-Linux-x86_64.tar.gz"
    assert updates.pick_asset({"assets": rel["assets"][:2]}, "linux") is None      # Release só com Windows
    assert updates.pick_asset({}, "linux") is None and updates.pick_asset(rel, "other") is None
    print("ARQUIVO POR SISTEMA OK (Windows .zip, Linux .AppImage > .tar.gz)")


def test_ffmpeg_exec():
    exe = ex.ffmpeg_exe()
    assert exe and os.path.isfile(exe), exe
    if os.name != "nt":
        assert os.access(exe, os.X_OK), exe
        # binário sem permissão de execução numa pasta somente leitura -> cópia executável no cache
        ro = os.path.join(TMP, "ro"); os.makedirs(ro)
        f = os.path.join(ro, "ffmpeg-teste"); shutil.copy(exe, f); os.chmod(f, 0o644); os.chmod(ro, 0o555)
        old = os.environ.get("XDG_CACHE_HOME"); os.environ["XDG_CACHE_HOME"] = os.path.join(TMP, "cache")
        try:
            got = ex._ensure_exec(f)
            if os.access(f, os.X_OK):           # root consegue dar chmod mesmo em pasta 555
                assert got == f
            else:
                assert got == os.path.join(TMP, "cache", "Chromaqui", "ffmpeg-teste") and os.access(got, os.X_OK), got
        finally:
            os.chmod(ro, 0o755)
            if old is None:
                os.environ.pop("XDG_CACHE_HOME", None)
            else:
                os.environ["XDG_CACHE_HOME"] = old
    print(f"FFMPEG OK ({os.path.basename(exe)})")


def test_settings_location():
    if paths.IS_WINDOWS:
        print("CONFIGURAÇÕES: Registro do Windows (sem mudança)"); return
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv[:1])
    old = {k: os.environ.get(k) for k in ("XDG_CONFIG_HOME", "CHROMAQUI_SETTINGS")}
    try:
        os.environ.pop("CHROMAQUI_SETTINGS", None)
        os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "cfg2")
        QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, os.path.join(TMP, "cfg2"))
        legacy = QSettings("bugzinho", "Chromaqui"); legacy.setValue("theme", "light"); legacy.sync()
        from chromaqui import settings as st
        importlib.reload(st)
        s = st.Settings()
        ini = os.path.join(TMP, "cfg2", "Chromaqui", "Chromaqui.ini")
        assert s.q.fileName() == ini, s.q.fileName()
        assert s.get("theme") == "light"                    # migrado do local antigo
        s.set("lang", "ja"); assert os.path.isfile(ini) and st.Settings().get("lang") == "ja"
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    print("CONFIGURAÇÕES OK (~/.config/Chromaqui/Chromaqui.ini, migração do local antigo)")


if __name__ == "__main__":
    test_paths(); test_assets(); test_ffmpeg_exec(); test_settings_location()
    shutil.rmtree(TMP, ignore_errors=True)
    print("TEST PLATFORM OK")
