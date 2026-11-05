#!/usr/bin/env python3
"""Tuxcam — a simple webcam viewer / recorder for Linux."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

from tuxcam.window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Tuxcam")
    app.setOrganizationName("Tuxcam")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
