"""Render the Grimoire SDDM theme offscreen with a fake SDDM backend (for MuraL's previews).

    QT_QPA_PLATFORM=offscreen python3 -m grimoire.spells.mural.sddmshot THEME_DIR OUT.png
"""
import configparser
import sys
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickView


class FakeSddm(QObject):
    loginFailed = Signal()
    loginSucceeded = Signal()

    def _yes(self):
        return True

    canSuspend = Property(bool, _yes, constant=True)
    canReboot = Property(bool, _yes, constant=True)
    canPowerOff = Property(bool, _yes, constant=True)

    @Slot(str, str, int)
    def login(self, *_):
        self.loginFailed.emit()

    @Slot()
    def suspend(self): pass

    @Slot()
    def reboot(self): pass

    @Slot()
    def powerOff(self): pass


class FakeUsers(QObject):
    def __init__(self, user):
        super().__init__()
        self._user = user

    lastUser = Property(str, lambda self: self._user, constant=True)


class FakeSessions(QObject):
    lastIndex = Property(int, lambda self: 0, constant=True)


class FakeKeyboard(QObject):
    capsLock = Property(bool, lambda self: False, constant=True)


def main():
    theme, out = Path(sys.argv[1]), sys.argv[2]
    app = QGuiApplication(sys.argv)
    conf = configparser.ConfigParser()
    conf.read(theme / "theme.conf")
    view = QQuickView()
    ctx = view.rootContext()
    keep = [FakeSddm(), FakeUsers(Path.home().name), FakeSessions(), FakeKeyboard()]
    for name, obj in zip(("sddm", "userModel", "sessionModel", "keyboard"), keep):
        ctx.setContextProperty(name, obj)
    ctx.setContextProperty("config", dict(conf["General"]))
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    view.resize(1920, 1080)
    view.setSource(QUrl.fromLocalFile(str(theme / "Main.qml")))
    if view.status() != QQuickView.Status.Ready:
        for e in view.errors():
            print(e.toString(), file=sys.stderr)
        sys.exit(1)
    view.show()
    QTimer.singleShot(700, lambda: (view.grabWindow().save(out), app.quit()))
    app.exec()


if __name__ == "__main__":
    main()
