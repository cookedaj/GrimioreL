"""VaultL as its own window (this is what opens when you open a folder anywhere).

    python3 -m grimoire.spells.vaultl [folder or file or file:// URL]
    python3 -m grimoire.spells.vaultl tidy [run|undo|enable|disable|status]
"""
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


def main(argv: list[str]):
    if argv[:1] == ["tidy"]:                                   # a folder called tidy: pass ./tidy
        from grimoire.spells.vaultl import cli
        return cli.main(argv[1:])

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMainWindow

    from grimoire.app import style_app
    from grimoire.spells.vaultl.page import VaultLPage
    from grimoire.standalone import app_icon

    app = QApplication(sys.argv[:1])
    app.setApplicationName("VaultL")
    app.setDesktopFileName("grimoire-vaultl")
    style_app(app)
    app.setWindowIcon(QIcon(app_icon("vault")))
    arg = argv[0] if argv else ""
    if arg.startswith("file://"):
        arg = unquote(urlparse(arg).path)
    start = Path(arg).expanduser() if arg else Path.home()
    select = None
    if start.exists() and not start.is_dir():
        start, select = start.parent, start
    win = QMainWindow()
    page = VaultLPage(start if start.is_dir() else Path.home(), standalone=True)
    win.setCentralWidget(page)
    win.resize(1280, 800)
    win.setMinimumSize(820, 520)
    win.show()
    if select:
        page.reveal(select)
    sys.exit(app.exec())


if __name__ == "__main__":
    main(sys.argv[1:])
