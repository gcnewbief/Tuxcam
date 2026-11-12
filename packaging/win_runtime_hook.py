"""PyInstaller runtime hook: set up the bundled GStreamer/GI environment.

Mirrors the AppImage's AppRun env-vars. sys._MEIPASS is the extraction dir
(onefile) or the app dir (onedir).
"""

import os
import sys

base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))


def _set(name, *parts):
    p = os.path.join(base, *parts)
    if os.path.exists(p):
        os.environ[name] = p


_set("FONTCONFIG_PATH", "etc", "fonts")
# persist the plugin registry across launches (the default lands in the
# onefile temp dir and gets rescanned every start)
os.environ.setdefault(
    "GST_REGISTRY_1_0",
    os.path.join(
        os.environ.get("LOCALAPPDATA", base), "Tuxcam", "gst-registry.bin"
    ),
)
