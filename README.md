# Tuxcam

A simple, fast webcam viewer and recorder for Linux and Windows — built
for quickly filming return/unboxing inspections, but general-purpose.

## Features

- Live preview with device + resolution/fps selection (raw and MJPG modes)
- One-click recording to **MP4** or **MKV** (H.264 + AAC audio)
- **Timestamp overlay** burned into preview, recordings and snapshots —
  useful evidence for disputed returns
- **Name + order-number label** (Label button → "Show on video") burned
  in top-left; off by default, per-video toggle
- Full-resolution **snapshots** (PNG)
- Audio source picker + live level meter, or record video-only
- Digital zoom (works mid-recording): **scroll wheel** zooms toward the
  pointer, plus −/+ buttons or the slider for centre zoom;
  brightness/contrast/saturation
- **Camera controls panel** (like Guvcview) — auto-discovers whatever the
  device exposes over V4L2: exposure mode/time, white balance, gain,
  backlight compensation, sharpness, anti-flicker, etc. Auto/manual pairs
  lock their dependents, and values persist per device.
- Fullscreen preview (F or double-click)
- Recordings/snapshots land in `~/Videos/Tuxcam` (configurable), named by
  timestamp
- Keyboard shortcuts: **R** record, **S** snapshot, **F** fullscreen,
  **Esc** exit fullscreen

## Run

Linux:

```bash
./tuxcam.sh                    # dev checkout (uses .venv)
./Tuxcam-x86_64.AppImage       # single-file bundle
./packaging/build_appimage.sh  # rebuild the AppImage
```

Windows (MSYS2 UCRT64 — see setup below):

```bat
tuxcam.bat                            :: dev checkout
packaging\build_windows.sh            :: rebuild dist\Tuxcam.exe (run in MSYS2 bash)
```

## Windows setup

PyGObject has no Windows wheels, so the whole stack comes from MSYS2:

```bash
# in an MSYS2 (msys2.org) UCRT64 shell:
pacman -S --needed \
  mingw-w64-ucrt-x86_64-python mingw-w64-ucrt-x86_64-python-gobject \
  mingw-w64-ucrt-x86_64-python-comtypes mingw-w64-ucrt-x86_64-pyside6 \
  mingw-w64-ucrt-x86_64-gstreamer \
  mingw-w64-ucrt-x86_64-gst-plugins-base mingw-w64-ucrt-x86_64-gst-plugins-good \
  mingw-w64-ucrt-x86_64-gst-plugins-bad mingw-w64-ucrt-x86_64-gst-plugins-ugly \
  mingw-w64-ucrt-x86_64-gst-libav \
  mingw-w64-ucrt-x86_64-pyinstaller mingw-w64-ucrt-x86_64-ntldd
```

Then `tuxcam.bat` runs the app straight from the checkout, and
`packaging/build_windows.sh` produces a standalone `dist/Tuxcam.exe`
(~110 MB onefile; no MSYS2 needed on the target machine).

## How it works

PySide6 UI + GStreamer 1.0 backend (`python3-gi`). The camera runs one
always-on pipeline (`<source> → caps → crop/zoom → videobalance →
textoverlay → tee`). Recording bridges to a separate encoder pipeline via
`appsink`/`appsrc`, so starting/stopping a recording never disturbs the
preview and can't deadlock on pad linking.

Platform-specific bits are isolated in `tuxcam/backend.py`: the video
source is created via `GstDevice.create_element()` (v4l2src on Linux,
mfvideosrc/ksvideosrc on Windows), audio is pulsesrc on Linux and
wasapi2src on Windows, and hardware camera controls go through V4L2
ioctls (`tuxcam/v4l2.py`) or DirectShow COM (`tuxcam/win_controls.py`).

## Requirements

Linux system packages (already satisfied on Ubuntu 24.04):
`gstreamer1.0-plugins-good`, `-bad`, `-ugly`, `-libav`, `python3-gi`,
`pactl` for audio device listing.

Python deps live in `.venv` (PySide6). The bundled `.libs/libxcb-cursor0`
is only needed because Qt's xcb plugin wants it — delete `.libs/` if your
distro has `libxcb-cursor0` installed.
