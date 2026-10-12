# Grimoire

A black & white suite of personal desktop tools ("spells") for **KDE Plasma 6** on Linux.
One app, one look: a slim icon rail, monochrome line icons, and every spell built to stay out of your way.

| Spell | What it does |
|---|---|
| **MuraL** | Customize everything you look at: desktop wallpaper & crossfading playlists (images and video), lock screen, splash, login (SDDM), boot (Plymouth), taskbar, Plasma style, window title bars, motion/effects, colors, icons, fonts, cursor and terminal. Every tab has live previews, and a **Community** view with the top 100 from the KDE Store and Wallhaven, installable in one click. |
| **SightsL** | A crosshair overlay drawn above every window and fullscreen game (KDE layer-shell), fully click-through. Many styles, outline, offsets, live updates, and a global hotkey (Ctrl+Alt+X) to hide it. |
| **TidyL** | Keeps `~/Downloads` sorted by file type in the background, sends stale installers/archives to the Trash, finds big files and duplicates. Never deletes: everything goes to the Trash, and every move can be undone. |

## Requirements

- KDE Plasma 6 (Wayland) — tested on Kubuntu 26.04
- Python 3.12+ with PySide6 (Ubuntu/Kubuntu packages):
  ```bash
  sudo apt install python3-pyside6.{qtcore,qtgui,qtwidgets,qtsvg,qtdbus,qtqml,qtquick} python3-pil
  ```
- `layer-shell-qt` (for SightsL) and `ffmpeg` (video thumbnails)

## Install

```bash
git clone https://github.com/cookedaj/Grimoire.git
cd Grimoire
./install.sh          # links launchers into ~/.local/bin, adds the app-menu entry, links the wallpaper plugin
grimoire              # or open "Grimoire" from the app menu
```

Command-line helpers: `grimoire-sightc on|off|toggle`, `grimoire-tidyl run|undo|enable|disable|status`.

## How it works

- **MuraL** writes Plasma's own config (`plasma-apply-*`, `kwriteconfig6`, plasmashell scripting) and ships a
  Plasma wallpaper plugin (`plasma/com.cookedaj.grimoire.mural`) for playlists, crossfades and video wallpapers
  that pause while a window is fullscreen. Previews render on worker threads (splash and login previews are
  rendered from the real QML). System-wide pieces (SDDM login, Plymouth boot) install through `pkexec` via
  `grimoire/spells/mural/root-helper.sh`, which validates its input and keeps backups so you can restore.
- **Community store**: downloads only happen when you press Install. Archives are extracted defensively
  (no absolute paths, no `..`, regular files only, size-capped) and only theme files are copied into place.
  Community login/boot themes run code at login/boot, so prefer popular, well-rated ones.
- **SightsL** runs a small layer-shell overlay process and registers its hotkey with KGlobalAccel.
- **TidyL** runs as a systemd user timer every 10 minutes; rules live in `~/.config/grimoire/tidyl.json`.

## Layout

```
grimoire/            the app (PySide6)
  app.py             window: icon rail + home
  glyphs.py          monochrome line icons drawn in code
  spells/mural/      MuraL tabs, store, previews, root helper, SDDM theme, splash templates
  spells/sightc/     SightsL overlay + page
  spells/tidyl/      TidyL engine, CLI/timer, page
plasma/              the MuraL wallpaper plugin
bin/                 launchers
```

Personal project; artwork you add (wallpapers, community themes) belongs to its creators and isn't part of this repo.
