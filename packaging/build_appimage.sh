#!/usr/bin/env bash
# Build Tuxcam-x86_64.AppImage
# Bundles: python3.12 + stdlib, pruned PySide6, PyGObject, all GStreamer
# plugins, GI typelibs, and the ldd-closure of every library they need.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/appimage-build"
APPDIR="$BUILD/Tuxcam.AppDir"
SYSLIB=/usr/lib/x86_64-linux-gnu
SP="$ROOT/.venv/lib/python3.12/site-packages"
APPLIB="$APPDIR/usr/lib/x86_64-linux-gnu"

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/app" "$APPDIR/usr/pyapp" "$APPLIB" \
         "$APPDIR/usr/libexec" "$APPDIR/usr/lib/python3.12"

echo "== python =="
cp /usr/bin/python3.12 "$APPDIR/usr/bin/"
cp -a /usr/lib/python3.12/. "$APPDIR/usr/lib/python3.12/"
rm -rf "$APPDIR/usr/lib/python3.12"/{test,idlelib,tkinter,turtledemo,ensurepip,lib2to3,pydoc_data}
find "$APPDIR/usr/lib/python3.12" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

echo "== python packages =="
cp -a /usr/lib/python3/dist-packages/gi "$APPDIR/usr/pyapp/"
cp -a "$SP/PySide6" "$APPDIR/usr/pyapp/"
cp -a "$SP/shiboken6" "$APPDIR/usr/pyapp/"
find "$APPDIR/usr/pyapp" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

# prune PySide6: we import only QtCore/QtGui/QtWidgets — drop every other
# extension module, type stubs, and the heavy unused Qt libs
PS="$APPDIR/usr/pyapp/PySide6"
find "$PS" -maxdepth 1 -name "Qt*.abi3.so" ! -name "QtCore.abi3.so" \
     ! -name "QtGui.abi3.so" ! -name "QtWidgets.abi3.so" -delete
find "$PS" -name "*.pyi" -delete
rm -rf "$PS"/{QtAsyncio,scripts,support,include,typesystems,_config.pyi}
rm -rf "$PS"/Qt/{qml,translations,resources,metatypes,libexec,qsci,examples,doc,include,bin}
QTLIB="$PS/Qt/lib"
rm -f "$QTLIB"/libQt6{WebEngine*,Pdf*,Quick*,Qml*,Multimedia*,Designer*,ShaderTools*,Quick3D*,RemoteObjects*,WebSockets*,WebChannel*,WebView*,Charts*,DataVisualization*,SpatialAudio*,TextToSpeech*,Scxml*,Sensors*,SerialPort*,Bluetooth*,Nfc*,Positioning*,Location*,NetworkAuth*,Help*,UiTools*,Test*,Concurrent*,Sql*,OpenGL*,PrintSupport*,Grpc*,Protobuf*,HttpServer*,Labs*,StateMachine*,SvgWidgets*,Svg*}*
rm -f "$QTLIB"/lib{avcodec,avformat,avutil,swresample,swscale}*

echo "== gstreamer =="
cp -a "$SYSLIB"/libgst*.so* "$APPLIB/"
cp -a "$SYSLIB/gstreamer-1.0" "$APPLIB/"
cp "$SYSLIB/gstreamer1.0/gstreamer-1.0/gst-plugin-scanner" "$APPDIR/usr/libexec/"
cp -a "$SYSLIB/girepository-1.0" "$APPLIB/"

echo "== app code =="
cp -a "$ROOT/tuxcam" "$APPDIR/usr/app/"
cp "$ROOT/tuxcam.py" "$APPDIR/usr/app/"
find "$APPDIR/usr/app" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

echo "== bundled extras =="
# libxcb-cursor isn't installed system-wide — we carry it in .libs/
cp -a "$ROOT/.libs"/libxcb-cursor.so* "$APPLIB/" 2>/dev/null || true

