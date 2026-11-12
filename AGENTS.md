# Tuxcam — agent notes

Webcam viewer/recorder for Linux + Windows, aimed at filming
return/unboxing inspections. PySide6 UI + GStreamer backend via
`python3-gi`.

## Run

```bash
./tuxcam.sh            # GUI (needs DISPLAY; sets LD_LIBRARY_PATH for .libs/)
QT_QPA_PLATFORM=offscreen .venv/bin/python tuxcam.py   # headless testing
```

## Environment quirks (this machine)

- `.venv` was created **without pip** (`python3-venv`/`ensurepip` absent);
  pip was bootstrapped via get-pip.py. It has `system-site-packages`
  enabled so `gi`/GStreamer bindings are visible — keep that flag.
- `.libs/libxcb-cursor0` is an extracted system lib — Qt's xcb plugin
  fails without it. `tuxcam.sh` prepends it to `LD_LIBRARY_PATH`.
- `v4l2-ctl`, `xdotool`, `uv`, `virtualenv` are NOT installed.
  V4L2 control goes through `tuxcam/v4l2.py` (direct ioctls).
- Camera: UGREEN Camera on `/dev/video0` (`/dev/video1` is a metadata
  node — filtered out). `pactl` is used for audio source listing.

## Architecture

- `tuxcam/engine.py` — one always-on pipeline:
  `v4l2src → caps → (jpegdec) → videoconvert → videocrop(zoom) →
  videobalance → textoverlay → tee → appsink(preview)`.
  Recording = separate pipeline fed by `appsrc`, pumped from permanent
  leaky `appsink` taps on the tees; EOS via `appsrc.end_of_stream()`.
  **Do NOT attach mux branches to the live tee dynamically** — pad
  juggling deadlocks `GstAggregator` muxers and corrupts MP4s. This was
  the cause of multiple past bugs; keep the appsink/appsrc design.
- `tuxcam/window.py` — all UI incl. hardware-controls panel built from
  `v4l2.list_controls()`; per-device values persist in QSettings under
  `hw/<devpath>/<ctrlname>`.
- `tuxcam/v4l2.py` — VIDIOC_QUERYCTRL/G_CTRL/S_CTRL ioctls; multiple
  opens of the device are allowed for controls, works while streaming.
- Zoom: `videocrop` left/right/top/bottom updated live (renegotiates
  automatically). `_focus` anchors wheel-zoom to the first pointer
  position of a gesture; reset when zoom returns to 1.0.

## Testing

- Always `QT_QPA_PLATFORM=offscreen` + drive with `QTimer.singleShot`.
- **Always call `engine.stop()` before exit** — dropping PLAYING
  GStreamer elements at GC time segfaults.
- A running GUI holds `/dev/video0`; tests will fail with
  "Device busy" — kill the GUI first. Careful: `pkill -f tuxcam`
  in a `bash -c` command kills the wrapper shell itself (its own
  cmdline matches). Kill by PID from `wmctrl -lp`.
- Validate recordings with `ffprobe` — `ftyp`/`moov` presence is NOT
  proof of validity; check `codec_name`, dimensions, duration.

## GI/GStreamer gotchas hit before

- `GstValueList`/fractions can't be unboxed via `get_value`/`get_nth` —
  enumerate framerates by fixating caps against candidate rates.
- `GstVideo.VideoInfo.from_caps()` returns `(bool, info)` — parse
  width/height from sample caps and derive stride from buffer size.
- `iterate_pads()` returns a GI `Iterator` — loop `.next()`, don't
  iterate it as a Python iterable.
- Pull preview frames via `QTimer` + `try-pull-sample` — `new-sample`
  callbacks cross into Qt from streaming threads and corrupt the heap.

## AppImage build

```bash
./packaging/build_appimage.sh   # → Tuxcam-x86_64.AppImage (~178M)
```

- AppDir at `appimage-build/Tuxcam.AppDir` (gitignored, inspect it to debug)
- Bundles python3.12 + stdlib, PySide6 (QtCore/Gui/Widgets only — the
  prune list in the script drops WebEngine/QML/Multimedia/etc.),
  PyGObject, all Gst plugins, typelibs, ldd-closure of system libs,
  and `.libs/libxcb-cursor`.
- Host still provides: glibc, X11/Mesa GL stack (deliberately excluded —
  bundling those breaks portability rather than helping), fonts,
  and kernel-level bits (/dev/video*, pulse socket).
- AppRun sets `GST_PLUGIN_*`, `GST_PLUGIN_SCANNER`, `GI_TYPELIB_PATH`,
  `PYTHONHOME`, `PYTHONPATH`, `LD_LIBRARY_PATH`. Registry goes to
  `~/.cache/tuxcam-gst-registry.bin` (AppImage mount is read-only).
- appimagetool downloads itself + type2-runtime on first run (needs net).

## Repo notes

- `.venv/`, `__pycache__/`, `*.pyc` are gitignored. `.libs/` is
  intentionally not ignored (needed to launch on machines without
  `libxcb-cursor0`; safe to delete where it's installed).

## Windows port (done)

- Stack: MSYS2 UCRT64 at `C:\msys64` — python, `python-gobject`,
  `python-comtypes`, `pyside6`, `gstreamer` + all plugin sets,
  `pyinstaller`, `ntldd` come from pacman. `pip install` into ucrt64
  python is blocked (PEP 668) and PyPI wheels won't match anyway
  (`mingw_x86_64_ucrt_gnu` platform tag ≠ `win_amd64`) — use pacman.
  `tuxcam.bat` launches `ucrt64\bin\python.exe tuxcam.py`.
- `tuxcam/backend.py` — all platform seams: `GstDevice.create_element()`
  produces the configured source element for both OSes (no per-platform
  property names needed). `controls` re-exports v4l2.py or
  win_controls.py.
- `Gst.DeviceMonitor` providers enumerate **asynchronously** —
  `get_devices()` right after `start()` misses devices; we sleep 0.8s.
  Windows props: video uses `device.path`, wasapi2 audio uses `device.id`.
- Windows dedupe: ks/mf/dshow providers can each report one camera —
  `device_key()` collapses on the PnP instance id; `device_priority()`
  prefers ksvideosrc > mfvideosrc > dshowvideosrc. On the Surface box
  only mf reports the cam.
- `tuxcam/win_controls.py` — DirectShow via comtypes: binds the camera
  moniker a second time and talks `IAMVideoProcAmp`/`IAMCameraControl`;
  works mid-stream. Ctrl ids encode iface/prop/auto; real flag bits are
  detected per-property from GetRange caps (drivers disagree on
  0x10/0x20 vs 0x1/0x2). `ctypes.COMError` is NOT an OSError subclass.
- filesink `location` is set via `set_property` after parse_launch —
  embedding a `C:\...` path in the launch string eats backslashes.
- AAC encoder fallback chain: `avenc_aac` → `fdkaacenc` → `voaacenc`
  (fdk-aac isn't in Ubuntu repos, so avenc stays first for Linux).
- `packaging/build_windows.sh` → PyInstaller onefile `dist/Tuxcam.exe`
  (~110 MB). The builtin `gi.repository.Gst` hook collects
  plugins/typelibs/deps itself — do NOT also bundle bin/ or lib/
  manually (duplicate glib copies → type-registration crash on start).
  gstlibav is excluded via hooksconfig (avfilter pulls ggml/llama
  DLLs that abort on load). `USERPROFILE` must be exported under msys2
  bash or pathlib.Path.home() dies inside PyInstaller.
- Verified on Surface Camera Front: enumerate, 720p preview, mp4 record
  (h264+aac), controls panel (brightness…exposure via DirectShow).
