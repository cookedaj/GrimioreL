"""Small widgets shared by several spells."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QWidget


class Slider(QWidget):
    """Label + slider + value, in one row."""

    def __init__(self, lo, hi, suffix="", on_change=None):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.s = QSlider(Qt.Orientation.Horizontal)
        self.s.setRange(lo, hi)
        self.v = QLabel()
        self.v.setObjectName("Muted")
        self.v.setFixedWidth(44)
        self.v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.suffix = suffix
        lay.addWidget(self.s, 1)
        lay.addWidget(self.v)
        self.s.valueChanged.connect(lambda x: self.v.setText(f"{x}{suffix}"))
        if on_change:
            self.s.valueChanged.connect(on_change)

    def value(self):
        return self.s.value()

    def setValue(self, x):
        self.s.setValue(x)
        self.v.setText(f"{x}{self.suffix}")
