#!/usr/bin/env bash
# Build Tuxcam.exe — run inside an MSYS2 UCRT64 shell (or any shell where
# the env below resolves).
#
# Required pacman packages:
#   mingw-w64-ucrt-x86_64-python{,-gobject,-pip,-comtypes}
#   mingw-w64-ucrt-x86_64-pyside6 mingw-w64-ucrt-x86_64-pyinstaller
#   mingw-w64-ucrt-x86_64-ntldd
#   mingw-w64-ucrt-x86_64-gstreamer mingw-w64-ucrt-x86_64-gst-plugins-{base,good,bad,ugly}
#   mingw-w64-ucrt-x86_64-gst-libav
set -euo pipefail
cd "$(dirname "$0")/.."

PY=/ucrt64/bin/python.exe
[ -x "$PY" ] || PY="$(command -v python)"

# mingw python derives home from USERPROFILE — absent under MSYS2 bash
export USERPROFILE="${USERPROFILE:-$(cygpath -u "$HOME" 2>/dev/null || echo "$HOME")}"
export HOME="${HOME:-$(cygpath -u "$USERPROFILE" 2>/dev/null || echo "$USERPROFILE")}"

# packaging/tuxcam.ico is optional — the spec falls back to no icon
"$PY" -m PyInstaller --noconfirm --clean \
    --distpath dist --workpath build \
    packaging/tuxcam_win.spec
echo "==> dist/Tuxcam.exe"
