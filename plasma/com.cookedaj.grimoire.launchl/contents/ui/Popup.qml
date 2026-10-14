/*
    LaunchL's menu. Header: avatar, name and the search field. Body: categories on the left, apps on the right
    (Places: computer, recent files, frequently used), or the search results while there's text. Footer: the
    Applications / Places tabs and the leave buttons.

    Keyboard: the search field keeps focus, so typing searches right away; arrows move, Left/Right (or Tab) switch
    between categories and apps, Enter launches, Menu or Shift+F10 opens the right-click menu, Ctrl+Tab switches
    Applications/Places, Esc clears the search, then closes.

    SPDX-FileCopyrightText: 2026 cookedaj
    SPDX-License-Identifier: GPL-3.0-or-later
*/
import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.kirigami as Kirigami
import org.kde.ksvg as KSvg
import org.kde.coreaddons as KCoreAddons

FocusScope {
    id: popup

    Layout.minimumWidth: Kirigami.Units.gridUnit * 30
    Layout.minimumHeight: Kirigami.Units.gridUnit * 24
    Layout.preferredWidth: Kirigami.Units.gridUnit * 40
    Layout.preferredHeight: Kirigami.Units.gridUnit * 32

    property string tab: "apps"              // "apps" or "places"
    property string pane: "content"          // where Up/Down go: "side" or "content"
    property int appsRow: 0                  // picked category per tab
    property int placesRow: 0
    readonly property string query: search.text
    readonly property bool searching: query.trim() !== ""
    readonly property bool isCommand: query.startsWith(">")
    readonly property string command: isCommand ? query.slice(1).trim() : ""
    readonly property real sideWidth: Math.round(width * 0.3)

    //BEGIN search plumbing
    Binding {
        target: launchl.runnerModel
        property: "query"
        value: popup.searching && !popup.isCommand ? popup.query : ""
    }
    Connections {
        target: launchl.runnerModel
        function onRequestUpdateQuery(query) {
            search.text = query
        }
    }
    //END

    //BEGIN Grimoire entries in the search
    readonly property var grimoireActions: [
        { name: i18n("Crosshair on"), spell: "sightc", needs: "grimoire-sightc", cmd: "grimoire-sightc on",
          keys: "sightsl sightc crosshair overlay show on aim" },
        { name: i18n("Crosshair off"), spell: "sightc", needs: "grimoire-sightc", cmd: "grimoire-sightc off",
          keys: "sightsl sightc crosshair overlay hide off" },
        { name: i18n("Next crosshair"), spell: "sightc", needs: "grimoire-sightc", cmd: "grimoire-sightc next",
          keys: "sightsl sightc crosshair overlay next preset cycle" },
        { name: i18n("Tidy Downloads now"), spell: "vaultl", needs: "grimoire-vaultl", cmd: "grimoire-vaultl tidy run",
          keys: "vaultl tidyl tidy sort clean downloads organize" },
        { name: i18n("Open VaultL"), spell: "vaultl", needs: "grimoire-vaultl", cmd: "grimoire-vaultl",
          keys: "vaultl files file manager folders browse explorer" },
        { name: i18n("Screenshot region"), spell: "shotl", needs: "grimoire-shotl", cmd: "grimoire-shotl region",
          keys: "shotl screenshot capture region area screen snip print" },
    ]
    // used until Grimoire has written launchl-spells.json
    readonly property var builtinSpells: [
        { id: "mural", name: "MuraL", tagline: i18n("Every screen and surface") },
        { id: "sightc", name: "SightsL", tagline: i18n("Crosshair overlay") },
        { id: "vaultl", name: "VaultL", tagline: i18n("File manager with tidying built in") },
        { id: "optimizel", name: "OptimizeL", tagline: i18n("Speed tweaks") },
        { id: "systeml", name: "SystemL", tagline: i18n("System monitor") },
        { id: "terminall", name: "TerminalL", tagline: i18n("Terminal") },
        { id: "launchl", name: "LaunchL", tagline: i18n("This launcher") },
    ]
    readonly property var spellList: launchl.spells.length ? launchl.spells : builtinSpells
    readonly property url clover: Qt.resolvedUrl("../icons/clover.svg")

    function spellIcon(id: string): var {
        const s = spellList.find(x => x.id === id)
        return s && s.icon ? { icon: "file://" + s.icon, mask: false } : { icon: clover, mask: true }
    }

    // every word typed must start a word of the entry's name or keywords
    function matches(q: string, hay: string): bool {
        const words = " " + hay.toLowerCase().replace(/[^a-z0-9]+/g, " ")
        return q.toLowerCase().split(/\s+/).filter(w => w !== "").every(w => words.includes(" " + w))
    }

    function grimoireResults(q: string): var {
        // from q, not popup.isCommand: this runs from onTextChanged, before those bindings catch up
        if (q.startsWith(">")) {
            const cmd = q.slice(1).trim()
            if (cmd === "") {
                return []
            }
            const terminal = launchl.haveCommands["grimoire-terminall"] ? "TerminalL" : "Konsole"
            return [{ name: i18n("Run %1", cmd), description: i18n("In %1", terminal),
                      icon: "utilities-terminal-symbolic", mask: true,
                      run: () => launchl.runInTerminal(cmd) }]
        }
        if (!Plasmoid.configuration.grimoireInSearch || q.trim().length < 2 || !launchl.haveCommands["grimoire"]) {
            return []
        }
        const out = []
        for (const a of grimoireActions) {
            if (launchl.haveCommands[a.needs] && matches(q, a.name + " " + a.keys + " grimoire")) {
                const s = spellList.find(x => x.id === a.spell)
                const look = spellIcon(a.spell)
                out.push({ name: a.name, description: "Grimoire · " + (s ? s.name : a.spell), icon: look.icon,
                           mask: look.mask, run: () => launchl.runDetached(a.cmd) })
            }
        }
        for (const s of spellList) {
            if (matches(q, s.name + " " + s.id + " grimoire spell")) {
                const look = spellIcon(s.id)
                out.push({ name: s.name, description: s.tagline, icon: look.icon, mask: look.mask,
                           run: () => launchl.runDetached("grimoire " + s.id) })
            }
        }
        return out.slice(0, 6)
    }
    //END

    //BEGIN what the body shows
    ListModel {
        id: placesGroups
        ListElement { display: "Computer" }
        ListElement { display: "Recent files" }
        ListElement { display: "Frequently used" }
        Component.onCompleted: {
            setProperty(0, "display", i18n("Computer"))
            setProperty(1, "display", i18n("Recent files"))
            setProperty(2, "display", i18n("Frequently used"))
        }
    }

    function contentModel() {
        if (tab === "apps") {
            const row = side.currentIndex
            // row 0 is the favorites placeholder; modelForRow(0) isn't meant to be used
            return row <= 0 ? launchl.rootModel.favoritesModel : launchl.rootModel.modelForRow(row)
        }
        return [launchl.computerModel, launchl.recentDocsModel, launchl.frequentModel][Math.max(0, side.currentIndex)]
    }

    function showCategory() {
        if (tab === "apps") {
            appsRow = Math.max(0, side.currentIndex)
        } else {
            placesRow = Math.max(0, side.currentIndex)
        }
        content.model = contentModel()
    }

    function setTab(t: string) {
        if (t === tab) {
            return
        }
        tab = t
        side.model = t === "apps" ? launchl.rootModel : placesGroups
        side.currentIndex = t === "apps" ? appsRow : placesRow
        showCategory()
        search.text = ""
    }

    Connections {
        target: launchl.rootModel
        function onRefreshed() {                 // categories can change when apps are (un)installed
            if (popup.tab === "apps") {
                popup.showCategory()
            }
        }
    }
    //END

    //BEGIN launching and the right-click menu
    function close() {
        if (!Plasmoid.configuration.pin) {
            launchl.expanded = false
        }
    }

    function trigger(model, row: int) {
        if (model && model.trigger && model.trigger(row, "", null)) {
            close()
        }
    }

    function runExtra(extra) {
        extra.run()
        close()
    }

    function openMenu(model, row: int, entry, item: Item, x: real, y: real) {
        if (!entry || !entry.model) {
            return
        }
        const acts = []
        const fav = launchl.rootModel.favoritesModel
        const favId = entry.model.favoriteId
        if (favId && fav && fav.enabled !== false) {
            acts.push(fav.isFavorite(favId)
                ? { text: i18n("Remove from Favorites"), actionId: "_launchl_unfavorite", favoriteId: favId }
                : { text: i18n("Add to Favorites"), actionId: "_launchl_favorite", favoriteId: favId })
        }
        const own = entry.model.hasActionList ? (entry.model.actionList || []) : []
        if (acts.length && own.length) {
            acts.push({ type: "separator" })
        }
        for (const a of own) {
            if (a.subActions && a.subActions.length) {
                acts.push({ type: "separator" }, { type: "title", text: a.text })
                for (const s of a.subActions) {
                    acts.push(s)
                }
            } else {
                acts.push(a)
            }
        }
        // no separators at either end or twice in a row
        for (let i = acts.length - 1; i >= 0; i--) {
            if (acts[i].type === "separator" && (i === 0 || acts[i - 1].type === "separator")) {
                acts.splice(i, 1)
            }
        }
        while (acts.length && acts[acts.length - 1].type === "separator") {
            acts.pop()
        }
        if (!acts.length) {
            return
        }
        menu.target = { model: model, row: row }
        menu.actions = acts
        const p = item.mapToItem(popup, x, y)
        menu.x = Math.max(4, Math.min(p.x, popup.width - menu.implicitWidth - 4))
        menu.y = Math.max(4, Math.min(p.y, popup.height - menu.implicitHeight - 4))
        menu.open()
    }

    ActionMenu {
        id: menu
        property var target: null
        onPicked: action => {
            const fav = launchl.rootModel.favoritesModel
            if (action.actionId === "_launchl_favorite") {
                fav.addFavorite(action.favoriteId)
            } else if (action.actionId === "_launchl_unfavorite") {
                fav.removeFavorite(action.favoriteId)
            } else if (target && target.model.trigger(target.row, action.actionId, action.actionArgument)) {
                popup.close()
            }
        }
        onClosed: search.forceActiveFocus()
    }

    function menuForCurrent() {
        if (searching) {
            results.openMenu()
        } else if (content.currentItem) {
            openMenu(content.model, content.currentIndex, content.currentItem, content.currentItem, 40,
                     content.currentItem.height / 2)
        }
    }
    //END

    //BEGIN keyboard
    function handleKey(event) {
        const k = event.key
        const empty = search.text === ""
        const ctrl = event.modifiers & Qt.ControlModifier
        let handled = true
        if (k === Qt.Key_Escape) {
            if (!empty) {
                search.text = ""
            } else {
                launchl.expanded = false
            }
        } else if (k === Qt.Key_Down || k === Qt.Key_Up || k === Qt.Key_PageDown || k === Qt.Key_PageUp) {
            if (ctrl && (k === Qt.Key_PageDown || k === Qt.Key_PageUp)) {
                setTab(tab === "apps" ? "places" : "apps")
            } else {
                const step = (k === Qt.Key_Down ? 1 : k === Qt.Key_Up ? -1 : k === Qt.Key_PageDown ? 8 : -8)
                if (searching) {
                    results.move(step)
                } else if (pane === "side") {
                    side.move(step > 0 ? 1 : -1)
                } else {
                    content.move(step)
                }
            }
        } else if (k === Qt.Key_Return || k === Qt.Key_Enter) {
            if (searching) {
                results.activate()
            } else if (pane === "side") {
                pane = "content"
            } else if (content.currentIndex >= 0) {
                trigger(content.model, content.currentIndex)
            }
        } else if (k === Qt.Key_Tab && ctrl) {
            setTab(tab === "apps" ? "places" : "apps")
        } else if ((k === Qt.Key_Tab || k === Qt.Key_Backtab) && !searching) {
            pane = pane === "side" ? "content" : "side"
        } else if (k === Qt.Key_Left && empty) {
            pane = "side"
        } else if (k === Qt.Key_Right && empty) {
            pane = "content"
        } else if (k === Qt.Key_Menu || (k === Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier))) {
            menuForCurrent()
        } else if ((k === Qt.Key_Home || k === Qt.Key_End) && empty) {
            content.moveTo(k === Qt.Key_Home ? 0 : content.count - 1)
        } else {
            handled = false
        }
        event.accepted = handled
    }

    Connections {
        target: launchl
        function onHaveCommandsChanged() {       // the probe finished: Grimoire's entries may have changed
            results.extras = popup.grimoireResults(search.text)
        }
        function onExpandedChanged() {
            if (launchl.expanded) {
                search.text = ""
                popup.pane = "content"
                content.keyboardNav = false
                content.moveTo(0)
                content.keyboardNav = false
                search.forceActiveFocus()
            }
        }
    }
    //END

    // the dialog frame's padding: the black background reaches the popup's edges, as Kickoff's header does
    KSvg.FrameSvgItem {
        id: frame
        imagePath: "dialogs/background"
        visible: false
        readonly property real padLeft: Math.round(margins.left - Math.max(inset.left, 0))
        readonly property real padRight: Math.round(margins.right - Math.max(inset.right, 0))
        readonly property real padTop: Math.round(margins.top - Math.max(inset.top, 0))
        readonly property real padBottom: Math.round(margins.bottom - Math.max(inset.bottom, 0))
    }

    Rectangle {
        anchors.fill: parent
        anchors.leftMargin: -frame.padLeft
        anchors.rightMargin: -frame.padRight
        anchors.topMargin: -frame.padTop
        anchors.bottomMargin: -frame.padBottom
        color: launchl.ink.bg
        radius: Kirigami.Units.cornerRadius * 2
        border.width: 1
        border.color: launchl.ink.line
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        //BEGIN header
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 64
            spacing: 0

            RowLayout {
                Layout.preferredWidth: popup.sideWidth
                Layout.maximumWidth: popup.sideWidth
                Layout.leftMargin: 14
                spacing: 10

                KCoreAddons.KUser { id: kuser }

                Item {
                    Layout.preferredWidth: 36
                    Layout.preferredHeight: 36
                    Kirigami.ShadowedImage {
                        id: face
                        anchors.fill: parent
                        source: kuser.faceIconUrl
                        sourceSize: Qt.size(72, 72)
                        fillMode: Image.PreserveAspectCrop
                        radius: width / 2
                        color: launchl.ink.field
                        visible: status === Image.Ready
                    }
                    Rectangle {                  // no picture set: the initial in a ring
                        anchors.fill: parent
                        visible: !face.visible
                        radius: width / 2
                        color: launchl.ink.field
                        border.width: 1
                        border.color: launchl.ink.edge
                        Text {
                            anchors.centerIn: parent
                            text: (kuser.fullName || kuser.loginName || "?").charAt(0).toUpperCase()
                            color: launchl.ink.text
                            font.family: launchl.ink.font
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                        }
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            launchl.runDetached("systemsettings kcm_users")
                            popup.close()
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    Text {
                        Layout.fillWidth: true
                        text: kuser.fullName || kuser.loginName
                        elide: Text.ElideRight
                        color: launchl.ink.white
                        font.family: launchl.ink.font
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                    }
                    Text {
                        Layout.fillWidth: true
                        text: kuser.loginName + "@" + kuser.host
                        elide: Text.ElideRight
                        color: launchl.ink.faint
                        font.family: launchl.ink.font
                        font.pixelSize: 11
                    }
                }
            }

            Rectangle {                          // the search field
                Layout.fillWidth: true
                Layout.preferredHeight: 36
                Layout.leftMargin: 14
                Layout.rightMargin: 8
                radius: 18
                color: launchl.ink.field
                border.width: 1
                border.color: search.activeFocus ? launchl.ink.edge : launchl.ink.line

                Kirigami.Icon {
                    id: lens
                    anchors.left: parent.left
                    anchors.leftMargin: 13
                    anchors.verticalCenter: parent.verticalCenter
                    width: 16
                    height: 16
                    source: popup.isCommand ? "utilities-terminal-symbolic" : "search-symbolic"
                    isMask: true
                    color: launchl.ink.muted
                }

                TextInput {
                    id: search
                    anchors.left: lens.right
                    anchors.leftMargin: 9
                    anchors.right: clear.left
                    anchors.rightMargin: 6
                    anchors.verticalCenter: parent.verticalCenter
                    focus: true
                    clip: true
                    color: launchl.ink.white
                    selectionColor: launchl.ink.white
                    selectedTextColor: launchl.ink.bg
                    font.family: launchl.ink.font
                    font.pixelSize: 14
                    Keys.priority: Keys.BeforeItem
                    Keys.onPressed: event => popup.handleKey(event)
                    onTextChanged: results.extras = popup.grimoireResults(text)
                    Accessible.name: i18n("Search")
                    Accessible.role: Accessible.EditableText

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: search.text === ""
                        text: i18n("Search apps, files and Grimoire  ·  >command runs it")
                        elide: Text.ElideRight
                        width: parent.width
                        color: launchl.ink.faint
                        font: search.font
                    }
                }

                Kirigami.Icon {
                    id: clear
                    anchors.right: parent.right
                    anchors.rightMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    width: search.text === "" ? 0 : 14
                    height: 14
                    visible: search.text !== ""
                    source: "edit-clear-symbolic"
                    isMask: true
                    color: clearMouse.containsMouse ? launchl.ink.white : launchl.ink.muted
                    MouseArea {
                        id: clearMouse
                        anchors.fill: parent
                        anchors.margins: -6
                        hoverEnabled: true
                        onClicked: {
                            search.text = ""
                            search.forceActiveFocus()
                        }
                    }
                }
            }

            Rectangle {                          // pin: keep the menu open when it loses focus
                Layout.preferredWidth: 30
                Layout.preferredHeight: 30
                Layout.rightMargin: 12
                radius: 15
                color: Plasmoid.configuration.pin ? launchl.ink.white : pinMouse.containsMouse ? launchl.ink.hover : "transparent"
                Kirigami.Icon {
                    anchors.centerIn: parent
                    width: 16
                    height: 16
                    source: "window-pin-symbolic"
                    isMask: true
                    color: Plasmoid.configuration.pin ? launchl.ink.bg : launchl.ink.muted
                }
                MouseArea {
                    id: pinMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: Plasmoid.configuration.pin = !Plasmoid.configuration.pin
                }
                Accessible.name: i18n("Keep open")
                Accessible.role: Accessible.CheckBox
            }
        }
        //END

        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: launchl.ink.line }

        //BEGIN body
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            RowLayout {
                anchors.fill: parent
                spacing: 0
                visible: !popup.searching

                Rectangle {
                    Layout.preferredWidth: popup.sideWidth
                    Layout.fillHeight: true
                    color: launchl.ink.side
                    SideList {
                        id: side
                        anchors.fill: parent
                        model: launchl.rootModel
                        focused: popup.pane === "side"
                        onCurrentIndexChanged: popup.showCategory()
                    }
                }
                Rectangle { Layout.preferredWidth: 1; Layout.fillHeight: true; color: launchl.ink.line }

                EntryList {
                    id: content
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    twoLine: popup.tab === "places"
                    sections: popup.tab === "places" || side.currentIndex === 1   // All Applications: A, B, C, ...
                    showCurrent: popup.pane === "content" || keyboardNav === false
                    emptyText: popup.tab === "apps" && side.currentIndex <= 0
                        ? i18n("No favorites yet. Right-click an app to add it.")
                        : popup.tab === "places" ? i18n("Nothing here yet") : ""
                    onActivated: i => popup.trigger(model, i)
                    onHovered: popup.pane = "content"
                    onMenuRequested: (i, item, x, y) => popup.openMenu(model, i, itemAtIndex(i), item, x, y)
                    Component.onCompleted: model = popup.contentModel()
                }
            }

            SearchView {
                id: results
                anchors.fill: parent
                visible: popup.searching
                onTriggerExtra: extra => popup.runExtra(extra)
                onTriggerResult: row => popup.trigger(list.model, row)
                onMenuFor: (row, item, x, y) => popup.openMenu(list.model, row, list.itemAtIndex(row), item, x, y)
            }
        }
        //END

        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: launchl.ink.line }

        //BEGIN footer
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 52

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 4

                Repeater {
                    model: [{ id: "apps", label: i18n("Applications") }, { id: "places", label: i18n("Places") }]
                    delegate: Rectangle {
                        id: tabButton
                        required property var modelData
                        readonly property bool on: popup.tab === modelData.id
                        Layout.preferredHeight: 32
                        Layout.preferredWidth: tabLabel.implicitWidth + 30
                        radius: 16
                        color: on ? launchl.ink.white : tabMouse.containsMouse ? launchl.ink.hover : "transparent"
                        border.width: on ? 0 : 1
                        border.color: launchl.ink.line
                        Text {
                            id: tabLabel
                            anchors.centerIn: parent
                            text: tabButton.modelData.label
                            color: tabButton.on ? launchl.ink.bg : tabMouse.containsMouse ? launchl.ink.text : launchl.ink.muted
                            font.family: launchl.ink.font
                            font.pixelSize: 13
                            font.weight: tabButton.on ? Font.DemiBold : Font.Normal
                        }
                        MouseArea {
                            id: tabMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: {
                                popup.setTab(tabButton.modelData.id)
                                search.forceActiveFocus()
                            }
                        }
                        Accessible.name: modelData.label
                        Accessible.role: Accessible.PageTab
                    }
                }

                Item { Layout.fillWidth: true }
            }

            // opened, the leave buttons slide over the tabs rather than past the edge
            Rectangle {
                anchors.right: parent.right
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                width: Math.min(leaveRow.implicitWidth, parent.width - 24)
                height: leaveRow.implicitHeight
                color: launchl.ink.bg
                clip: true
                LeaveRow {
                    id: leaveRow
                    anchors.fill: parent
                    onDone: popup.close()
                }
            }
        }
        //END
    }

    Component.onCompleted: {
        launchl.rootModel.refresh()
        search.forceActiveFocus()
    }
}
