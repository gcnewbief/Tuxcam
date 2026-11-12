"""Main window for Tuxcam."""

from __future__ import annotations

import datetime
import os
import re
import subprocess

from PySide6.QtCore import Qt, QSettings, QTimer, Signal, Slot
from PySide6.QtGui import QImage, QKeySequence, QPainter, QColor, QPen, QFont, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import v4l2, __version__
from .engine import CameraEngine, list_devices

ORG = "Tuxcam"
APP = "Tuxcam"


def list_audio_sources():
    """Return [(source_name, label)] from pactl, plus Default/None."""
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


class VideoView(QWidget):
    """Letterboxed video preview."""

    double_clicked = Signal()
    zoom_at = Signal(float, float, float)  # steps, x fraction, y fraction

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frame = None
        self._disp_rect = None
        self.recording = False
        self.setMinimumSize(640, 360)
        self.setStyleSheet("background: black;")

    @Slot(QImage)
    def set_frame(self, img: QImage):
        self._frame = img
        self.update()

    def clear(self):
        self._frame = None
        self.update()

    def mouseDoubleClickEvent(self, _):
        self.double_clicked.emit()

    def wheelEvent(self, ev):
        steps = ev.angleDelta().y() / 120.0
        if not steps:
            return
        r = self._disp_rect
        if r and r[2] > 0 and r[3] > 0:
            fx = (ev.position().x() - r[0]) / r[2]
            fy = (ev.position().y() - r[1]) / r[3]
            fx = max(0.0, min(1.0, fx))
            fy = max(0.0, min(1.0, fy))
        else:
            fx = fy = 0.5
        self.zoom_at.emit(steps, fx, fy)

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        if self._frame and not self._frame.isNull():
            img = self._frame.scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            x = (self.width() - img.width()) // 2
            y = (self.height() - img.height()) // 2
            self._disp_rect = (x, y, img.width(), img.height())
            p.drawImage(x, y, img)
        else:
            p.setPen(QColor(120, 120, 120))
            p.drawText(self.rect(), Qt.AlignCenter, "No video signal")
        if self.recording:
            f = QFont()
            f.setBold(True)
            p.setFont(f)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(220, 30, 30))
            p.drawEllipse(14, 14, 14, 14)
            p.setPen(QColor(255, 255, 255))
            p.drawText(34, 27, "REC")
            p.setPen(QPen(QColor(220, 30, 30), 3))
            p.setBrush(Qt.NoBrush)
            p.drawRect(self.rect().adjusted(1, 1, -2, -2))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Tuxcam {__version__}")
        self.resize(1100, 720)
        self.settings = QSettings(ORG, APP)
        self.engine = CameraEngine(self)
        self.devices = []
        self._building = False

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ---- top bar: device / mode / refresh --------------------------
        top = QHBoxLayout()
        top.addWidget(QLabel("Camera:"))
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(260)
        top.addWidget(self.device_combo)
        top.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.setMinimumWidth(210)
        top.addWidget(self.mode_combo)
        self.refresh_btn = QPushButton("Refresh")
        top.addWidget(self.refresh_btn)
        top.addSpacing(20)
        top.addWidget(QLabel("Format:"))
        self.fmt_combo = QComboBox()
        self.fmt_combo.addItem("MP4 (H.264 + AAC)", "mp4")
        self.fmt_combo.addItem("MKV (H.264 + AAC)", "mkv")
        top.addWidget(self.fmt_combo)
        top.addStretch(1)
        self.outdir_btn = QPushButton("Save to…")
        top.addWidget(self.outdir_btn)
        root.addLayout(top)

        # ---- video ------------------------------------------------------
        self.video = VideoView()
        root.addWidget(self.video, stretch=1)

        # ---- adjust panel ------------------------------------------------
        self.adjust_frame = QFrame()
        self.adjust_frame.setFrameShape(QFrame.StyledPanel)
        adj = QHBoxLayout(self.adjust_frame)
        adj.setContentsMargins(8, 4, 8, 4)
        self.bright = self._slider(-100, 100, 0)
        self.contrast = self._slider(0, 200, 100)
        self.sat = self._slider(0, 200, 100)
        for lbl, s in (
            ("Brightness", self.bright),
            ("Contrast", self.contrast),
            ("Saturation", self.sat),
        ):
            adj.addWidget(QLabel(lbl))
            adj.addWidget(s, stretch=1)
        reset = QPushButton("Reset")
        reset.clicked.connect(self._reset_adjust)
        adj.addWidget(reset)
        self.adjust_frame.setVisible(False)
        root.addWidget(self.adjust_frame)

        # ---- hardware camera controls ------------------------------------
        self.ctrls_frame = QFrame()
        self.ctrls_frame.setFrameShape(QFrame.StyledPanel)
        cf = QVBoxLayout(self.ctrls_frame)
        cf.setContentsMargins(8, 4, 8, 8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(220)
        inner = QWidget()
        self.ctrls_layout = QGridLayout(inner)
        self.ctrls_layout.setColumnStretch(1, 1)
        scroll.setWidget(inner)
        cf.addWidget(scroll)
        self.ctrls_frame.setVisible(False)
        root.addWidget(self.ctrls_frame)
        self._hw_timers = {}   # ctrl id -> QTimer debounce for slider ioctls

        # ---- name/order label panel --------------------------------------
        self.label_frame = QFrame()
        self.label_frame.setFrameShape(QFrame.StyledPanel)
        lf = QHBoxLayout(self.label_frame)
        lf.setContentsMargins(8, 4, 8, 4)
        self.label_chk = QCheckBox("Show on video")
        lf.addWidget(self.label_chk)
        lf.addSpacing(12)
        lf.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. J. Smith")
        self.name_edit.setMaximumWidth(220)
        lf.addWidget(self.name_edit)
        lf.addWidget(QLabel("Order #:"))
        self.order_edit = QLineEdit()
        self.order_edit.setPlaceholderText("e.g. 12345-A")
        self.order_edit.setMaximumWidth(160)
        lf.addWidget(self.order_edit)
        lf.addStretch(1)
        self.label_frame.setVisible(False)
        root.addWidget(self.label_frame)

        # ---- bottom bar --------------------------------------------------
        bottom = QHBoxLayout()
        self.rec_btn = QPushButton("●  Record")
        self.rec_btn.setMinimumHeight(40)
        self.rec_btn.setMinimumWidth(130)
        self.rec_btn.setStyleSheet("font-weight: bold;")
        bottom.addWidget(self.rec_btn)
        self.snap_btn = QPushButton("Snapshot")
        self.snap_btn.setMinimumHeight(40)
        bottom.addWidget(self.snap_btn)
        self.full_btn = QPushButton("Fullscreen")
        self.full_btn.setMinimumHeight(40)
        bottom.addWidget(self.full_btn)
        self.adj_btn = QPushButton("Adjust")
        self.adj_btn.setCheckable(True)
        self.adj_btn.setMinimumHeight(40)
        bottom.addWidget(self.adj_btn)
        self.cam_btn = QPushButton("Camera")
        self.cam_btn.setCheckable(True)
        self.cam_btn.setMinimumHeight(40)
        bottom.addWidget(self.cam_btn)
        self.label_btn = QPushButton("Label")
        self.label_btn.setCheckable(True)
        self.label_btn.setMinimumHeight(40)
        bottom.addWidget(self.label_btn)
        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        bottom.addWidget(line)
        self.ts_chk = QCheckBox("Timestamp overlay")
        bottom.addWidget(self.ts_chk)
        bottom.addWidget(QLabel("Zoom:"))
        self.zoom_less = QToolButton()
        self.zoom_less.setText("−")
        self.zoom_less.setAutoRepeat(True)
        self.zoom_less.clicked.connect(
            lambda: self.zoom.setValue(self.zoom.value() - 10)
        )
        bottom.addWidget(self.zoom_less)
        self.zoom = self._slider(100, 400, 100)
        self.zoom.setMaximumWidth(140)
        bottom.addWidget(self.zoom)
        self.zoom_more = QToolButton()
        self.zoom_more.setText("+")
        self.zoom_more.setAutoRepeat(True)
        self.zoom_more.clicked.connect(
            lambda: self.zoom.setValue(self.zoom.value() + 10)
        )
        bottom.addWidget(self.zoom_more)
        self.zoom_lbl = QLabel("100%")
        self.zoom_lbl.setMinimumWidth(44)
        self.zoom_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bottom.addWidget(self.zoom_lbl)
        bottom.addStretch(1)
        bottom.addWidget(QLabel("Audio:"))
        self.audio_combo = QComboBox()
        self.audio_combo.setMinimumWidth(200)
        bottom.addWidget(self.audio_combo)
        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setMaximumWidth(90)
        self.meter.setTextVisible(False)
        self.meter.setMaximumHeight(12)
        bottom.addWidget(self.meter)
        root.addLayout(bottom)

        # ---- status bar ---------------------------------------------------
        self.status_label = QLabel("Ready")
        self.statusBar().addWidget(self.status_label, stretch=1)
        self.rec_label = QLabel("")
        self.statusBar().addPermanentWidget(self.rec_label)

        # ---- shortcuts ----------------------------------------------------
        for key, slot in (
            ("R", self._toggle_recording),
            ("S", self._snapshot),
            ("F", self._toggle_fullscreen),
        ):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(slot)

        # ---- wiring ---------------------------------------------------------
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.refresh_btn.clicked.connect(self.refresh_devices)
        self.fmt_combo.currentIndexChanged.connect(self._save_ui_settings)
        self.outdir_btn.clicked.connect(self._pick_outdir)
        self.rec_btn.clicked.connect(self._toggle_recording)
        self.snap_btn.clicked.connect(self._snapshot)
        self.full_btn.clicked.connect(self._toggle_fullscreen)
        self.adj_btn.toggled.connect(self.adjust_frame.setVisible)
        self.cam_btn.toggled.connect(self.ctrls_frame.setVisible)
        self.label_btn.toggled.connect(self.label_frame.setVisible)
        self.label_chk.toggled.connect(self._update_label)
        self.name_edit.textEdited.connect(self._update_label)
        self.order_edit.textEdited.connect(self._update_label)
        self.ts_chk.toggled.connect(self.engine.set_timestamp)
        self.ts_chk.toggled.connect(self._save_ui_settings)
        self.zoom.valueChanged.connect(self._zoom_changed)
        self.zoom.valueChanged.connect(self._save_ui_settings)
        self.video.zoom_at.connect(self._wheel_zoom)
        self.audio_combo.currentIndexChanged.connect(self._on_audio_changed)
        self.bright.valueChanged.connect(
            lambda v: self.engine.set_balance("brightness", v / 100.0)
        )
        self.contrast.valueChanged.connect(
            lambda v: self.engine.set_balance("contrast", v / 100.0)
        )
        self.sat.valueChanged.connect(
            lambda v: self.engine.set_balance("saturation", v / 100.0)
        )
        self.video.double_clicked.connect(self._toggle_fullscreen)

        self.engine.frame_ready.connect(self.video.set_frame)
        self.engine.level_changed.connect(
            lambda v: self.meter.setValue(int(v * 100))
        )
        self.engine.error.connect(self._on_error)
        self.engine.recording_started.connect(self._on_rec_started)
        self.engine.recording_finished.connect(self._on_rec_finished)
        self.engine.rec_stats.connect(self._on_rec_stats)

        self._load_ui_settings()
        self.refresh_devices()

    # ------------------------------------------------------------------
    def _zoom_changed(self, v):
        self.zoom_lbl.setText(f"{v}%")
        self.engine.set_zoom(v / 100.0)

    def _wheel_zoom(self, steps, fx, fy):
        if not steps:
            return
        f = max(1.0, min(4.0, self.engine.zoom * (1.05 ** steps)))
        if f > 1.0:
            self.engine.set_zoom_at(f, fx, fy)
        else:
            self.engine.set_zoom(1.0)
        v = int(round(f * 100))
        self.zoom.blockSignals(True)
        self.zoom.setValue(v)
        self.zoom.blockSignals(False)
        self.zoom_lbl.setText(f"{v}%")
        self._save_ui_settings()

    def _slider(self, lo, hi, val):
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.setValue(val)
        return s

    def _outdir(self) -> str:
        d = self.settings.value(
            "output_dir", os.path.expanduser("~/Videos/Tuxcam")
        )
        os.makedirs(d, exist_ok=True)
        return d

    def _unique_path(self, prefix, ext) -> str:
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base = os.path.join(self._outdir(), f"{prefix}_{stamp}")
        path = f"{base}.{ext}"
        n = 1
        while os.path.exists(path):
            path = f"{base}_{n}.{ext}"
            n += 1
        return path

    # ------------------------------------------------------------------
    # device / mode management
    # ------------------------------------------------------------------

    def refresh_devices(self):
        self._building = True
        self.devices = list_devices()
        self.device_combo.clear()
        for d in self.devices:
            self.device_combo.addItem(d.label, d)
        saved_path = self.settings.value("device_path", "")
        idx = 0
        for i, d in enumerate(self.devices):
            if d.path == saved_path:
                idx = i
        self.device_combo.setCurrentIndex(idx)
        self._fill_modes()
        self._fill_audio()
        self._building = False
        self._restart_pipeline()
        if not self.devices:
            self.status_label.setText("No cameras found")

    def _fill_modes(self):
        self.mode_combo.clear()
        d = self.device_combo.currentData()
        if not d:
            return
        saved = self.settings.value("mode_label", "")
        idx = 0
        for i, m in enumerate(d.modes):
            self.mode_combo.addItem(m.label, m)
            if m.label == saved:
                idx = i
        self.mode_combo.setCurrentIndex(idx)

    def _fill_audio(self):
        self.audio_combo.clear()
        saved = self.settings.value("audio_device", "default")
        idx = 0
        for i, (name, label) in enumerate(list_audio_sources()):
            self.audio_combo.addItem(label, name)
            if name == saved:
                idx = i
        self.audio_combo.setCurrentIndex(idx)

    def _on_device_changed(self, _):
        if self._building:
            return
        self._building = True
        self._fill_modes()
        self._building = False
        self._restart_pipeline()

    def _on_mode_changed(self, _):
        if not self._building:
            self._restart_pipeline()

    def _on_audio_changed(self, _):
        if not self._building:
            self._restart_pipeline()

    def _restart_pipeline(self):
        if self._building:
            return
        d = self.device_combo.currentData()
        m = self.mode_combo.currentData()
        if not d or not m:
            return
        audio = self.audio_combo.currentData()
        self.video.clear()
        if self.engine.start(d, m, audio):
            self.status_label.setText(f"{d.path} — {m.label}")
        self._build_controls(d.path)
        self._update_label()
        # re-apply persistent controls to the fresh pipeline
        self.engine.set_zoom(self.zoom.value() / 100.0)
        self.engine.set_balance("brightness", self.bright.value() / 100.0)
        self.engine.set_balance("contrast", self.contrast.value() / 100.0)
        self.engine.set_balance("saturation", self.sat.value() / 100.0)
        self.engine.set_timestamp(self.ts_chk.isChecked())
        self._save_ui_settings()

    def _update_label(self, *_args):
        self.engine.set_label(
            self.name_edit.text(),
            self.order_edit.text(),
            self.label_chk.isChecked(),
        )
        self._save_ui_settings()

    # ------------------------------------------------------------------
    # hardware camera controls (V4L2)
    # ------------------------------------------------------------------

    @staticmethod
    def _ctrl_stem(name: str) -> str:
        words = re.sub(r"[^a-z0-9]+", " ", name.lower()).split()
        return "".join(w for w in words if w not in ("auto", "automatic"))

    def _hw_set(self, path, ctrl, value):
        if v4l2.set_ctrl(path, ctrl.id, int(value)):
            self.settings.setValue(f"hw/{path}/{ctrl.name}", int(value))

    def _build_controls(self, path):
        while self.ctrls_layout.count():
            item = self.ctrls_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for t in self._hw_timers.values():
            t.stop()
            t.deleteLater()
        self._hw_timers = {}
        ctrls = v4l2.list_controls(path)
        self.cam_btn.setVisible(bool(ctrls))
        if not ctrls:
            self.ctrls_frame.setVisible(False)
            return

        def get(c):
            try:
                return v4l2.get_ctrl(path, c.id)
            except OSError:
                return c.default

        def current(c):
            cur = get(c)
            key = f"hw/{path}/{c.name}"
            if self.settings.contains(key):
                try:
                    want = int(self.settings.value(key))
                except (TypeError, ValueError):
                    want = cur
                if want != cur and c.minimum <= want <= c.maximum:
                    if v4l2.set_ctrl(path, c.id, want):
                        return want
            return cur

        widgets = {}   # ctrl -> widget
        val_lbls = {}  # ctrl -> QLabel
        row = 0
        for c in ctrls:
            if c.is_class:
                lab = QLabel(f"<b>{c.name}</b>")
                self.ctrls_layout.addWidget(lab, row, 0, 1, 3)
                row += 1
                continue
            cur = current(c)
            self.ctrls_layout.addWidget(QLabel(c.name), row, 0)
            if c.type == v4l2.T_BOOL:
                w = QCheckBox()
                w.setChecked(bool(cur))
                w.toggled.connect(
                    lambda on, c=c: self._hw_set(path, c, on)
                )
                self.ctrls_layout.addWidget(w, row, 1, 1, 2)
            elif c.type in (v4l2.T_MENU, v4l2.T_INT_MENU):
                w = QComboBox()
                for idx, label in sorted(c.menu.items()):
                    w.addItem(label, idx)
                pos = w.findData(cur)
                w.setCurrentIndex(pos if pos >= 0 else 0)
                w.activated[int].connect(
                    lambda i, w=w, c=c: self._hw_set(path, c, w.itemData(i))
                )
                self.ctrls_layout.addWidget(w, row, 1, 1, 2)
            elif c.type == v4l2.T_BUTTON:
                w = QPushButton("Trigger")
                w.clicked.connect(lambda _=None, c=c: self._hw_set(path, c, 1))
                self.ctrls_layout.addWidget(w, row, 1, 1, 2)
            else:
                w = QSlider(Qt.Horizontal)
                w.setRange(c.minimum, c.maximum)
                if c.step > 0:
                    w.setSingleStep(c.step)
                w.setValue(cur)
                vl = QLabel(str(cur))
                vl.setMinimumWidth(40)
                vl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                t = QTimer(self)
                t.setSingleShot(True)
                t.setInterval(120)
                t.timeout.connect(
                    lambda c=c, w=w, vl=vl: (
                        vl.setText(str(w.value())),
                        self._hw_set(path, c, w.value()),
                    )
                )
                self._hw_timers[c.id] = t
                w.valueChanged.connect(lambda _v, t=t: t.start())
                self.ctrls_layout.addWidget(w, row, 1)
                self.ctrls_layout.addWidget(vl, row, 2)
                val_lbls[c] = vl
            widgets[c] = w
            row += 1

        # auto/manual dependencies: an "auto" control gates widgets whose
        # name shares its stem (e.g. Auto Exposure -> Exposure Time, Absolute)
        for c, w in widgets.items():
            if "auto" not in c.name.lower():
                continue
            stem = self._ctrl_stem(c.name)
            deps = [
                widgets[o]
                for o in widgets
                if o is not c
                and re.sub(r"[^a-z0-9]", "", o.name.lower()).startswith(stem)
            ]
            if not deps:
                continue
            if c.type == v4l2.T_BOOL:
                state = lambda w=w: w.isChecked()
                w.toggled.connect(lambda *_a, s=state, d=deps: self._hw_deps(s, d))
            else:
                state = lambda w=w: "manual" not in w.currentText().lower()
                w.activated[int].connect(lambda *_a, s=state, d=deps: self._hw_deps(s, d))
            self._hw_deps(state, deps)

    @staticmethod
    def _hw_deps(state_fn, widgets):
        enabled = not state_fn()
        for w in widgets:
            w.setEnabled(enabled)

    # ------------------------------------------------------------------
    # recording / snapshot
    # ------------------------------------------------------------------

    def _toggle_recording(self):
        if self.engine.recording:
            self.rec_btn.setEnabled(False)
            self.engine.stop_recording()
        else:
            fmt = self.fmt_combo.currentData()
            path = self._unique_path("tuxcam", fmt)
            self.engine.start_recording(path, fmt)

    def _snapshot(self):
        img = self.engine.last_frame
        if img is None or img.isNull():
            self.status_label.setText("No frame to save")
            return
        path = self._unique_path("snap", "png")
        if img.save(path):
            self.status_label.setText(f"Saved {path}")
        else:
            self.status_label.setText("Snapshot failed")

    def _on_rec_started(self):
        self.video.recording = True
        self.rec_btn.setText("■  Stop")
        self.rec_btn.setStyleSheet("font-weight: bold; color: #d21e1e;")
        for w in (
            self.device_combo,
            self.mode_combo,
            self.fmt_combo,
            self.refresh_btn,
            self.outdir_btn,
            self.audio_combo,
        ):
            w.setEnabled(False)
        self.status_label.setText("Recording…")

    def _on_rec_finished(self, path):
        self.video.recording = False
        self.rec_btn.setText("●  Record")
        self.rec_btn.setStyleSheet("font-weight: bold;")
        self.rec_btn.setEnabled(True)
        for w in (
            self.device_combo,
            self.mode_combo,
            self.fmt_combo,
            self.refresh_btn,
            self.outdir_btn,
            self.audio_combo,
        ):
            w.setEnabled(True)
        self.rec_label.setText("")
        self.status_label.setText(f"Saved {path}")

    def _on_rec_stats(self, secs, size):
        m, s = divmod(int(secs), 60)
        h, m = divmod(m, 60)
        mb = size / 1_000_000
        self.rec_label.setText(f"  ● {h:02d}:{m:02d}:{s:02d}   {mb:.1f} MB")
        self.video.update()

    def _on_error(self, msg):
        self.status_label.setText(msg)

    # ------------------------------------------------------------------
    # misc ui
    # ------------------------------------------------------------------

    def _pick_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "Save recordings to", self._outdir())
        if d:
            self.settings.setValue("output_dir", d)
            self.status_label.setText(f"Saving to {d}")

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape and self.isFullScreen():
            self.showNormal()
            return
        super().keyPressEvent(ev)

    def _reset_adjust(self):
        self.bright.setValue(0)
        self.contrast.setValue(100)
        self.sat.setValue(100)

    def _load_ui_settings(self):
        self.fmt_combo.setCurrentIndex(
            int(self.settings.value("fmt_idx", 0))
        )
        self.ts_chk.setChecked(
            self.settings.value("timestamp", "true") == "true"
        )
        self.zoom.setValue(int(self.settings.value("zoom", 100)))
        self.label_chk.setChecked(
            self.settings.value("label_on", "false") == "true"
        )
        self.name_edit.setText(self.settings.value("label_name", ""))
        self.order_edit.setText(self.settings.value("label_order", ""))

    def _save_ui_settings(self):
        if self._building:
            return
        d = self.device_combo.currentData()
        m = self.mode_combo.currentData()
        if d:
            self.settings.setValue("device_path", d.path)
        if m:
            self.settings.setValue("mode_label", m.label)
        self.settings.setValue("fmt_idx", self.fmt_combo.currentIndex())
        self.settings.setValue("timestamp", "true" if self.ts_chk.isChecked() else "false")
        self.settings.setValue("zoom", self.zoom.value())
        a = self.audio_combo.currentData()
        if a is not None:
            self.settings.setValue("audio_device", a)
        self.settings.setValue(
            "label_on", "true" if self.label_chk.isChecked() else "false"
        )
        self.settings.setValue("label_name", self.name_edit.text())
        self.settings.setValue("label_order", self.order_edit.text())

    # ------------------------------------------------------------------
    def closeEvent(self, ev):
        self.engine.stop()
        super().closeEvent(ev)
