"""Spells as their own apps: one window per spell, plus its own launcher in the app menu.

    python3 -m grimoire.standalone <spell-id>          open that spell in its own window
    python3 -m grimoire.standalone install <id>|all    add launchers (command, icon, menu entry)
    python3 -m grimoire.standalone uninstall <id>      remove the menu entry and icon
    python3 -m grimoire.standalone refresh             rewrite launchers that are already installed

Each spell's command is bin/grimoire-<id>. Uninstalling keeps the command in ~/.local/bin, because SightsL's autostart
and VaultL's auto-tidy timer call it.
"""
import os
import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMainWindow

from grimoire.paths import DATA
from grimoire.spells import SPELLS

_app = None
# launchers point at the installed copy (install.sh puts it in ~/.local/share/grimoire/app), so they keep working
# when the download is moved or deleted; a checkout that was never installed links to itself
INSTALLED = DATA / "app" / "bin"
BIN = INSTALLED if (INSTALLED / "grimoire").is_file() else Path(__file__).resolve().parent.parent / "bin"
# extra desktop-entry lines; VaultL is also the default folder handler
EXTRA = {"vaultl": {"GenericName": "File Manager", "Categories": "Utility;System;FileTools;FileManager;",
                    "MimeType": "inode/directory;"},
         "terminall": {"GenericName": "Terminal", "Categories": "System;TerminalEmulator;"}}
# spells merged into another: their menu entries stay (hidden), since the system's default-app setting may name them
MERGED = {"filel": "vaultl", "tidyl": "vaultl"}


def _spell(sid: str):
    return next((s for s in SPELLS if s.id == sid), None)


def _paths(sid: str) -> tuple[Path, Path, Path]:
    """(command link, menu entry, icon) for a spell; read $HOME late so a sandbox HOME works in tests."""
    share = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")    # as install.sh does
    return (Path.home() / ".local/bin" / f"grimoire-{sid}", share / "applications" / f"grimoire-{sid}.desktop",
            share / "icons/hicolor/256x256/apps" / f"grimoire-{sid}.png")


def available(sid: str) -> bool:
    """A spell can stand alone once it has its bin/grimoire-<id> command."""
    return (BIN / f"grimoire-{sid}").is_file()


def installed(sid: str) -> bool:
    return _paths(sid)[1].exists()


def app_icon(glyph_name: str, size: int = 256) -> QPixmap:
    """The spell's line glyph in white on a black rounded tile, so each app reads apart in the menu."""
    from grimoire.glyphs import _pixmap
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QColor("#2a2a2a"))
    p.setBrush(QColor("#000000"))
    p.drawRoundedRect(QRectF(size * .06, size * .06, size * .88, size * .88), size * .2, size * .2)
    inner = int(size * .56)
    p.drawPixmap((size - inner) // 2, (size - inner) // 2, _pixmap(glyph_name, "#ffffff", inner))
    p.end()
    return pm


def install(sid: str):
    spell = _spell(sid)
    if not spell or not available(sid):
        raise ValueError(f"{sid} has no standalone command yet")
    cmd, entry, icon = _paths(sid)
    for d in (cmd.parent, entry.parent, icon.parent):
        d.mkdir(parents=True, exist_ok=True)
    src = BIN / f"grimoire-{sid}"
    src.chmod(0o755)
    if cmd.is_symlink() or not cmd.exists():          # never replace a real file someone put there
        cmd.unlink(missing_ok=True)
        cmd.symlink_to(src)
    global _app
    _app = QApplication.instance() or QApplication([])   # drawing the icon needs an app (CLI use)
    app_icon(spell.icon).save(str(icon))
    fields = {"Type": "Application", "Name": spell.name, "GenericName": "Grimoire spell", "Comment": spell.tagline,
              "Exec": f"{cmd} %u" if sid in EXTRA else str(cmd), "Icon": f"grimoire-{sid}", "Terminal": "false",
              "Categories": "Utility;", "StartupWMClass": f"grimoire-{sid}"} | EXTRA.get(sid, {})
    entry.write_text("[Desktop Entry]\n" + "".join(f"{k}={v}\n" for k, v in fields.items()))
    for old, new in MERGED.items():
        if new == sid:
            _hide_merged(old, fields)
    _refresh_menu()


def _hide_merged(old: str, fields: dict):
    """Turn an installed entry of a merged spell (grimoire-filel.desktop) into a hidden alias of its new home, so
    'open folder' keeps working through the old name without two apps showing in the menu."""
    cmd, entry, icon = _paths(old)
    if not entry.exists():
        return
    if not cmd.exists() and not cmd.is_symlink() and (BIN / cmd.name).is_file():
        cmd.symlink_to(BIN / cmd.name)  # the alias command the entry (and TidyL's timer) runs
    alias = fields | {"Exec": f"{cmd} %u" if old == "filel" else str(cmd), "NoDisplay": "true"}
    if old != "filel":
        alias.pop("MimeType", None)     # only FileL ever opened folders
    entry.write_text("[Desktop Entry]\n" + "".join(f"{k}={v}\n" for k, v in alias.items()))
    icon.unlink(missing_ok=True)        # generated by Grimoire; the alias uses the new spell's icon


def uninstall(sid: str):
    _, entry, icon = _paths(sid)
    entry.unlink(missing_ok=True)       # files Grimoire generated itself, not user files
    icon.unlink(missing_ok=True)
    _refresh_menu()


def _refresh_menu():
    import subprocess
    apps = _paths("x")[1].parent
    for c in (["update-desktop-database", str(apps)], ["kbuildsycoca6", "--noincremental"]):
        try:
            subprocess.run(c, capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            pass


def run(sid: str):
    from grimoire.app import style_app
    sid = MERGED.get(sid, sid)
    spell = _spell(sid)
    if not spell:
        sys.exit(f"no spell called {sid!r}; try: {', '.join(s.id for s in SPELLS)}")
    app = QApplication(sys.argv[:1])
    app.setApplicationName(spell.name)
    app.setDesktopFileName(f"grimoire-{sid}")
    style_app(app)
    app.setWindowIcon(QIcon(app_icon(spell.icon)))
    win = QMainWindow()
    win.setWindowTitle(spell.name)
    win.setCentralWidget(spell.page())
    win.resize(1280, 820)
    win.setMinimumSize(1000, 640)
    win.show()
    sys.exit(app.exec())


def main(argv: list[str]):
    if argv[:1] in (["install"], ["uninstall"]) and len(argv) == 2:
        ids = [s.id for s in SPELLS if available(s.id)] if argv[1] == "all" else [argv[1]]
        for sid in ids:
            (install if argv[0] == "install" else uninstall)(sid)
            print(f"{argv[0]}ed {sid}")
    elif argv == ["refresh"]:
        for s in SPELLS:
            if available(s.id) and installed(s.id):
                install(s.id)
    elif len(argv) == 1:
        run(argv[0])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
