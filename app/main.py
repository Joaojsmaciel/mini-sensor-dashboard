"""Ponto de entrada do MINI SENSOR DASHBOARD.

Uso:
    python app\\main.py
(ou simplesmente execute run.bat na raiz do projeto)
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

# Garante que o PyQtGraph use o PyQt6 (e não outro binding instalado).
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402
import pyqtgraph as pg  # noqa: E402

from interface.dashboard import DashboardWindow  # noqa: E402
from interface.styles import STYLESHEET, make_font  # noqa: E402
from utils.configuration import APP_NAME, APP_VERSION  # noqa: E402


def install_exception_hook() -> None:
    """Exibe erros inesperados em vez de encerrar a aplicação silenciosamente."""

    def hook(exc_type, exc_value, exc_tb):
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        sys.stderr.write(details)
        app = QApplication.instance()
        if app is not None:
            QMessageBox.critical(None, APP_NAME, f"Erro inesperado:\n\n{exc_value}\n\nDetalhes no console.")

    sys.excepthook = hook


def set_windows_app_id() -> None:
    """Faz o Windows usar o ícone da aplicação na barra de tarefas."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MiniSensorDashboard.App.1")
        except Exception:
            pass


def main() -> int:
    set_windows_app_id()
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setStyle("Fusion")
    app.setFont(make_font(10))
    app.setStyleSheet(STYLESHEET)
    pg.setConfigOptions(antialias=True)
    install_exception_hook()

    window = DashboardWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
