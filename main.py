#!/usr/bin/env python3
"""РадоФМ — графическое интернет-радио для Linux. Запуск: python3 main.py"""
import sys

from PySide6.QtWidgets import QApplication

from radio.ui import STYLE, MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("radiofm")
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
