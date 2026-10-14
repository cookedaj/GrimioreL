# SPDX-License-Identifier: GPL-3.0-or-later
"""ShotL from a terminal or a hotkey.

    grimoire-shotl                                          open the window
    grimoire-shotl region|window|full|screen [options]      take a shot (full: all screens, screen: the one under
                                                            the pointer)
        --delay N        wait N seconds first
        --edit | --copy | --save   what to do after (default: the "After" setting in ShotL)
    grimoire-shotl record [toggle|start|stop|status] [--sound] [--pick]
                                                            start or stop a recording (--pick: choose the screen
                                                            again instead of reusing the last one)

Bind any of these to a key in System Settings → Keyboard → Shortcuts → Add New → Command.
"""
import sys
import time

MODES = ("region", "window", "full", "screen")


def shoot(mode: str, args: list[str]) -> int:
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMainWindow

    from grimoire.app import style_app
    from grimoire.fsutil import tilde
    from grimoire.spells.shotl import capture, region, shots
    from grimoire.spells.shotl.record import _notify
    from grimoire.standalone import app_icon

    settings = shots.load()
    after = next((a[2:] for a in args if a in ("--edit", "--copy", "--save")), settings["after"])
    delay = settings["delay"]
    if "--delay" in args:
        try:
            delay = max(0, int(args[args.index("--delay") + 1]))
        except (IndexError, ValueError):
            print("--delay needs a number of seconds")
            return 2
    app = QApplication(sys.argv[:1])
    app.setApplicationName("ShotL")
    app.setDesktopFileName("grimoire-shotl")
    style_app(app)
    app.setWindowIcon(QIcon(app_icon("shot")))
    time.sleep(delay)
    try:
        img = capture.take(capture.grab("full" if mode == "region" else mode,
                                        pointer=settings["pointer"] and mode != "region"))
    except capture.CaptureError as e:
        _notify("No screenshot", str(e))
        print(e)
        return 1
    if mode == "region":
        rect = region.pick(img)
        if not rect:
            return 1
        img = img.copy(rect)

    if after == "edit":
        from grimoire.spells.shotl.editor import Editor

        class Win(QMainWindow):
            def closeEvent(self, e):
                ed.blockSignals(True)               # request_close() emits closed, which closes this window
                ok = not ed.unsaved() or ed.request_close()
                ed.blockSignals(False)
                e.accept() if ok else e.ignore()

        win = Win()
        win.setWindowTitle("ShotL")
        ed = Editor()
        ed.setContentsMargins(16, 12, 16, 8)
        ed.load(img)
        ed.closed.connect(win.close)
        ed.toast.connect(lambda t: win.statusBar().showMessage(t, 5000))
        win.setCentralWidget(ed)
        win.resize(min(1400, max(900, img.width() // 2 + 120)), min(900, max(600, img.height() // 2 + 180)))
        win.show()
        ed.canvas.setFocus()
        code = app.exec()
        if app.clipboard().ownsClipboard():                # copied in the editor: keep it pasteable
            return capture.hold_clipboard(app)
        return code

    dest = shots.new_path()
    if not img.save(str(dest), "PNG"):
        shots.release(dest)
        print(f"couldn't write {dest}")
        return 1
    shots.add(dest)
    print(dest)
    if after == "copy":
        how = capture.copy_image(img)
        _notify("Screenshot copied", f"Also saved as {tilde(dest)}")
        if how == "qt":
            return capture.hold_clipboard(app)          # Wayland drops the image if its owner quits
        return 0
    _notify("Screenshot saved", tilde(dest))
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        from grimoire.standalone import run
        run("shotl")
        return 0
    if argv[0] in MODES:
        return shoot(argv[0], argv[1:])
    if argv[0] == "record":
        from grimoire.spells.shotl import record
        return record.main(argv[1:] if argv[1:2] and not argv[1].startswith("-") else ["toggle"] + argv[1:])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
