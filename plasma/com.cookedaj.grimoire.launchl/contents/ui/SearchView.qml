/*
    Search results: Grimoire's own entries (spells, quick actions, ">command") on top, then KRunner's merged
    results (apps, settings, files, calculator, unit conversion, ...) grouped by runner. One cursor runs through
    both so the arrow keys and Enter treat them as a single list.

    SPDX-FileCopyrightText: 2026 cookedaj
    SPDX-License-Identifier: GPL-2.0-or-later
*/
import QtQuick

Item {
    id: sv

    property var extras: []                  // [{name, description, icon, mask, run()}]
    property int cursor: 0
    readonly property int extraCount: extras.length
    readonly property int total: extraCount + results.count
    readonly property alias list: results

    signal triggerExtra(var extra)
    signal triggerResult(int row)
    signal menuFor(int row, Item item, real x, real y)

    onExtrasChanged: reset()

    function reset() {
        cursor = 0
        sync()
    }

    function sync() {
        if (cursor >= extraCount && results.count > 0) {
            results.currentIndex = Math.min(cursor - extraCount, results.count - 1)
            results.positionViewAtIndex(results.currentIndex, ListView.Contain)
        } else {
            results.positionViewAtBeginning()
        }
    }

    function move(step: int) {
        if (total === 0) {
            return
        }
        cursor = Math.max(0, Math.min(total - 1, cursor + step))
        results.keyboardNav = true
        sync()
    }

    function activate() {
        if (cursor < extraCount) {
            triggerExtra(extras[cursor])
        } else if (results.count > 0) {
            triggerResult(Math.min(cursor - extraCount, results.count - 1))
        }
    }

    function openMenu() {
        if (cursor >= extraCount && results.currentItem) {
            menuFor(results.currentIndex, results.currentItem, 40, results.currentItem.height / 2)
        }
    }

    EntryList {
        id: results
        anchors.fill: parent
        twoLine: true
        showCurrent: sv.cursor >= sv.extraCount
        model: launchl.runnerModel.count ? launchl.runnerModel.modelForRow(0) : null
        emptyText: sv.extraCount === 0 && !launchl.runnerModel.querying ? i18n("No matches") : ""
        onCountChanged: sv.sync()
        onActivated: i => sv.triggerResult(i)
        onHovered: i => sv.cursor = sv.extraCount + i      // the mouse moves the shared cursor too
        onMenuRequested: (i, item, x, y) => sv.menuFor(i, item, x, y)

        header: Column {
            width: results.width
            Item {
                width: parent.width
                height: sv.extraCount > 0 ? 30 : 0
                Text {
                    visible: sv.extraCount > 0
                    anchors.left: parent.left
                    anchors.leftMargin: 18
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 6
                    text: "GRIMOIRE"
                    color: launchl.ink.faint
                    font.family: launchl.ink.font
                    font.pixelSize: 10
                    font.weight: Font.DemiBold
                    font.letterSpacing: 2
                }
            }
            Repeater {
                model: sv.extras
                delegate: EntryRow {
                    required property int index
                    required property var modelData
                    width: results.width
                    height: implicitHeight
                    icon: modelData.icon
                    maskIcon: modelData.mask === true
                    title: modelData.name
                    subtitle: modelData.description ?? ""
                    isCurrent: sv.cursor === index
                    outlined: results.keyboardNav
                    onEntered: {
                        results.keyboardNav = false
                        sv.cursor = index
                    }
                    onClicked: sv.triggerExtra(modelData)
                }
            }
        }
    }
}
