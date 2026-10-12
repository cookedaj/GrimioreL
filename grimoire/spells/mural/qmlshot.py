"""Render a splash QML to a PNG offscreen (used for MuraL's previews).

    QT_QPA_PLATFORM=offscreen python3 -m grimoire.spells.mural.qmlshot SPLASH.qml OUT.png [STAGE] [W] [H]
"""
import sys

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickView


def main():
    qml, out = sys.argv[1], sys.argv[2]
    stage = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    w = int(sys.argv[4]) if len(sys.argv) > 4 else 1280
    h = int(sys.argv[5]) if len(sys.argv) > 5 else 720
    app = QGuiApplication(sys.argv)
    view = QQuickView()
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    view.resize(w, h)
    view.setSource(QUrl.fromLocalFile(qml))
    if view.status() != QQuickView.Status.Ready:
        for e in view.errors():
            print(e.toString(), file=sys.stderr)
        sys.exit(1)
    view.show()
    view.rootObject().setProperty("stage", stage)

    def grab():
        view.grabWindow().save(out)
        app.quit()

    QTimer.singleShot(1600, grab)        # let fade-ins / Behaviors settle
    app.exec()


if __name__ == "__main__":
    main()
