# Porting Tuxcam to Windows — brief for the next session

> **DONE** (2026-11-12). The port is implemented and verified on a
> Surface webcam (enumerate / preview / mp4+aac record / DirectShow
> controls panel / `dist\Tuxcam.exe` build). This file is kept as
> background reading; see AGENTS.md "Windows port (done)" for the
> quirks actually encountered. Original brief follows.

Context: Tuxcam is PySide6 + GStreamer (python3-gi). ~80% of the code is
already platform-neutral; the work is four platform seams + packaging.
Target: `Tuxcam.exe` via PyInstaller.

## Install recipe (Windows)

- Python 3.12 (python.org)
- **GStreamer**: official MSVC installer from gstreamer.freedesktop.org —
  install BOTH `gstreamer-1.0-msvc-x86_64-*.msi` (runtime) and the
  `-devel` package (typelibs + headers needed by PyGObject).
- PyGObject on Windows is painful outside MSYS2. Two paths:
  a) `pip install PyGObject` — wheels exist for recent versions; try first
  b) MSYS2: `pacman -S mingw-w64-ucrt-x86_64-python-gobject
     mingw-w64-ucrt-x86_64-gstreamer mingw-w64-ucrt-x86_64-gst-plugins-*`
     — the reliable fallback; use the MSYS2 Python for everything.
- `pip install PySide6 comtypes pyinstaller`

## Platform seams to build

Create `tuxcam/platform/` with a small factory; engine calls it instead
of hardcoding Linux pieces:

1. **Video source element** — Linux `v4l2src device="/dev/video0"`.
   Windows: `mfvideosrc` (Media Foundation, modern) or `ksvideosrc`
   (kernel streaming, more compatible). Device `device-path` property
   takes the symbolic path from DeviceMonitor (e.g.
   `\\?\usb#vid_...#...#{65e8773d-8f56-11d0-a3b9-00a0c9223196}` —
   store it as the DeviceInfo.path equivalent; it must be escaped/quoted
   in parse_launch — better to set it via set_property after parsing).
2. **Device enumeration** — `Gst.DeviceMonitor` works on Windows and
   returns GstDevice objects; the props giving a usable path differ
   (`device.path` vs `api.v4l2.path` vs `device.name`/serial). Enumerate
   like `list_devices()` but branch by `sys.platform`.
3. **Audio** — `pulsesrc` → `wasapi2src`; source listing via
   DeviceMonitor (audio sources) instead of `pactl`.
4. **Hardware controls** — `v4l2.py` is Linux-only. Windows equivalent:
   DirectShow COM interfaces `IAMVideoProcAmp` (brightness, contrast,
   saturation, WB, gain, backlight, focus mode…) and `IAMCameraControl`
   (exposure, zoom, pan/tilt, iris) via `comtypes`. Same panel can be
   reused: implement `list_controls/get_ctrl/set_ctrl` with identical
   semantics (id, type, min, max, step, default, flags, menu) mapping
   VideoProcAmp/CameraControl enums to synthetic ctrl ids. Auto/manual
   pairs come free via the `*_AUTO` flags the APIs expose.
   Reference: IAMVideoProcAmpRange_* / CameraControlProperty_* docs.

## What needs NO changes

- Recording appsink/appsrc bridge, encoders (x264/aac/mp4/mkv are all in
  the Windows Gst build), zoom/crop, both overlays, snapshot path,
  QSettings persistence, most of window.py.

## Packaging (.exe)

- `pyinstaller --onefile --windowed` on the Windows box. Bundling Gst:
  collect `bin/` (gst plugin DLLs) + `lib/girepository-1.0` typelibs
  + `share/gstreamer-1.0` schemas into the exe via `datas=`, then set
  `GST_PLUGIN_PATH`, `GI_TYPELIB_PATH`, `GST_PLUGIN_SYSTEM_PATH_1_0`,
  `GST_PLUGIN_SCANNER`, `GST_REGISTRY_1_0=%LOCALAPPDATA%...` at runtime
  (mirrors `packaging/build_appimage.sh` AppRun env). PyInstaller's
  `hook-gi.repository.Gst` does some of this; expect manual datas work.
- Icon: `packaging/tuxcam.png` → `tuxcam.ico` for `--icon`.

## Test order on Windows

1. `gst-launch-1.0 mfvideosrc ! autovideosink` — camera sanity
2. `list_devices()` port — sees the cam
3. Preview pipeline (swap source element only)
4. Record one mp4, ffprobe it
5. Controls panel via comtypes backend
6. PyInstaller build → run on a clean account/machine
