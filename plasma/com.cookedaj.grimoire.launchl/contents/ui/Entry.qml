/*
    Delegate for any kicker model (apps, favorites, search results, places): an EntryRow fed from the model's roles,
    or a thin rule for separators.

    SPDX-FileCopyrightText: 2026 cookedaj
    SPDX-License-Identifier: GPL-2.0-or-later
*/
import QtQuick

Item {
    id: entry
    required property int index
    required property var model

    readonly property ListView view: ListView.view      // an EntryList (not typed: EntryList uses Entry, a cycle)
    readonly property bool separator: model.isSeparator === true
    readonly property string description: {
        const d = model.description === undefined || model.description === null ? "" : String(model.description)
        return view && view.twoLine && d !== model.display ? d : ""
    }

    width: view ? view.width : 0
    height: separator ? 11 : content.implicitHeight

    Rectangle {
        visible: entry.separator
        anchors.verticalCenter: parent.verticalCenter
        x: 16
        width: parent.width - 32
        height: 1
        color: launchl.ink.line
    }

    EntryRow {
        id: content
        visible: !entry.separator
        anchors.fill: parent
        icon: entry.model.decoration
        title: entry.model.display ?? ""
        subtitle: entry.description
        badge: entry.model.isNewlyInstalled === true
        isCurrent: entry.ListView.isCurrentItem && entry.view.showCurrent
        outlined: entry.view.keyboardNav
        enabled: entry.model.disabled !== true
        onEntered: entry.view.hover(entry.index)
        onClicked: entry.view.activated(entry.index)
        onRightClicked: (x, y) => entry.view.menuRequested(entry.index, content, x, y)
    }
}
