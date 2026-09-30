"""GUI entry point."""

from __future__ import annotations

import sys


def main() -> int:
    # WebEngine must be imported before QApplication is created.
    try:
        import PySide6.QtWebEngineWidgets  # noqa: F401
    except ImportError:
        pass
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from .. import __version__
    from ..config import APP_NAME
    from .main_window import MainWindow
    from .theme import app_icon, apply_theme

    if sys.platform == "win32":
        try:  # Own taskbar group/icon instead of python.exe's
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_NAME}.{__version__}")
        except Exception:  # noqa: BLE001
            pass

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    apply_theme(app)
    app.setWindowIcon(app_icon())
    window = MainWindow()
    window.show()
    return app.exec()
