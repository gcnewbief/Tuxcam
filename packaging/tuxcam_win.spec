# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Windows (MSYS2/UCRT64) build of Tuxcam.

Build from an MSYS2 UCRT64 shell:
    ./packaging/build_windows.sh

Produces dist/Tuxcam.exe (onefile). PyInstaller's gi.repository.Gst hook
collects the GStreamer plugins, typelibs and DLL deps itself (into
gst_plugins/ + gi_typelibs/ + gio_modules/); we only exclude libgstlibav —
it drags in ffmpeg's avfilter -> ggml/llama/whisper chain whose static
init aborts the exe on some machines. The recorder then uses fdkaacenc.
"""

import os
import sys

try:
    ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
except NameError:  # not inside a spec eval — assume repo root cwd
    ROOT = os.getcwd()

UCRT = sys.base_prefix.replace("/", "\\")  # C:\msys64\ucrt64

datas = [
    (os.path.join(UCRT, "etc", "fonts"), "etc/fonts"),
    (os.path.join(ROOT, "packaging", "tuxcam.png"), "."),
]

a = Analysis(
    [os.path.join(ROOT, "tuxcam.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=["comtypes", "comtypes.client", "comtypes.GUID"],
    hookspath=[],
    hooksconfig={"gstreamer": {"exclude_plugins": ["libav"]}},
    runtime_hooks=[os.path.join(ROOT, "packaging", "win_runtime_hook.py")],
    excludes=["tkinter", "PyQt5", "PyQt6", "numpy", "pandas", "matplotlib"],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Tuxcam",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # flip to False for the release build
    icon=os.path.join(ROOT, "packaging", "tuxcam.ico")
    if os.path.exists(os.path.join(ROOT, "packaging", "tuxcam.ico"))
    else None,
)
