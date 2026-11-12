"""Shared camera-control types used by the per-platform control backends.

v4l2.py (Linux) and win_controls.py (Windows) both expose
list_controls/get_ctrl/set_ctrl using these types so window.py can build
the hardware-controls panel without knowing which OS it's on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
