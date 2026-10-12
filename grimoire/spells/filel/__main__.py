"""FileL as its own window (this is what opens when you open a folder anywhere).

    python3 -m grimoire.spells.filel [folder or file or file:// URL]
"""
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from PySide6.QtWidgets import QApplication, QMainWindow

from grimoire.app import style_app
from grimoire.spells.filel.page import FileLPage


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("FileL")
    app.setDesktopFileName("grimoire-filel")
    style_app(app)
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg.startswith("file://"):
        arg = unquote(urlparse(arg).path)
    start = Path(arg).expanduser() if arg else Path.home()
    select = None
    if start.exists() and not start.is_dir():
        start, select = start.parent, start
    win = QMainWindow()
    page = FileLPage(start if start.is_dir() else Path.home(), standalone=True)
    win.setCentralWidget(page)
    win.resize(1280, 800)
    win.setMinimumSize(820, 520)
    win.show()
    if select:
        idx = page.model.index(str(select))
        page.view().setCurrentIndex(idx)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
