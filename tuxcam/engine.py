"""GStreamer camera engine for Tuxcam.

One always-running pipeline:

    v4l2src -> caps -> (jpegdec) -> videoconvert -> videocrop (zoom)
        -> videoscale -> videobalance -> textoverlay -> tee
            -> queue -> videoconvert -> appsink          (preview)
            -> [record bin attached on demand]           (recording)

    pulsesrc -> audioconvert -> audioresample -> tee
            -> queue -> level -> fakesink                (meter)
            -> [record bin audio chain]

Recording attaches a fresh bin (queue->x264->mp4mux->filesink plus an optional
AAC audio chain) to the tees, and detaches it after a clean EOS so the
container is always finalized properly.
"""

from __future__ import annotations

import datetime
import os
import time
from dataclasses import dataclass

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

from PySide6.QtCore import QObject, Signal, QTimer, QEventLoop
from PySide6.QtGui import QImage

Gst.init(None)

FPS_CANDIDATES = (60, 50, 30, 25, 24, 20, 15, 10, 5)


@dataclass(frozen=True)
class Mode:
    width: int
    height: int
    fps_num: int
    fps_den: int
    format: str = "video/x-raw"

    @property
    def fps(self) -> float:
        return self.fps_num / self.fps_den

    @property
    def caps(self) -> str:
        if not self.width:
            return self.format
        return (
            f"{self.format},width={self.width},height={self.height},"
            f"framerate={self.fps_num}/{self.fps_den}"
        )

    @property
    def label(self) -> str:
        if not self.width:
            return "Auto (device default)"
        s = f"{self.width}x{self.height} @ {self.fps:g} fps"
        if self.format == "image/jpeg":
            s += " (MJPG)"
        return s


@dataclass
class Device:
    name: str
    path: str
    modes: list

    @property
    def label(self) -> str:
        return f"{self.name} ({self.path})"


def _framerates(st) -> list:
    """Supported framerates for a caps structure.

    PyGObject can't unbox GstValueList / GstFractionRange fields, so for
    non-scalar fields we fixate a copy toward each candidate fps — fixation
    always yields a value the device actually supports.
    """
    if not st.has_field("framerate"):
        return [(30, 1)]
    ok, n, d = st.get_fraction("framerate")
    if ok and d:
        return [(n, d)]
    out = set()
    for f in FPS_CANDIDATES:
        c = st.copy()
        if c.fixate_field_nearest_fraction("framerate", f, 1):
            ok2, n2, d2 = c.get_fraction("framerate")
            if ok2 and d2:
                out.add((n2, d2))
    return sorted(out) or [(30, 1)]


def _int_field(st, name):
    ok, v = st.get_int(name)
    return v if ok else None


def list_devices() -> list:
    """Enumerate V4L2 capture devices and their supported modes."""
    mon = Gst.DeviceMonitor()
    mon.start()
    devs = []
    for d in mon.get_devices():
        if not d.has_classes("Video/Source"):
            continue
        props = d.get_properties()
        path = None
        for key in ("device.path", "api.v4l2.path", "object.path"):
            if props and props.has_field(key):
                path = props.get_string(key)
                if path and ":" in path and not path.startswith("/"):
                    path = path.split(":", 1)[1]
                break
        caps = d.get_caps()
        modes = set()
        if caps:
            for i in range(caps.get_size()):
                st = caps.get_structure(i)
                name = st.get_name()
                if name not in ("video/x-raw", "image/jpeg"):
                    continue
                w = _int_field(st, "width")
                h = _int_field(st, "height")
                if w is None or h is None:
                    # range/list dims — offer an unconstrained mode
                    modes.add(Mode(0, 0, 30, 1, name))
                    continue
                for n, dn in _framerates(st):
                    modes.add(Mode(w, h, n, dn, name))
        if not path or not modes:
            continue
        devs.append(
            Device(
                name=d.get_display_name(),
                path=path,
                modes=sorted(modes, key=lambda m: (-m.width * m.height, -m.fps)),
            )
        )
    mon.stop()
    return devs


def _bitrate_kbps(mode: Mode) -> int:
    px = mode.width * mode.height
    if px >= 1920 * 1080:
        return 8000
    if px >= 1280 * 720:
        return 5000
    return 3000


