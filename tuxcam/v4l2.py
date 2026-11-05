"""Minimal V4L2 device control via ioctls — no v4l-utils needed.

Enumerates VIDIOC_QUERYCTRL / QUERYMENU / G_CTRL / S_CTRL directly on the
video device. Multiple opens of the same device are allowed for control
ioctls, so this works while GStreamer is streaming.
"""

from __future__ import annotations

import fcntl
import os
import struct
from dataclasses import dataclass, field


def _ioc(d, t, n, s):
    return (d << 30) | (ord(t) << 8) | n | (s << 16)


def _iowr(t, n, fmt):
    return _ioc(3, t, n, struct.calcsize(fmt))


# struct v4l2_queryctrl { u32 id; u32 type; u8 name[32]; s32 min; s32 max;
#                         u32 step; s32 default; u32 flags; u32 reserved[2]; }
_QUERYCTRL = _iowr("V", 36, "II32siiIiI2I")
# struct v4l2_querymenu { u32 id; u32 index; u8 name[32]; u32 reserved; }
_QUERYMENU = _iowr("V", 37, "II32sI")
# struct v4l2_control { u32 id; s32 value; }
_G_CTRL = _iowr("V", 27, "Ii")
_S_CTRL = _iowr("V", 28, "Ii")

NEXT_CTRL = 0x80000000
FLAG_DISABLED = 0x0002
FLAG_READ_ONLY = 0x0004
FLAG_WRITE_ONLY = 0x0008
FLAG_GRABBED = 0x0800

T_INT = 1
T_BOOL = 2
T_MENU = 3
T_BUTTON = 4
T_CLASS = 6
T_INT_MENU = 9


@dataclass(eq=False)
class Ctrl:
    id: int
    type: int
    name: str
    minimum: int
    maximum: int
    step: int
    default: int
    flags: int
    menu: dict = field(default_factory=dict)  # index -> label

    @property
    def is_class(self) -> bool:
        return self.type == T_CLASS


def _cstr(b: bytes) -> str:
    return b.split(b"\0", 1)[0].decode("utf-8", "replace")


def list_controls(path: str) -> list:
    """All user-adjustable controls on the device (plus class headers)."""
    out = []
    try:
        fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
    except OSError:
        return out
    try:
        cid = NEXT_CTRL
        while True:
            buf = bytearray(68)
            struct.pack_into("I", buf, 0, cid)
            try:
                fcntl.ioctl(fd, _QUERYCTRL, buf, True)
            except OSError:
                break
            cid, ctype, name, mn, mx, step, dflt, flags = struct.unpack_from(
                "II32siiIiI", buf, 0
            )
            if flags & FLAG_DISABLED:
                cid |= NEXT_CTRL
                continue
            if ctype == T_CLASS:
                out.append(Ctrl(cid, ctype, _cstr(name), 0, 0, 0, 0, flags))
            elif ctype in (T_INT, T_BOOL, T_MENU, T_BUTTON, T_INT_MENU) and not (
                flags & FLAG_READ_ONLY
            ):
                c = Ctrl(cid, ctype, _cstr(name), mn, mx, step, dflt, flags)
                if ctype in (T_MENU, T_INT_MENU):
                    for idx in range(mn, min(mx, mn + 64) + 1):
                        mbuf = bytearray(44)
                        struct.pack_into("II", mbuf, 0, cid, idx)
                        try:
                            fcntl.ioctl(fd, _QUERYMENU, mbuf, True)
                        except OSError:
                            continue
                        if ctype == T_INT_MENU:
                            val = struct.unpack_from("q", mbuf, 8)[0]
                            c.menu[idx] = str(val)
                        else:
                            c.menu[idx] = _cstr(mbuf[8:])
                out.append(c)
            cid |= NEXT_CTRL
    finally:
        os.close(fd)
    return out


def get_ctrl(path: str, cid: int):
    fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
    try:
        buf = bytearray(8)
        struct.pack_into("I", buf, 0, cid)
        fcntl.ioctl(fd, _G_CTRL, buf, True)
        return struct.unpack_from("i", buf, 4)[0]
    finally:
        os.close(fd)


def set_ctrl(path: str, cid: int, value: int) -> bool:
    try:
        fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
    except OSError:
        return False
    try:
        buf = bytearray(8)
        struct.pack_into("II", buf, 0, cid, value & 0xFFFFFFFF)
        fcntl.ioctl(fd, _S_CTRL, buf, True)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)
