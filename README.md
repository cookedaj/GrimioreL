# Grimoire

A black & white suite of personal desktop tools ("spells") for **KDE Plasma 6** on Linux.
One app, one look: a slim icon rail, monochrome line icons, and every spell built to stay out of your way.

| Spell | What it does |
|---|---|
| **MuraL** | Customize everything you look at: desktop wallpaper & crossfading playlists (images and video), lock screen, splash, login (SDDM), boot (Plymouth), taskbar, Plasma style, window title bars, motion/effects, colors, icons, fonts, cursor and terminal. Every tab has live previews, and a **Community** view with the top 100 from the KDE Store and Wallhaven, installable in one click. |
| **SightsL** | A crosshair overlay drawn above every window and fullscreen game (KDE layer-shell), fully click-through. Pixel-sharp styles, presets, saved crosshairs and share codes, rotation, outline, offsets, screen choice, live updates, and global hotkeys: Ctrl+Alt+X hides it, Ctrl+Alt+Shift+X flips to the next crosshair. |
| **VaultL** | A file manager with tidying built in (FileL and TidyL, merged). Places & drives sidebar, breadcrumbs, grid with image thumbnails or a details list, preview panel, Trash with restore, KDE-compatible copy/cut/paste, Dolphin's keyboard shortcuts. Its **Tidy** section keeps `~/Downloads` sorted by file type in the background, sends stale installers/archives to the Trash, and finds big files and duplicates; Downloads gets a bar with Tidy now and Undo. Never deletes: everything goes to the Trash, and every move can be undone. Runs inside Grimoire or as its own window, and can be the default for opening folders. |
| **OptimizeL** | Scans the PC and lays out ~24 speed tweaks as on/off switches, grouped by power, memory (zram, earlyoom), storage & boot, network (BBR), services, startup apps, desktop and gaming. Every switch is written to persistent config, so it survives restarts, and turning it off restores exactly what was there. Also lists what's already set the fast way. |
| **SystemL** | A system monitor in place of KDE System Monitor. Live graphs for CPU (and every core), memory, swap, disk, network, GPU, temperatures and load; a process list with search, sorting, a tree view, end/force quit, pause and priority; per-app history (what was busy an hour, a day or a week ago) and the top offenders right now; systemd services (system and yours) with start, stop, restart, boot on/off and logs; startup apps; disks with usage and live read/write; and background alerts (a desktop notification when memory, CPU/GPU temperature, a disk's free space or a stuck app crosses the line you set, even while SystemL is closed). Quick actions empty swap, restart the Plasma desktop and jump to OptimizeL. |

## Requirements

- KDE Plasma 6 (Wayland is best; tested on Kubuntu 26.04)
- Python 3.12+ with PySide6 and Pillow, plus layer-shell-qt (SightsL), Qt Multimedia (video wallpapers),
  ffmpeg (video thumbnails) and rsync (installer):

  ```bash
  # Ubuntu / Kubuntu / Debian
  sudo apt install python3-pyside6.{qtcore,qtgui,qtwidgets,qtsvg,qtdbus,qtqml,qtquick} python3-pil python3-psutil \
      qml6-module-org-kde-layershell qml6-module-qtmultimedia ffmpeg rsync
  # Fedora
  sudo dnf install python3-pyside6 python3-pillow python3-psutil layer-shell-qt qt6-qtmultimedia ffmpeg-free rsync
  # Arch / Manjaro / EndeavourOS
  sudo pacman -S pyside6 python-pillow python-psutil layer-shell-qt qt6-multimedia ffmpeg rsync
  ```

## Install

Download Grimoire anywhere (git clone or the ZIP from GitHub), then run its installer:

```bash
git clone https://github.com/cookedaj/GrimioreL.git
cd GrimioreL
./install.sh          # add --all to also put every spell in the app menu
grimoire              # or open "Grimoire" from the app menu
```

The installer needs no sudo. It copies the app into `~/.local/share/grimoire/app`, links the commands into
`~/.local/bin`, adds the app-menu entries and copies the MuraL wallpaper plugin into Plasma. Everything runs
from that copy, so you can move or delete the download afterwards. If `grimoire` isn't found in a terminal,
add `~/.local/bin` to your `PATH` (or log out and back in).

Every spell also runs as its own app: press **Install** on its card on the home page (or use `./install.sh --all`),
or run `grimoire-mural`, `grimoire-sightc`, `grimoire-vaultl`, `grimoire-optimizel`, `grimoire-systeml` directly.

Command-line helpers: `grimoire-sightc on|off|toggle|next`, `grimoire-vaultl [folder]`,
`grimoire-vaultl tidy run|undo|enable|disable|status`, `grimoire-systeml alerts check|test|enable|disable|status`. The old `grimoire-filel` and `grimoire-tidyl` commands
still work and open VaultL.

**Tray icon**: `grimoire-tray` (or "Grimoire Tray" in the app menu) puts live CPU/RAM bars in the system tray,
with the crosshair, the next crosshair profile, "Tidy Downloads now", Performance mode and every spell in its menu.
Tick "Tray icon at login" on Grimoire's home page (or "Start tray at login" in its menu, or
`grimoire-tray autostart on`) to start it with Plasma.

To make VaultL the default file manager: `xdg-mime default grimoire-vaultl.desktop inode/directory`
(switch back any time in System Settings → Default Applications → File manager).

## Upgrade