class CameraEngine(QObject):
    frame_ready = Signal(QImage)
    level_changed = Signal(float)  # 0.0 - 1.0
    error = Signal(str)
    recording_started = Signal()
    recording_finished = Signal(str)  # saved file path
    rec_stats = Signal(float, int)  # elapsed seconds, file bytes

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pipeline = None
        self._bus = None
        self.device = None
        self.mode = None
        self.audio_device = None
        self.last_frame = None
        self.zoom = 1.0
        self._focus = None      # (x, y) in source pixels, or None = center
        self._crop_rect = None  # (left, top, w, h) of current crop
        self.timestamp_on = True

        self._rec = None
        self._rec_t0 = 0.0

        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(10)
        self._frame_timer.timeout.connect(self._pull_frame)

        self._pump_timer = QTimer(self)
        self._pump_timer.setInterval(5)
        self._pump_timer.timeout.connect(self._pump_recording)

        self._bus_timer = QTimer(self)
        self._bus_timer.setInterval(30)
        self._bus_timer.timeout.connect(self._poll_bus)

        self._ts_timer = QTimer(self)
        self._ts_timer.setInterval(500)
        self._ts_timer.timeout.connect(self._tick_ts)

        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(500)
        self._stats_timer.timeout.connect(self._tick_stats)

    # ------------------------------------------------------------------
    # pipeline lifecycle
    # ------------------------------------------------------------------

    def start(self, device: Device, mode: Mode, audio_device) -> bool:
        self.stop()
        self.device, self.mode, self.audio_device = device, mode, audio_device

        decoder = "jpegdec ! " if mode.format == "image/jpeg" else ""
        if mode.width:
            scale = (
                "videoscale ! "
                f"video/x-raw,width={mode.width},height={mode.height} ! "
            )
        else:
            scale = "videoscale ! "
        desc = (
            f'v4l2src device="{device.path}" name=src ! {mode.caps} ! {decoder}'
            "videoconvert ! "
            "videocrop name=crop ! "
            f"{scale}"
            "videobalance name=balance ! "
            'textoverlay name=ts text="" valignment=bottom halignment=right '
            'font-desc="Sans, 18" shaded-background=true ! '
            'textoverlay name=meta text="" valignment=top halignment=left '
            'font-desc="Sans, 18" shaded-background=true ! '
            "tee name=vtee allow-not-linked=true "
            "vtee. ! queue leaky=downstream max-size-buffers=3 ! videoconvert ! "
            "video/x-raw,format=RGB ! "
            "appsink name=preview max-buffers=2 drop=true "
            "sync=false "
            # permanent record tap (leaky — can never stall the preview)
            "vtee. ! queue name=rvq leaky=downstream max-size-buffers=90 ! "
            "appsink name=rvsink max-buffers=90 drop=true sync=false"
        )
        if audio_device is not None:
            desc += (
                " pulsesrc name=asrc ! audioconvert ! audioresample ! "
                "tee name=atee allow-not-linked=true "
                "atee. ! queue leaky=downstream max-size-buffers=10 ! "
                "audioconvert ! audioresample ! "
                "level name=level interval=100000000 post-messages=true ! "
                "fakesink sync=false "
                # permanent record tap for audio
                "atee. ! queue name=raq leaky=downstream max-size-buffers=400 ! "
                "appsink name=rasink max-buffers=400 drop=true sync=false"
            )

        try:
            self.pipeline = Gst.parse_launch(desc)
        except GLib.Error as e:
            self.pipeline = None
            self.error.emit(f"Could not build pipeline: {e}")
            return False

        if audio_device not in (None, "default"):
            asrc = self.pipeline.get_by_name("asrc")
            if asrc:
                asrc.set_property("device", audio_device)

        self._ts = self.pipeline.get_by_name("ts")
        self._meta = self.pipeline.get_by_name("meta")
        self._crop = self.pipeline.get_by_name("crop")
        self._balance = self.pipeline.get_by_name("balance")
        self._vtee = self.pipeline.get_by_name("vtee")
        self._atee = self.pipeline.get_by_name("atee")

        self._appsink = self.pipeline.get_by_name("preview")

        self._bus = self.pipeline.get_bus()
        self._bus_timer.start()
        self._frame_timer.start()
        self._ts_timer.start()
        self._tick_ts()

        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            self.error.emit("Could not start camera (device busy or removed?)")
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
            return False
        self._apply_zoom()
        return True

    def stop(self):
        if self._rec:
            self.stop_recording()
            # wait for the container to finalize (max ~3 s)
            loop = QEventLoop()
            self.recording_finished.connect(loop.quit)
            QTimer.singleShot(3000, loop.quit)
            loop.exec()
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline.get_state(2 * Gst.SECOND)
            self.pipeline = None
            # drop element refs so GC never disposes a PLAYING element
            self._appsink = self._rvsink = self._rasink = None
            self._ts = self._meta = self._crop = self._balance = None
            self._vtee = self._atee = None
            self._bus = None
        self._bus_timer.stop()
        self._frame_timer.stop()
        self._pump_timer.stop()
        self._ts_timer.stop()
        self._stats_timer.stop()
        self.last_frame = None

    # ------------------------------------------------------------------
    # live controls
    # ------------------------------------------------------------------

    def set_zoom(self, z: float):
        self.zoom = max(1.0, z)
        self._apply_zoom()

    def set_zoom_at(self, z: float, fx: float, fy: float):
        """Zoom toward a point. The anchor is set from the pointer on the
        first step of a gesture and kept until zoom returns to 1x."""
        if not self.mode or not self.mode.width:
            return
        if self._focus is None:
            w, h = self.mode.width, self.mode.height
            if self._crop_rect:
                l, t, cw, ch = self._crop_rect
                self._focus = (l + fx * cw, t + fy * ch)
            else:
                self._focus = (fx * w, fy * h)
        self.zoom = max(1.0, z)
        self._apply_zoom()

    def _apply_zoom(self):
        if not getattr(self, "_crop", None) or not self.mode or not self.mode.width:
            return
        w, h = self.mode.width, self.mode.height
        keep_w = int(w / self.zoom) & ~1
        keep_h = int(h / self.zoom) & ~1
        cx, cy = self._focus if self._focus else (w / 2, h / 2)
        left = max(0, min(w - keep_w, int(round(cx - keep_w / 2))))
        top = max(0, min(h - keep_h, int(round(cy - keep_h / 2))))
        self._crop.set_property("left", left)
        self._crop.set_property("right", w - keep_w - left)
        self._crop.set_property("top", top)
        self._crop.set_property("bottom", h - keep_h - top)
        self._crop_rect = (left, top, keep_w, keep_h)
        if self.zoom <= 1.0:
            self._focus = None

    def set_balance(self, prop: str, value: float):
        if getattr(self, "_balance", None):
            self._balance.set_property(prop, value)

    def set_label(self, name: str, order: str, on: bool):
        if getattr(self, "_meta", None):
            parts = [p for p in (name.strip(), order.strip()) if p]
            self._meta.set_property(
                "text", "\n".join(parts) if on and parts else ""
            )

    def set_timestamp(self, on: bool):
        self.timestamp_on = on
        self._tick_ts()

    def _tick_ts(self):
        if getattr(self, "_ts", None):
            text = (
                datetime.datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
                if self.timestamp_on
                else ""
            )
            self._ts.set_property("text", text)

    # ------------------------------------------------------------------
    # recording
    # ------------------------------------------------------------------

    @property
    def recording(self) -> bool:
        return self._rec is not None

    def start_recording(self, path: str, container: str = "mp4"):
        if self._rec or not self.pipeline:
            return
        mux_name = "mp4mux" if container == "mp4" else "matroskamux"
        with_audio = self.audio_device is not None and self._atee is not None
        kbps = _bitrate_kbps(self.mode)

        # Separate encoder pipeline fed via appsrc — avoids fragile dynamic
        # pad linking and EOS injection on the live camera pipeline.
        desc = (
            "appsrc name=vasrc is-live=true format=time do-timestamp=true "
            "block=false ! videoconvert ! "
            f"x264enc tune=zerolatency speed-preset=veryfast bitrate={kbps} "
            "key-int-max=60 ! h264parse ! rmux. "
        )
        if with_audio:
            desc += (
                "appsrc name=aasrc is-live=true format=time do-timestamp=true "
                "block=false ! audioconvert ! audioresample ! "
                "avenc_aac bitrate=192000 ! aacparse ! rmux. "
            )
        if container == "mp4":
            desc += f'mp4mux name=rmux faststart=true ! filesink location="{path}"'
        else:
            desc += f'matroskamux name=rmux writing-app="Tuxcam" ! filesink location="{path}"'
        try:
            rp = Gst.parse_launch(desc)
        except GLib.Error as e:
            self.error.emit(f"Could not build recorder: {e}")
            return

        self._rvsink = self.pipeline.get_by_name("rvsink")
        vasrc = rp.get_by_name("vasrc")
        aasrc = rp.get_by_name("aasrc") if with_audio else None
        self._rasink = self.pipeline.get_by_name("rasink") if with_audio else None

        # drop stale buffered samples — the file should start at "now"
        for s in (self._rvsink, self._rasink):
            if s:
                while s.emit("try-pull-sample", 0):
                    pass

        self._rec = {
            "pipeline": rp,
            "bus": rp.get_bus(),
            "path": path,
            "stopping": False,
            "taps": [[self._rvsink, vasrc, False]],
        }
        if aasrc and self._rasink:
            self._rec["taps"].append([self._rasink, aasrc, False])

        rp.set_state(Gst.State.PLAYING)
        self._rec_t0 = time.monotonic()
        self._pump_timer.start()
        self._stats_timer.start()
        self.recording_started.emit()

    def _pump_recording(self):
        rec = self._rec
        if not rec or rec["stopping"]:
            return
        for tap in rec["taps"]:
            sink, asrc, caps_done = tap
            for _ in range(200):
                sample = sink.emit("try-pull-sample", 0)
                if not sample:
                    break
                if not caps_done:
                    asrc.set_property("caps", sample.get_caps())
                    caps_done = tap[2] = True
                asrc.emit("push-buffer", sample.get_buffer())

    def stop_recording(self):
        rec = self._rec
        if not rec or rec["stopping"]:
            return
        rec["stopping"] = True
        self._pump_recording()
        self._pump_timer.stop()
        for tap in rec["taps"]:
            tap[1].emit("end-of-stream")
        QTimer.singleShot(8000, self._teardown_guard)

    def _teardown_guard(self):
        if self._rec and self._rec["stopping"]:
            self._finish_recording()

    def _finish_recording(self):
        rec = self._rec
        if not rec:
            return
        rec["pipeline"].set_state(Gst.State.NULL)
        rec["pipeline"].get_state(500 * Gst.MSECOND)
        self._rec = None
        self._stats_timer.stop()
        self.recording_finished.emit(rec["path"])

    def _tick_stats(self):
        if self._rec:
            try:
                size = os.path.getsize(self._rec["path"])
            except OSError:
                size = 0
            self.rec_stats.emit(time.monotonic() - self._rec_t0, size)

    # ------------------------------------------------------------------
    # frames + bus
    # ------------------------------------------------------------------

    def _pull_frame(self):
        if not getattr(self, "_appsink", None):
            return
        sample = self._appsink.emit("try-pull-sample", 0)
        if not sample:
            return
        buf = sample.get_buffer()
        st = sample.get_caps().get_structure(0)
        ok_w, w = st.get_int("width")
        ok_h, h = st.get_int("height")
        if not (ok_w and ok_h) or not w or not h:
            return
        ok, mapinfo = buf.map(Gst.MapFlags.READ)
        if not ok:
            return
        try:
            # RGB is a single plane; stride is size/height when tightly packed
            stride = mapinfo.size // h if mapinfo.size % h == 0 else w * 3
            img = QImage(
                mapinfo.data, w, h, stride, QImage.Format_RGB888
            ).copy()
            self.last_frame = img
            self.frame_ready.emit(img)
        finally:
            buf.unmap(mapinfo)

    def _poll_bus(self):
        self._drain_bus(self._bus)
        if self._rec:
            self._drain_bus(self._rec["bus"])

    def _drain_bus(self, bus):
        while bus:
            msg = bus.timed_pop_filtered(0, Gst.MessageType.ANY)
            if msg is None:
                break
            t = msg.type
            if t == Gst.MessageType.ERROR:
                err, dbg = msg.parse_error()
                self.error.emit(f"{err.message}")
            elif t == Gst.MessageType.WARNING:
                err, _ = msg.parse_warning()
                self.error.emit(f"warning: {err.message}")
            elif t == Gst.MessageType.EOS:
                if self._rec and msg.src is self._rec["pipeline"]:
                    self._finish_recording()
            elif t == Gst.MessageType.ELEMENT:
                s = msg.get_structure()
                if s and s.get_name() == "level":
                    rms = s.get_value("rms")
                    peak = s.get_value("peak")
                    val = None
                    if peak:
                        val = max(peak)
                    elif rms:
                        val = max(rms)
                    if val is not None:
                        self.level_changed.emit(max(0.0, min(1.0, (val + 60) / 60)))
