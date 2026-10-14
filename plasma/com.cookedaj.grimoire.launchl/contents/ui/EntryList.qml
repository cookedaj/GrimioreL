/*
    A scrolling list of Entry rows over a kicker model. The popup drives it from the keyboard (move/activate) while
    the search field keeps focus, so typing always goes to the search.

    SPDX-FileCopyrightText: 2026 cookedaj
    SPDX-License-Identifier: GPL-2.0-or-later
*/
import QtQuick
import QtQuick.Controls as QQC2

ListView {
    id: list

    property bool showCurrent: true
    property bool twoLine: false
    property bool keyboardNav: false
    property string emptyText: ""
    property bool sections: true             // headers from the model's "group" role (A, B, ...; runner names)

    signal activated(int index)
    signal hovered(int index)
    signal menuRequested(int index, Item item, real x, real y)

    clip: true
    focus: false
    activeFocusOnTab: false
    keyNavigationEnabled: false
    boundsBehavior: Flickable.StopAtBounds
    highlightFollowsCurrentItem: false
    cacheBuffer: 400
    onModelChanged: {
        currentIndex = count > 0 ? 0 : -1
        positionViewAtBeginning()
    }
    onCountChanged: {
        if (currentIndex < 0 || currentIndex >= count) {
            currentIndex = count > 0 ? 0 : -1
        }
    }
    topMargin: 6
    bottomMargin: 6
    delegate: Entry {}

    section.property: sections ? "group" : ""
    section.criteria: ViewSection.FullString
    section.delegate: Item {
        required property string section
        width: ListView.view.width
        height: section === "" ? 0 : 30
        Text {
            visible: parent.section !== ""
            anchors.left: parent.left
            anchors.leftMargin: 18
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 6
            text: parent.section.toUpperCase()
            color: launchl.ink.faint
            font.family: launchl.ink.font
            font.pixelSize: 10
            font.weight: Font.DemiBold
            font.letterSpacing: 2
        }
    }

    QQC2.ScrollBar.vertical: QQC2.ScrollBar {
        id: bar
        policy: list.contentHeight > list.height ? QQC2.ScrollBar.AsNeeded : QQC2.ScrollBar.AlwaysOff
        width: 8
        contentItem: Rectangle {
            implicitWidth: 3
            radius: 1.5
            color: bar.pressed || bar.hovered ? launchl.ink.muted : launchl.ink.edge
        }
        background: null
    }

    Text {
        anchors.centerIn: parent
        width: parent.width - 60
        visible: list.count === 0 && list.emptyText !== ""
        text: list.emptyText
        wrapMode: Text.WordWrap
        horizontalAlignment: Text.AlignHCenter
        color: launchl.ink.faint
        font.family: launchl.ink.font
        font.pixelSize: 13
    }

    function hover(i: int) {
        keyboardNav = false
        currentIndex = i
        hovered(i)
    }

    function isSeparator(i: int): bool {
        const item = itemAtIndex(i)
        return item !== null && item.separator === true
    }

    // Move the current row by step (skipping separators); false when already at that end
    function move(step: int): bool {
        if (count === 0) {
            return false
        }
        let i = currentIndex < 0 ? (step > 0 ? -1 : count) : currentIndex
        const one = step > 0 ? 1 : -1
        let left = Math.abs(step)
        let moved = false
        while (left > 0) {
            let j = i + one
            while (j >= 0 && j < count && isSeparator(j)) {
                j += one
            }
            if (j < 0 || j >= count) {
                break
            }
            i = j
            moved = true
            left--
        }
        if (moved) {
            currentIndex = i
            positionViewAtIndex(i, ListView.Contain)
        }
        keyboardNav = true
        return moved
    }

    function moveTo(i: int) {
        if (count === 0) {
            return
        }
        currentIndex = Math.max(0, Math.min(count - 1, i))
        positionViewAtIndex(currentIndex, ListView.Contain)
        keyboardNav = true
    }
}
