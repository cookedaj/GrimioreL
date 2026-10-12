"""Style tab: the Plasma Style (look of the taskbar, menus, popups, tooltips).
Grimoire's own Onyx plus any community styles installed from the store.
"""
from grimoire.spells.mural import plasmastyle, taskbar
from grimoire.spells.mural.kde import run_tool
from grimoire.spells.mural.screens import Design, ScreenTab, community_designs, community_entry, load_state

DESIGNS = [
    Design("onyx", "Onyx", "Grimoire's own: solid black panel, menus and tooltips with softly rounded corners."),
]


class StyleTab(ScreenTab):
    key = "style"
    subtitle = "The look of your taskbar, menus, popups and tooltips (Plasma Style). Applies instantly."
    apply_label = "Apply style"
    store = ["plasma"]

    def designs(self):
        return DESIGNS + community_designs("plasma")

    def preview(self, design, o):
        opts = {**taskbar.DEFAULTS, **(load_state().get("taskbar", {}).get("options") or {}), "look": "Onyx"}
        return taskbar.render("dock", opts)

    def thumbnail(self, design, o):
        return self.preview(design, o).copy(320, 560, 640, 160).scaled(640, 360)

    def apply(self, design, o):
        if design.id.startswith("store:"):
            ident = community_entry(design.id)["ident"]
            run_tool(["plasma-apply-desktoptheme", ident], ok_if_already=True)
        else:
            plasmastyle.apply(design.id)
        return "Applied ✓"