Grimoire checks GitHub every few hours (no account needed). When there's a newer version, the version at the foot of
the rail shows an arrow and the home page says so: **What's new** lists the changes since yours, **Update now**
downloads and installs it, then **Restart now**. From a terminal: `grimoire update` (or `grimoire update --check` to
only look). Set `GRIMOIRE_NO_UPDATE_CHECK=1` to stop the automatic check; clicking the version still checks.

By hand: get the newer version (`git pull` in your clone, or a fresh download) and run `./install.sh` from it again.
Either way it replaces the installed copy and keeps your settings, timer and autostart.

## Uninstall

```bash
~/.local/share/grimoire/app/uninstall.sh            # keeps your settings for a later install
~/.local/share/grimoire/app/uninstall.sh --purge    # also moves settings, logs and cache to the Trash
```

This removes the app, its commands and menu entries, the wallpaper plugin, the auto-tidy and alert timers, SightsL's
and the tray's autostart (and stops the tray).
Looks and tweaks you applied stay as they are, so turn off MuraL themes and OptimizeL switches in Grimoire first
if you want them undone. Settings live in `~/.config/grimoire` and `~/.local/share/grimoire`.

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
- **VaultL** uses the same system underneath (Qt's `QFileSystemModel`, the freedesktop Trash that Dolphin uses,
  KDE's clipboard format), so files, Trash and clipboard are shared with every other KDE app. Auto-tidy runs as
  the systemd user timer `grimoire-tidyl.timer` every 10 minutes; rules live in `~/.config/grimoire/vaultl.json`
  and the undo log in `~/.local/share/grimoire/vaultl/` (copied once from TidyL's files, which stay as a backup).
- **OptimizeL** stages switch flips and applies them in one go. System tweaks go through `pkexec` to
  `grimoire/spells/optimizel/root-helper.sh`, which only knows a fixed list of tweaks, writes files whose names
  contain `grimoire-optimizel` (sysctl.d, journald.conf.d, apt.conf.d, systemd drop-ins, zram-generator.conf),
  and saves the old values in `/var/lib/grimoire-optimizel` so "off" puts them back. Your own tweaks (power
  profile, KDE settings, autostart overrides, `~/.config/environment.d`) keep their old values in
  `~/.local/share/grimoire/optimizel.json`. Nothing deletes your files; the apt tweak only clears downloaded
  `.deb` installers.
- **Tray** (`grimoire/tray.py`) reads CPU and RAM every 2 s (temperatures every 10 s) and only redraws its icon
  when a bar would look different. Performance mode (`grimoire/spells/optimizel/perfmode.py`) turns on, through
  OptimizeL, whichever of these are off: the performance power profile, file indexing paused, and split-lock
  throttling off (the one system change, so it asks for your password). It remembers what it flipped in
  `~/.local/share/grimoire/performance-mode.json`, and "off" turns back exactly those.
- **SystemL** reads the machine with psutil and `/proc` once a second, only while its window is on screen.
  Per-app history is written once a minute to `~/.local/share/grimoire/systeml-history.json` (a week, busiest
  apps only). Your own processes, user services and startup apps change directly; anything else (another user's
  process, system services, emptying swap) goes through `pkexec` to `grimoire/spells/systeml/root-helper.sh`,
  which checks every argument and refuses to stop the processes and services that keep the session alive.
  Alerts run as the systemd user timer `grimoire-systeml-alerts.timer`: once a minute, one short check (psutil and
  a D-Bus call, no window) that notifies once per problem, then again only after it clears or the reminder time
  passes. Stuck apps are windows KWin marks "Not Responding" and your processes frozen on a disk or device with no
  progress. Thresholds live in `~/.config/grimoire/systeml-alerts.json`, the alert history in
  `~/.local/share/grimoire/systeml-alerts-history.json`.
- **ShotL** takes stills with Spectacle's background mode (`spectacle -b -n -f|-m|-a -o …`; KWin lets it grab
  without asking); regions and single monitors are cut from a full grab in ShotL's own picker. Recordings go
  through the xdg-desktop-portal ScreenCast (KDE asks once which screen or window; tick "allow restoring" and later
  recordings start straight away) into GStreamer (`python3-gi`, `gstreamer1.0-pipewire`) and ffmpeg: H.264 MP4 on
  the NVIDIA encoder, else libx264, else VP8 WebM without ffmpeg. Shots go to `~/Pictures/Screenshots` with dated
  names that never replace a file; the gallery list is `~/.local/share/grimoire/shotl-history.json` and settings
  `~/.config/grimoire/shotl.json`. For hotkeys bind `grimoire-shotl region|window|full|screen` or
  `grimoire-shotl record` (press again to stop) in System Settings → Keyboard → Shortcuts → Add New → Command.

## Layout

```
grimoire/            the app (PySide6)
  app.py             window: icon rail + home
  glyphs.py          monochrome line icons drawn in code
  update.py          self-update from GitHub (updateview.py: What's new panel, banner, rail version)
  spells/mural/      MuraL tabs, store, previews, root helper, SDDM theme, splash templates
  spells/sightc/     SightsL overlay + page
  spells/vaultl/     VaultL window, file operations, tidy engine, tidy panels, CLI/timer
  spells/optimizel/  OptimizeL tweak catalog, root helper, page
  spells/systeml/    SystemL readings, graphs, per-app history, actions, alerts, root helper, page
  spells/shotl/      ShotL capture, region picker, editor, recorder, gallery page, CLI
plasma/              the MuraL wallpaper plugin
bin/                 launchers
install.sh           copies the app into ~/.local/share/grimoire/app and links it in
uninstall.sh         removes it again (--purge also clears settings)
```

Personal project; artwork you add (wallpapers, community themes) belongs to its creators and isn't part of this repo.
