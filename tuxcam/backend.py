"""Platform backend: capture-source elements + device/audio enumeration.

Everything platform-specific lives here (with the control backends in
v4l2.py / win_controls.py). engine.py and window.py only ever see
GstElements and plain data, so the pipeline code stays identical on
Linux and Windows.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst

Gst.init(None)  # idempotent — engine.py also calls it

WINDOWS = sys.platform == "win32"

if WINDOWS:
    from . import win_controls as controls  # noqa: F401  (re-exported)
else:
    from . import v4l2 as controls  # noqa: F401  (re-exported)

# When several providers see the same camera, prefer elements in this order.
_WIN_VIDEO_FACTORIES = ("ksvideosrc", "mfvideosrc", "dshowvideosrc")
_WIN_VIDEO_PRIORITY = {n: i for i, n in enumerate(_WIN_VIDEO_FACTORIES)}
_WIN_AUDIO_FACTORIES = ("wasapi2src", "wasapisrc", "dshowaudiosrc")

_AUDIO_DEVS = {}  # audio key -> GstDevice, from the last list_audio_sources()

_PNP_RE = re.compile(r"vid_[0-9a-f]+&pid_[0-9a-f]+[^#]*#[0-9a-z&]+", re.I)


def device_path(gst_device) -> str | None:
    """The stable identifier for a GstDevice ('/dev/video0' on Linux, the
    PnP symbolic path on Windows)."""
    props = gst_device.get_properties()
    if props is None:
        return None
    if WINDOWS:
        for key in ("device.path", "object.path", "device.id"):
            if props.has_field(key):
                return props.get_string(key)
        return None
    for key in ("device.path", "api.v4l2.path", "object.path"):
        if props.has_field(key):
            path = props.get_string(key)
            if path and ":" in path and not path.startswith("/"):
                path = path.split(":", 1)[1]
            return path
    return None


def device_key(gst_device, path) -> str:
    """Dedupe key: on Windows ks/mf/dshow providers each report the same
    physical camera — collapse them on the PnP instance id."""
    p = path or device_path(gst_device) or ""
    if not WINDOWS:
        return p
    m = _PNP_RE.search(p.lower())
    return m.group(0) if m else p.lower()


def device_priority(gst_device) -> int:
    """Lower is better when duplicates are found (Windows only)."""
    if not WINDOWS:
        return 0
    el = gst_device.create_element()
    name = el.get_factory().get_name() if el and el.get_factory() else ""
    if el:
        el.set_state(Gst.State.NULL)
        el.unref()
    return _WIN_VIDEO_PRIORITY.get(name, 9)


def create_video_source(device):
    """A configured video-source GstElement for a Device, or None."""
    gd = getattr(device, "gst_device", None)
    if gd is not None:
        el = gd.create_element()
        if el:
            el.set_name("src")
            return el
    if WINDOWS:
        for name in _WIN_VIDEO_FACTORIES:
            el = Gst.ElementFactory.make(name, "src")
            if el and device.path:
                try:
                    el.set_property("device-path", device.path)
                except TypeError:
                    pass
            if el:
                return el
        return None
    el = Gst.ElementFactory.make("v4l2src", "src")
    if el and device.path:
        el.set_property("device", device.path)
    return el


def list_audio_sources():
    """Return [(key, label)]; key None = no audio, 'default' = OS default."""
    if not WINDOWS:
        out = [("default", "Default microphone")]
        try:
            r = subprocess.run(
                ["pactl", "list", "sources"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            for block in r.stdout.split("Source #")[1:]:
                name = re.search(r"^\s*Name:\s*(\S+)", block, re.M)
                desc = re.search(r"^\s*Description:\s*(.+)", block, re.M)
                if name:
                    label = desc.group(1).strip() if desc else name.group(1)
                    out.append((name.group(1), label))
        except Exception:
            pass
        out.insert(0, (None, "No audio"))
        return out

    _AUDIO_DEVS.clear()
    out = [(None, "No audio"), ("default", "Default microphone")]
    mon = Gst.DeviceMonitor()
    mon.start()
    # providers probe asynchronously — give them a moment to populate
    time.sleep(0.8)
    try:
        for d in mon.get_devices():
            if not d.has_classes("Audio/Source"):
                continue
            path = device_path(d) or d.get_display_name()
            if path in _AUDIO_DEVS:
                continue
            _AUDIO_DEVS[path] = d
            out.append((path, d.get_display_name()))
    finally:
        mon.stop()
    return out


def create_audio_source(key):
    """A configured audio-source GstElement, or None when key is falsy."""
    if key in (None, ""):
        return None
    if WINDOWS:
        gd = _AUDIO_DEVS.get(key)
        if gd is not None:
            el = gd.create_element()
            if el:
                el.set_name("asrc")
                return el
        for name in _WIN_AUDIO_FACTORIES:
            el = Gst.ElementFactory.make(name, "asrc")
            if el:
                return el
        return None
    el = Gst.ElementFactory.make("pulsesrc", "asrc")
    if el and key != "default":
        el.set_property("device", key)
    return el
