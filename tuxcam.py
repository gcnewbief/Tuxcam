#!/usr/bin/env python3
"""Tuxcam — a simple webcam viewer / recorder for Linux."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from tuxcam.window import MainWindow


def _find_icon():
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (
        os.path.join(here, "packaging", "tuxcam.png"),   # dev checkout
        os.path.join(here, "..", "..", "tuxcam.png"),    # AppImage root
    ):
        if os.path.exists(cand):
            return cand
    return None


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Tuxcam")
    app.setOrganizationName("Tuxcam")
    icon = _find_icon()
    if icon:
        app.setWindowIcon(QIcon(icon))
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
