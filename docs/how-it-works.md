# How it works

Where each spell keeps its settings, what it changes on your system and how to undo it. For what needs root and
what goes over the network, see [security.md](security.md).

- **MuraL** writes Plasma's own config (`plasma-apply-*`, `kwriteconfig6`, plasmashell scripting) and ships a
  Plasma wallpaper plugin (`plasma/com.cookedaj.grimoire.mural`) for playlists, crossfades and video wallpapers
  that pause while a window is fullscreen. Previews render on worker threads (splash and login previews are
  rendered from the real QML). System-wide pieces (SDDM login, Plymouth boot) install through `pkexec` via
  its root helper (`mural-root-helper.sh`), which validates its input and keeps backups so you can restore.
- **Community store**: downloads only happen when you press Install. Archives are extracted defensively
  (no absolute paths, no `..`, regular files only, size-capped) and only theme files are copied into place.
  Community login/boot themes run code at login/boot, so prefer popular, well-rated ones.
- **SightsL** runs a small layer-shell overlay process and registers its hotkey with KGlobalAccel.
- **VaultL** uses the same system underneath (Qt's `QFileSystemModel`, the freedesktop Trash that Dolphin uses,
  KDE's clipboard format), so files, Trash and clipboard are shared with every other KDE app. Auto-tidy runs as
  the systemd user timer `grimoire-tidyl.timer` every 10 minutes; rules live in `~/.config/grimoire/vaultl.json`
  and the undo log in `~/.local/share/grimoire/vaultl/` (copied once from TidyL's files, which stay as a backup).
- **OptimizeL** stages switch flips and applies them in one go. System tweaks go through `pkexec` to
  its root helper (`optimizel-root-helper.sh`), which only knows a fixed list of tweaks, writes files whose names
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
  process, system services, emptying swap) goes through `pkexec` to its root helper (`systeml-root-helper.sh`),
  which checks every argument and refuses to stop the processes and services that keep the session alive.
  Alerts run as the systemd user timer `grimoire-systeml-alerts.timer`: once a minute, one short check (psutil and
  a D-Bus call, no window) that notifies once per problem, then again only after it clears or the reminder time
  passes. Stuck apps are windows KWin marks "Not Responding" and your processes frozen on a disk or device with no
  progress. Thresholds live in `~/.config/grimoire/systeml-alerts.json`, the alert history in
  `~/.local/share/grimoire/systeml-alerts-history.json`.
- **TerminalL** runs your login shell (`$SHELL -l`) on a real PTY with `TERM=xterm-256color`; the screen is
  emulated by [pyte](https://github.com/selectel/pyte) (`python3-pyte`), with scrollback, the alternate screen and a
  few xterm extras added on top. Without pyte the page just shows the install command. Profiles and saved commands
  live in `~/.config/grimoire/terminall.json`. "New tab in VaultL's folder" uses the folder VaultL last showed.
- **ShotL** takes stills with Spectacle's background mode (`spectacle -b -n -f|-m|-a -o …`; KWin lets it grab
  without asking); regions and single monitors are cut from a full grab in ShotL's own picker. Recordings go
  through the xdg-desktop-portal ScreenCast (KDE asks once which screen or window; tick "allow restoring" and later
  recordings start straight away) into GStreamer (`python3-gi`, `gstreamer1.0-pipewire`) and ffmpeg: H.264 MP4 on
  the NVIDIA encoder, else libx264, else VP8 WebM without ffmpeg. Shots go to `~/Pictures/Screenshots` with dated
  names that never replace a file; the gallery list is `~/.local/share/grimoire/shotl-history.json` and settings
  `~/.config/grimoire/shotl.json`. For hotkeys bind `grimoire-shotl region|window|full|screen` or
  `grimoire-shotl record` (press again to stop) in System Settings → Keyboard → Shortcuts → Add New → Command.
- **FocusL**: A focus timer in rounds (focus, short breaks, a long break; lengths, rounds and auto-start are yours to set) with a big countdown ring, a notification and a soft chime at each change, and stats: sessions today and this week, total focus time, your streak and the last 14 days as bars. While you focus it turns on Plasma's Do Not Disturb, hides the SightsL crosshair (back after, if it was on), and can keep apps away (a warning, then a polite quit after a grace time, or only the warning) and sites (a marked block in `/etc/hosts`, which asks for your password when the session starts and ends). The timer runs in the background, so closing Grimoire doesn't stop it: `grimoire-focusl start|stop|pause|resume|skip|status`, and `grimoire-focusl unblock` if a session that was killed left sites blocked. Code: `grimoire/spells/focusl/` (store, guards, background runner, root helper, ring, page).
- **LaunchL** is a Plasma panel widget (`plasma/com.cookedaj.grimoire.launchl`, QML on Plasma's own kicker models,
  the same ones Kickoff uses). Its page installs the widget with `kpackagetool6` and can swap it in for Kickoff:
  it records the panel, position, settings, shortcut and favorites order first, so **Restore Kickoff** puts back
  exactly what was there. `uninstall.sh` restores Kickoff before removing the widget.

## Installs

- **Per user** (`./install.sh`, no sudo): the app is copied to `~/.local/share/grimoire/app`, commands are linked
  into `~/.local/bin`, menu entries go to `~/.local/share/applications`. `app/INSTALLED.json` records the commit it
  came from, which the self-updater compares with GitHub's `main`.
- **System-wide** (.deb, AUR): `packaging/stage.sh` lays out `/usr/share/grimoire-linux` (with a `PACKAGED` marker
  that turns the self-updater off), `/usr/bin/grimoire*` links, menu entries, icons, MuraL's wallpaper plugin and
  AppStream data. Timers, autostart entries and hotkeys are still per user, written when you turn them on.

## Layout

```
grimoire/            the app (PySide6)
  app.py             window: icon rail + home
  glyphs.py          monochrome line icons drawn in code
  update.py          self-update from GitHub (updateview.py: What's new panel, banner, rail version)
  settingsview.py    Settings page: hotkeys.py, backup.py, github.py + keystore.py (sign-in), prefs.py
  spells/mural/      MuraL tabs, store, previews, root helper, SDDM theme, splash templates
  spells/sightc/     SightsL overlay + page
  spells/vaultl/     VaultL window, file operations, tidy engine, tidy panels, CLI/timer
  spells/optimizel/  OptimizeL tweak catalog, root helper, page
  spells/systeml/    SystemL readings, graphs, per-app history, actions, alerts, root helper, page
  spells/terminall/  TerminalL screen state (pyte), PTY sessions, keys, terminal view, page
  spells/netl/       NetL readings, NetworkManager controls, usage recorder/timer, page and panels
  spells/shotl/      ShotL capture, region picker, editor, recorder, gallery page, CLI
  spells/focusl/     FocusL timer state, background runner, guards (DND, apps, sites), root helper, page
  spells/launchl/    LaunchL install / replace / restore, page, CLI
plasma/              the MuraL wallpaper plugin and the LaunchL panel widget
bin/                 launchers
install.sh           copies the app into ~/.local/share/grimoire/app and links it in
uninstall.sh         removes it again (--purge also clears settings)
packaging/           .deb (debian/, build-deb.sh), AUR (aur/), the shared system layout (stage.sh), AppStream
scripts/             release.sh (version bump + tag), screenshots.py (README images)
```

Personal project; artwork you add (wallpapers, community themes) belongs to its creators and isn't part of this repo.
