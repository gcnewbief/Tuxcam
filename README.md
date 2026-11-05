# Tuxcam

A simple, fast webcam viewer and recorder for Linux — built for quickly
filming return/unboxing inspections, but general-purpose.

## Features

- Live preview with device + resolution/fps selection (raw and MJPG modes)
- One-click recording to **MP4** or **MKV** (H.264 + AAC audio)
- **Timestamp overlay** burned into preview, recordings and snapshots —
  useful evidence for disputed returns
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

```bash
./tuxcam.sh                    # dev checkout (uses .venv)
./Tuxcam-x86_64.AppImage       # single-file bundle
./packaging/build_appimage.sh  # rebuild the AppImage
```

## How it works

PySide6 UI + GStreamer 1.0 backend (`python3-gi`). The camera runs one
always-on pipeline (`v4l2src → crop/zoom → videobalance → textoverlay → tee`).
Recording bridges to a separate encoder pipeline via `appsink`/`appsrc`, so
starting/stopping a recording never disturbs the preview and can't deadlock
on pad linking.

## Requirements

System (already satisfied on Ubuntu 24.04): `gstreamer1.0-plugins-good`,
`-bad`, `-ugly`, `-libav`, `python3-gi`, `pactl` for audio device listing.

Python deps live in `.venv` (PySide6). The bundled `.libs/libxcb-cursor0`
is only needed because Qt's xcb plugin wants it — delete `.libs/` if your
distro has `libxcb-cursor0` installed.