echo "== shared library closure =="
# glibc, loader, and the X11/Mesa stack stay on the host (AppImage norm).
EXCLUDE='ld-linux|linux-vdso|libc\.so|libm\.so|libdl\.|libpthread|librt\.|libresolv|libnsl|libnss_|libutil|libthread_db|libBrokenLocale|libanl|libX11|libXext|libXi\.|libXrender|libXrandr|libXfixes|libXcursor|libXdamage|libXinerama|libxcb\.so|libXau|libXdmcp|libGL\.|libEGL|libGLX|libGLdispatch|libOpenGL|libglapi|libdrm|libgbm|libwayland|libmvec'

declare -A done_map
collect() {
    local f="$1"
    local soname dep
    while IFS= read -r line; do
        soname="${line%% *}"
        dep="$(echo "$line" | grep -oE '/[^ ]+' | head -1)" || true
        [ -z "$dep" ] && continue
        [ -n "${done_map[$soname]:-}" ] && continue
        done_map[$soname]=1
        if echo "$soname" | grep -qE "$EXCLUDE"; then
            continue
        fi
        cp -L "$dep" "$APPLIB/$soname"
        collect "$dep"
    done < <(ldd "$f" 2>/dev/null | grep '=>' || true)
}

while IFS= read -r f; do
    collect "$f"
done < <(find "$APPDIR" -name "*.so*" -o -name "python3.12" -o -name "gst-plugin-scanner" | sort)

echo "== consistency check =="
export LD_LIBRARY_PATH="$APPLIB:$QTLIB"
missing=0
while IFS= read -r f; do
    bad="$(ldd "$f" 2>/dev/null | grep 'not found' || true)"
    if [ -n "$bad" ]; then
        echo "MISSING in $f:"; echo "$bad"; missing=1
    fi
done < <(find "$APPDIR" -name "*.so*" -o -name "python3.12" -o -name "gst-plugin-scanner")
[ "$missing" = 0 ] && echo "all deps resolved"

echo "== AppRun / desktop / icon =="
cat > "$APPDIR/AppRun" <<'RUN'
#!/bin/bash
HERE="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
export LD_LIBRARY_PATH="$HERE/usr/lib/x86_64-linux-gnu:$HERE/usr/pyapp/PySide6/Qt/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export GI_TYPELIB_PATH="$HERE/usr/lib/x86_64-linux-gnu/girepository-1.0"
export GST_PLUGIN_PATH="$HERE/usr/lib/x86_64-linux-gnu/gstreamer-1.0"
export GST_PLUGIN_SYSTEM_PATH_1_0="$HERE/usr/lib/x86_64-linux-gnu/gstreamer-1.0"
export GST_PLUGIN_SCANNER="$HERE/usr/libexec/gst-plugin-scanner"
export GST_REGISTRY_1_0="${XDG_CACHE_HOME:-$HOME/.cache}/tuxcam-gst-registry.bin"
export PYTHONHOME="$HERE/usr"
export PYTHONPATH="$HERE/usr/pyapp"
exec "$HERE/usr/bin/python3.12" "$HERE/usr/app/tuxcam.py" "$@"
RUN
chmod +x "$APPDIR/AppRun"

cat > "$APPDIR/tuxcam.desktop" <<'DESK'
[Desktop Entry]
Type=Application
Name=Tuxcam
Comment=Webcam viewer and recorder
Exec=tuxcam
Icon=tuxcam
Categories=AudioVideo;Video;
DESK
cp "$ROOT/packaging/tuxcam.png" "$APPDIR/tuxcam.png"

echo "== pack =="
mkdir -p "$BUILD"
TOOL="$BUILD/appimagetool-x86_64.AppImage"
if [ ! -x "$TOOL" ]; then
    curl -L -o "$TOOL" "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x "$TOOL"
fi
ARCH=x86_64 "$TOOL" "$APPDIR" "$ROOT/Tuxcam-x86_64.AppImage"
ls -lh "$ROOT/Tuxcam-x86_64.AppImage"
