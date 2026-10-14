/*
    LaunchL: Grimoire's application launcher, laid out like Kickoff (avatar + search on top, categories on the left,
    apps on the right, Applications/Places tabs and the leave buttons at the bottom) in strict black & white.
    The data comes from Plasma's own kicker models, the same ones Kickoff uses, so apps, favorites, search and
    places behave exactly like the stock launcher.

    SPDX-FileCopyrightText: 2026 cookedaj
    SPDX-License-Identifier: GPL-2.0-or-later
*/
import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.private.kicker as Kicker
import org.kde.plasma.plasma5support as P5Support
import org.kde.kirigami as Kirigami

PlasmoidItem {
    id: launchl

    // Grimoire's palette, the same whatever Plasma color scheme is active
    readonly property QtObject ink: QtObject {
        readonly property color bg: "#0b0b0b"
        readonly property color side: "#070707"
        readonly property color field: "#141414"
        readonly property color line: "#222222"
        readonly property color edge: "#3a3a3a"
        readonly property color hover: "#181818"
        readonly property color current: "#202020"
        readonly property color white: "#f2f2f2"
        readonly property color text: "#ececec"
        readonly property color muted: "#8c8c8c"
        readonly property color faint: "#555555"
        readonly property string font: "IBM Plex Sans"
    }

    readonly property bool vertical: Plasmoid.formFactor === PlasmaCore.Types.Vertical
    // Favorites are shared by every launcher (activity stats); the client id only keeps their order. Grimoire's
    // "Replace launcher" sets it to the replaced Kickoff's, so the order carries over too.
    readonly property string favoritesClient: Plasmoid.configuration.favoritesClient
        || ("com.cookedaj.grimoire.launchl.favorites.instance-" + Plasmoid.id)
    onFavoritesClientChanged: rootModel.favoritesModel.initForClient(favoritesClient)

    //BEGIN models: Plasma's kicker models, as Kickoff uses them
    readonly property QtObject rootModel: Kicker.RootModel {
        autoPopulate: false
        appletInterface: launchl
        appNameFormat: 0                     // name only
        flat: true                           // categories, no subcategories
        sorted: Plasmoid.configuration.alphaSort
        showSeparators: true
        showTopLevelItems: true
        showAllApps: true
        showAllAppsCategorized: false
        showRecentApps: false
        showRecentDocs: false
        showPowerSession: false
        showFavoritesPlaceholder: true       // row 0 = Favorites, row 1 = All Applications, then the categories
        highlightNewlyInstalledApps: true

        Component.onCompleted: {
            favoritesModel.initForClient(launchl.favoritesClient)
            if (!Plasmoid.configuration.favoritesPortedToKAstats) {
                if (favoritesModel.count < 1) {
                    favoritesModel.portOldFavorites(Plasmoid.configuration.favorites)
                }
                Plasmoid.configuration.favoritesPortedToKAstats = true
            }
        }
    }

    // KRunner: apps, settings, files (Baloo), calculator, unit conversion, ... whatever runners are enabled
    readonly property QtObject runnerModel: Kicker.RunnerModel {
        appletInterface: launchl
        mergeResults: true
        favoritesModel: launchl.rootModel.favoritesModel
    }

    readonly property QtObject computerModel: Kicker.ComputerModel {
        appletInterface: launchl
        favoritesModel: launchl.rootModel.favoritesModel
        systemApplications: Plasmoid.configuration.systemApplications
    }

    readonly property QtObject recentDocsModel: Kicker.RecentUsageModel {
        favoritesModel: launchl.rootModel.favoritesModel
        shownItems: Kicker.RecentUsageModel.OnlyDocs
    }

    readonly property QtObject frequentModel: Kicker.RecentUsageModel {
        favoritesModel: launchl.rootModel.favoritesModel
        ordering: 1                          // Popular
    }

    readonly property QtObject processRunner: Kicker.ProcessRunner {}
    //END

    //BEGIN Grimoire: which commands exist, and the spells list Grimoire writes for LaunchL
    property var haveCommands: ({})
    property var spells: []                  // [{id, name, tagline, icon}] from launchl-spells.json

    // plasmashell's PATH may lack ~/.local/bin (where Grimoire links its commands)
    readonly property string pathPrefix: 'PATH="$HOME/.local/bin:$PATH"; '
    readonly property string probe: pathPrefix
        + 'for c in grimoire grimoire-sightc grimoire-vaultl grimoire-shotl grimoire-terminall konsole; do '
        + 'command -v "$c" >/dev/null 2>&1 && echo "have $c"; done; '
        + 'cat "${XDG_DATA_HOME:-$HOME/.local/share}/grimoire/launchl-spells.json" 2>/dev/null; true'

    P5Support.DataSource {
        id: shell
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            disconnectSource(source)
            if (source === launchl.probe) {
                launchl.readProbe(String(data.stdout || ""))
            }
        }
    }

    function readProbe(out: string) {
        const have = {}
        const json = []
        for (const line of out.split("\n")) {
            if (line.startsWith("have ")) {
                have[line.slice(5).trim()] = true
            } else {
                json.push(line)
            }
        }
        haveCommands = have
        try {
            const list = JSON.parse(json.join("\n"))
            spells = Array.isArray(list) ? list : []
        } catch (e) {
            spells = []
        }
    }

    function refreshProbe() {
        shell.connectSource(probe)
    }

    function shq(s: string): string {
        return "'" + String(s).replace(/'/g, "'\\''") + "'"
    }

    // Start a command detached from plasmashell (its own session, no pipes held open)
    function runDetached(cmd: string) {
        shell.connectSource(pathPrefix + "setsid -f sh -c " + shq(cmd) + " >/dev/null 2>&1 </dev/null # " + Date.now())
    }

    // ">cmd" in the search: run it in TerminalL when Grimoire has it, else in Konsole
    function runInTerminal(cmd: string) {
        if (haveCommands["grimoire-terminall"]) {
            runDetached("grimoire-terminall -e " + shq(cmd))
        } else {
            runDetached("konsole --noclose -e sh -c " + shq(cmd))
        }
    }
    //END

    Plasmoid.icon: "grimoire"
    toolTipMainText: "LaunchL"
    toolTipSubText: i18n("Apps, places and Grimoire's spells")
    hideOnWindowDeactivate: !Plasmoid.configuration.pin
    preferredRepresentation: compactRepresentation
    switchWidth: Kirigami.Units.gridUnit * 20
    switchHeight: Kirigami.Units.gridUnit * 20

    onExpandedChanged: () => {
        if (expanded) {
            refreshProbe()
        }
    }

    compactRepresentation: MouseArea {
        id: button
        readonly property real cell: launchl.vertical ? width : height
        Layout.minimumWidth: launchl.vertical ? -1 : height
        Layout.minimumHeight: launchl.vertical ? width : -1
        Layout.preferredWidth: launchl.vertical ? -1 : height
        Layout.preferredHeight: launchl.vertical ? width : -1
        hoverEnabled: true
        property bool wasExpanded: false
        Accessible.name: "LaunchL"
        Accessible.role: Accessible.Button
        onPressed: wasExpanded = launchl.expanded
        onClicked: launchl.expanded = !wasExpanded

        // The Grimoire clover, drawn in the panel's text color: white on a dark panel, black on a light one
        Kirigami.Icon {
            anchors.centerIn: parent
            width: Math.min(parent.width, parent.height, Kirigami.Units.iconSizes.huge)
            height: width
            source: Qt.resolvedUrl("../icons/clover.svg")
            isMask: true
            color: Kirigami.Theme.textColor
            opacity: launchl.expanded || button.containsMouse ? 1 : 0.86
            Behavior on opacity { NumberAnimation { duration: Kirigami.Units.shortDuration } }
        }
    }

    fullRepresentation: Popup { focus: true }

    Plasmoid.contextualActions: [
        PlasmaCore.Action {
            text: i18n("Open Grimoire")
            icon.name: "grimoire"
            onTriggered: launchl.runDetached("grimoire launchl")
        },
        PlasmaCore.Action {
            text: i18n("Edit Applications…")
            icon.name: "kmenuedit"
            visible: Plasmoid.immutability !== PlasmaCore.Types.SystemImmutable
            onTriggered: launchl.processRunner.runMenuEditor()
        }
    ]

    Component.onCompleted: {
        Plasmoid.activationTogglesExpanded = true     // Meta / Alt+F1 (plasmashell's launcher shortcut) toggle it
        refreshProbe()
    }
}
