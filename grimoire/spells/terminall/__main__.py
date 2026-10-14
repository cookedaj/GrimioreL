"""TerminalL as its own window.

    python3 -m grimoire.spells.terminall [folder or file:// URL]     open with a tab in that folder
"""
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


def main(argv: list[str]):
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox

    from grimoire.app import style_app
    from grimoire.spells.terminall.page import TerminalLPage
    from grimoire.standalone import app_icon

    app = QApplication(sys.argv[:1])
    app.setApplicationName("TerminalL")
    app.setDesktopFileName("grimoire-terminall")
    style_app(app)
    app.setWindowIcon(QIcon(app_icon("terminall")))
    arg = argv[0] if argv else ""
    if arg.startswith("file://"):
        arg = unquote(urlparse(arg).path)
    start = Path(arg).expanduser().resolve() if arg else Path.cwd()
    if start.exists() and not start.is_dir():
        start = start.parent

    class Window(QMainWindow):
        def closeEvent(self, e):
            busy = page.busy() if page.ok else []
            if busy and QMessageBox.question(
                    self, "TerminalL", f"{', '.join(sorted(set(busy)))} still running. Close TerminalL anyway?",
                    QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Close,
                    QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Close:
                return e.ignore()
            if page.ok:
                page.close_all()
            e.accept()

    win = Window()
    win.setWindowTitle("TerminalL")
    page = TerminalLPage(start if start.is_dir() else Path.home(), standalone=True)
    if page.ok:
        page.titleChanged.connect(win.setWindowTitle)
    win.setCentralWidget(page)
    win.resize(1100, 700)
    win.setMinimumSize(520, 320)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main(sys.argv[1:])
