"""Black & white look shared by every spell."""

from grimoire.paths import ASSETS

FONT = "IBM Plex Sans"

QSS = """
* { font-family: "IBM Plex Sans"; font-size: 13px; color: #e8e8e8; }
QMainWindow, QWidget#Page, QStackedWidget { background: #0b0b0b; }
QWidget#Sidebar { background: #050505; border-right: 1px solid #1a1a1a; }
QLabel { background: transparent; }
QLabel#Title { font-size: 26px; font-weight: 600; color: #ffffff; }
QLabel#Subtitle { color: #8c8c8c; }
QLabel#Section { color: #6f6f6f; font-size: 11px; font-weight: 600; }
QLabel#Muted { color: #8c8c8c; }
QLabel#Muted:disabled, QLabel:disabled { color: #4a4a4a; }
QLabel#Key { font-family: "IBM Plex Mono"; font-size: 11px; color: #d0d0d0; background: #141414;
             border: 1px solid #2e2e2e; border-bottom-width: 2px; border-radius: 5px; padding: 2px 7px; }

QPushButton {
    background: transparent; border: 1px solid #2e2e2e; border-radius: 6px; padding: 8px 14px;
}
QPushButton:hover { border-color: #8a8a8a; }
QPushButton:pressed { background: #151515; }
QPushButton:disabled { color: #4a4a4a; border-color: #1f1f1f; }
QPushButton#Primary { background: #f2f2f2; color: #000000; border: none; font-weight: 600; }
QPushButton#Primary:hover { background: #ffffff; }
QPushButton#Primary:disabled { background: #2a2a2a; color: #555555; }

QPushButton#Pill { border-radius: 13px; padding: 4px 14px; font-size: 11px; min-height: 16px; }
QPushButton#Pill[on="false"] { background: #f2f2f2; color: #000000; border: 1px solid #f2f2f2; border-radius: 13px; font-weight: 600; }
QPushButton#Pill[on="false"]:hover { background: #ffffff; border-color: #ffffff; }
QPushButton#Pill[on="true"] { color: #8c8c8c; border-color: #2a2a2a; }
QPushButton#Pill[on="true"]:hover { color: #ffffff; border-color: #8a8a8a; }

QWidget#Rail { background: #030303; border-right: 1px solid #161616; }
QPushButton#RailItem { border: none; border-radius: 12px; padding: 0; background: transparent; }
QPushButton#RailItem:hover { background: #121212; }
QPushButton#RailItem:checked { background: #1e1e1e; }
QLabel#Tiny { color: #4a4a4a; font-size: 10px; }
QToolButton#RailVersion { border: none; background: transparent; color: #4a4a4a; font-size: 10px; padding: 2px; }
QToolButton#RailVersion:hover { color: #bdbdbd; }
QToolButton#RailVersion[avail="true"] { color: #ffffff; }
QDialog#WhatsNew { background: #0b0b0b; }
QLabel#ChangeTitle { font-size: 14px; font-weight: 600; color: #ffffff; }
QFrame#Rule { background: #1c1c1c; border: none; }

QFrame#SubNav, QScrollArea > QWidget > QWidget#SubNav { background: #070707; }
QScrollArea { border: none; background: transparent; }
QFrame#SubNav { border-right: 1px solid #161616; }
QLabel#NavSection { color: #555555; font-size: 10px; font-weight: 700; padding: 6px 10px 4px 10px; }
QPushButton#SubNavItem {
    text-align: left; border: none; border-radius: 8px; padding: 8px 10px; color: #9a9a9a; background: transparent;
}
QPushButton#SubNavItem:hover { color: #ffffff; background: #101010; }
QPushButton#SubNavItem:checked { color: #ffffff; background: #1a1a1a; }
QLabel#PageHeading { font-size: 22px; font-weight: 600; color: #ffffff; padding-bottom: 2px; }
QLabel#Hero { font-size: 34px; font-weight: 300; color: #ffffff; }
QLabel#Status { color: #bdbdbd; font-size: 12px; border-top: 1px solid #1f1f1f; padding-top: 10px; }

QPushButton#Nav {
    text-align: left; border: none; border-left: 2px solid transparent; border-radius: 0;
    padding: 10px 20px; color: #8c8c8c;
}
QPushButton#Nav:hover { color: #ffffff; }
QPushButton#Nav:checked { color: #ffffff; border-left: 2px solid #ffffff; background: #0f0f0f; }

QPushButton#Tab {
    border: none; border-bottom: 2px solid transparent; border-radius: 0; padding: 8px 14px; color: #8c8c8c;
}
QPushButton#Tab:hover { color: #ffffff; }
QPushButton#Tab:checked { color: #ffffff; border-bottom: 2px solid #ffffff; }

QPushButton#Segment {
    border: 1px solid #2e2e2e; border-radius: 0; padding: 6px 14px; color: #8c8c8c; background: transparent;
}
QPushButton#Segment[pos="first"] { border-top-left-radius: 6px; border-bottom-left-radius: 6px; }
QPushButton#Segment[pos="last"] { border-top-right-radius: 6px; border-bottom-right-radius: 6px; }
QPushButton#Segment[pos="mid"], QPushButton#Segment[pos="last"] { border-left: none; }
QPushButton#Segment:checked { background: #f2f2f2; color: #000000; border-color: #f2f2f2; }

QPushButton#Link { border: none; text-align: left; padding: 4px 6px; color: #d0d0d0; }
QPushButton#Link:hover { color: #ffffff; text-decoration: underline; }
QTableWidget, QTreeWidget { background: #0b0b0b; border: 1px solid #1c1c1c; border-radius: 8px; gridline-color: #1a1a1a; }
QTableWidget::item, QTreeWidget::item { padding: 6px; border: none; }
QTableWidget::item:selected, QTreeWidget::item:selected { background: #1e1e1e; color: #ffffff; }
QHeaderView::section { background: #0e0e0e; color: #6f6f6f; border: none; border-bottom: 1px solid #1c1c1c;
                       padding: 8px; font-size: 11px; font-weight: 600; }
QListWidget#Plain::item { padding: 6px; }

QListWidget#Places { background: transparent; border: none; }
QListWidget#Places::item { padding: 7px 8px; border-radius: 8px; color: #a8a8a8; border: none; }
QListWidget#Places::item:hover { background: #101010; color: #ffffff; }
QListWidget#Places::item:selected { background: #1a1a1a; color: #ffffff; }
QFrame#Crumbs { background: #121212; border: 1px solid #262626; border-radius: 8px; }
QPushButton#Crumb { border: none; padding: 4px 8px; color: #cfcfcf; border-radius: 6px; }
QPushButton#Crumb:hover { background: #1e1e1e; color: #ffffff; }
QToolButton#Tool { border: none; border-radius: 8px; padding: 6px; }
QToolButton#Tool:hover { background: #151515; }
QToolButton#Tool:checked { background: #1f1f1f; }
QListView#FileGrid, QTreeView#FileDetails { background: #0b0b0b; border: none; }
QTreeView#FileDetails::item { padding: 4px 2px; }
QTreeView#FileDetails::item:selected { background: #222222; }
QTreeView#FileDetails::item:hover { background: #121212; }
QLabel#Mono { font-family: "IBM Plex Mono"; font-size: 11px; color: #a8a8a8; background: #080808;
              border: 1px solid #1c1c1c; border-radius: 6px; padding: 8px; }
QSplitter::handle { background: #1a1a1a; }

QFrame#Card { background: #101010; border: 1px solid #1f1f1f; border-radius: 10px; }
QFrame#Card:hover { border-color: #5a5a5a; }
QFrame#CardSoon { background: transparent; border: 1px dashed #262626; border-radius: 10px; }
QFrame#Panel { background: #0e0e0e; border-left: 1px solid #1a1a1a; }

QListWidget { background: #0b0b0b; border: none; outline: none; }
QListWidget::item { border: 1px solid transparent; border-radius: 8px; padding: 6px; color: #9a9a9a; }
QListWidget::item:hover { border-color: #333333; }
QListWidget::item:selected { border: 1px solid #ffffff; background: #141414; color: #ffffff; }

QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit {
    background: #121212; border: 1px solid #262626; border-radius: 6px; padding: 6px 8px; min-height: 18px;
}
QSpinBox:disabled, QDoubleSpinBox:disabled { color: #4a4a4a; }
QComboBox QAbstractItemView { background: #121212; border: 1px solid #262626; selection-background-color: #2a2a2a; }
QCheckBox { spacing: 10px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #4a4a4a; border-radius: 4px; background: #0b0b0b; }
QCheckBox::indicator:checked { background: #f2f2f2; border-color: #f2f2f2; image: url(@ASSETS@/check.svg); }
QTreeView::indicator, QListView::indicator { width: 14px; height: 14px; border: 1px solid #4a4a4a; border-radius: 4px;
                                            background: #0b0b0b; }
QTreeView::indicator:checked, QListView::indicator:checked { background: #f2f2f2; border-color: #f2f2f2;
                                                             image: url(@ASSETS@/check.svg); }
QTreeView::indicator:indeterminate { background: #6f6f6f; border-color: #6f6f6f; }

QSlider::groove:horizontal { height: 2px; background: #2a2a2a; }
QSlider::sub-page:horizontal { background: #d0d0d0; }
QSlider::handle:horizontal { background: #f2f2f2; width: 14px; height: 14px; margin: -6px 0; border-radius: 7px; }
QSlider::handle:horizontal:disabled { background: #444; }

QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #2a2a2a; border-radius: 4px; min-height: 30px; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 0; }
QScrollBar::handle:horizontal { background: #2a2a2a; border-radius: 4px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QMenu { background: #121212; border: 1px solid #262626; padding: 4px; }
QMenu::item { padding: 6px 18px; border-radius: 4px; }
QMenu::item:selected { background: #2a2a2a; }
QFrame#Row { background: #0f0f0f; border: 1px solid #1c1c1c; border-radius: 10px; }
QFrame#Row:hover { border-color: #333333; }
QFrame#Row[pending="true"] { border: 1px solid #f2f2f2; }
QFrame#Row[muted="true"] { background: transparent; border: 1px solid #161616; }
QLabel#RowTitle { font-size: 14px; font-weight: 600; color: #ffffff; }
QLabel#RowTitle[muted="true"] { color: #8c8c8c; }
QLabel#Value { font-family: "IBM Plex Mono"; font-size: 11px; color: #6f6f6f; }
QLabel#Badge { font-size: 9px; font-weight: 600; letter-spacing: 1px; color: #8c8c8c; border: 1px solid #2a2a2a;
               border-radius: 4px; padding: 1px 6px; }
QLabel#BadgeSolid { font-size: 9px; font-weight: 700; letter-spacing: 1px; color: #000000; background: #f2f2f2;
                    border-radius: 4px; padding: 2px 7px; }
QLabel#Done { color: #6f6f6f; font-size: 12px; padding-right: 4px; }
QLabel#SectionTitle { font-size: 17px; font-weight: 600; color: #ffffff; }
QLabel#GoodLine { color: #6f6f6f; font-size: 12px; }
QLabel#NavName { color: #9a9a9a; }
QLabel#NavName[on="true"] { color: #ffffff; }
QLabel#NavCount { font-family: "IBM Plex Mono"; font-size: 11px; color: #555555; }
QFrame#Stat { background: #0f0f0f; border: 1px solid #1c1c1c; border-radius: 10px; }
QLabel#StatNum { font-size: 28px; font-weight: 300; color: #ffffff; }
QLabel#StatLabel { font-size: 10px; font-weight: 600; letter-spacing: 2px; color: #6f6f6f; }
QFrame#Pending { background: #f2f2f2; border-radius: 10px; }
QLabel#PendingText { color: #000000; font-weight: 500; }
QFrame#Pending QPushButton { color: #000000; border: 1px solid #b5b5b5; background: transparent; }
QFrame#Pending QPushButton:hover { border-color: #000000; }
QFrame#Pending QPushButton#Primary { background: #000000; color: #ffffff; border: none; }
QFrame#Pending QPushButton#Primary:disabled, QFrame#Pending QPushButton:disabled { color: #8c8c8c; background: #d6d6d6; }
QLabel#Toast { color: #e8e8e8; background: #141414; border: 1px solid #2a2a2a; border-radius: 8px; padding: 10px 14px; }
QToolTip { background: #121212; color: #e8e8e8; border: 1px solid #333; }
""".replace("@ASSETS@", ASSETS.as_posix())
