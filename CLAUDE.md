# Grimoire — notes for Claude

A black & white suite of desktop tools ("spells") for KDE Plasma 6 (Wayland), written in Python + PySide6.
Public repo: github.com/cookedaj/Grimoire. Runs on the owner's own Kubuntu 26.04 machine.

## Spells
| Spell | Package | What |
|---|---|---|
| MuraL | `grimoire/spells/mural/` | customizes every screen/surface; tabs built on `screens.py:ScreenTab`; community store in `store.py` + `storeview.py` |
| SightsL | `grimoire/spells/sightc/` | layer-shell crosshair overlay (`overlay.py`/`overlay.qml`), drawing in `draw.py`, settings/presets/profiles in `config.py`, hotkeys via KGlobalAccel |
| VaultL | `grimoire/spells/vaultl/` | file manager with tidying built in (FileL + TidyL merged); `page.py` window (Tidy section in the sidebar), `ops.py` file operations, `tidyview.py` tidy panels, `tidy.py` sorting engine (migrates TidyL's json/log once by copying), `cli.py` (timer keeps the name `grimoire-tidyl.timer`), `__main__.py` standalone window (default for inode/directory). `grimoire-filel`/`grimoire-tidyl` stay as aliases; `standalone.MERGED` keeps their old desktop entries as hidden aliases |
| OptimizeL | `grimoire/spells/optimizel/` | speed tweaks as persistent on/off switches; catalog + detection in `tweaks.py`, system ones in its own whitelisted `root-helper.sh` (test with `OPTIMIZEL_ROOT=<sandbox> OPTIMIZEL_DRY=1`) |
| SystemL | `grimoire/spells/systeml/` | system monitor; `probe.py` readings (psutil, one `Sampler` per page, rates from the previous sample), `graph.py` B&W graphs, `history.py` per-app minutes, `system.py` signals/priority/services/startup/disks, `root-helper.sh` for root actions, `page.py` panels (samples only while visible), `alerts.py` background alert check (no Qt; timer `grimoire-systeml-alerts.timer`, `grimoire-systeml alerts …`) + `alertview.py` its panel |
| ShotL | `grimoire/spells/shotl/` | screenshots + recording; `capture.py` stills via `spectacle -b` (region/monitor cut from a full grab, `region.py` picker), `editor.py` B&W annotation as a replayed op list (undo = pop), `record.py` separate recorder process (portal ScreenCast → GStreamer → ffmpeg nvenc/x264, VP8 fallback; SIGINT stops, state in CACHE/shotl/recording.json), `shots.py` settings/history (no Qt), `__main__.py` CLI `grimoire-shotl region|window|full|screen|record`. Test recording with `record.encode(<videotestsrc>, …)`; a real `record start` pops KDE's share dialog |

Tray: `grimoire/tray.py` (`grimoire-tray`, QSystemTrayIcon → StatusNotifierItem): live CPU/RAM bars drawn by
`glyphs.meter()`, menu for crosshair/tidy/performance mode/spells, single instance via a QLocalServer socket in
`$XDG_RUNTIME_DIR`, opt-in autostart `~/.config/autostart/grimoire-tray.desktop` (home page checkbox or its menu).
Performance mode lives in `optimizel/perfmode.py` (flips `IDS` through `tweaks.apply`, records what it changed).

Shell: `grimoire/app.py` (icon rail, home, `style_app()`), icons drawn in code in `grimoire/glyphs.py`, styles in
`grimoire/theme.py` (QSS). New spells register in `grimoire/spells/__init__.py` (`Spell(id, name, tagline, page, icon,
status)`). Folder names stay as-is when display names change (e.g. SightsL lives in `sightc/`).

## Style rules (the owner cares about these)
- Strictly black & white: no accent colors, Fusion style + the monochrome palette in `style_app()`.
- Sleek and simple; new icons are line glyphs in `glyphs.py`, never colored theme icons in Grimoire's own chrome.
- New spells are named `<Word>L` (MuraL, SightsL, VaultL). Spells get a page, a rail icon and a status line.
- Match surrounding code: small focused modules, short docstrings on the "why".

## Safety rules
- Never permanently delete user files: use the Trash (`gio trash`, or the freedesktop spec as in `vaultl/ops.py`);
  never overwrite on name clashes (`free_name()` → "name (2).ext").
- Anything needing root goes through a spell's `root-helper.sh` via `pkexec` (MuraL's, OptimizeL's or SystemL's: whitelisted
  actions, validated input, old values backed up).
- Simulate package removals (`apt-get -s`) before suggesting them; never let `kubuntu-desktop` or IBM Plex fonts go.
- Community store downloads happen only on the user's Install click; keep the defensive extraction in `store.py`.
- Never commit personal info: author `cookedaj` with the GitHub noreply email; no `/home/<user>` paths or real names.

## Testing (do this before saying something works)
- Render UI offscreen: `QT_QPA_PLATFORM=offscreen` + `QWidget.grab().save(...)`, then look at the image.
- Test file operations in a sandbox under `~/.cache/…` (not `/tmp`: gio can't trash from there) and clean up.
- Live checks on the desktop: `qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript '…'`,
  `journalctl --user` for plasmashell/QML errors. plasmashell caches QML: restart it after plugin edits.
- Don't `pkill -f <pattern>` with a pattern that also matches your own shell command; anchor it (`^python3 -m …`).
- Qt signals carrying sizes/large numbers: use `object`, not `int` (32-bit overflow).

## Install / run
`./install.sh` copies the app (rsync, no `.git`) into `~/.local/share/grimoire/app`, links its `bin/*` into
`~/.local/bin`, writes desktop entries and copies the MuraL wallpaper plugin; re-running it from a newer checkout
upgrades. Nothing installed may point into the clone (public repo: it must work from any download location), so
after editing code, re-run `./install.sh` to see it in the menu apps. `uninstall.sh [--purge]` undoes it.
Run `grimoire [spell-id]`, `grimoire-vaultl [folder]`, `grimoire-sightc on|off|next`, `grimoire-vaultl tidy run`.
Standalone spells: `grimoire/standalone.py` opens any spell in its own window and writes its launcher (command link,
glyph icon, menu entry; links target the installed copy when there is one); a spell gets an Install button on its home card once `bin/grimoire-<id>` exists (no args
opens the window). `./install.sh --all` installs every launcher; plain `./install.sh` refreshes installed ones.
Self-update: install.sh records the source commit in `app/INSTALLED.json` (`GRIMOIRE_SOURCE_SHA` from the updater, else
the checkout's HEAD); `grimoire/update.py` compares it with GitHub main (API answers cached in CACHE, 60 req/h limit),
downloads codeload's tarball, extracts it defensively and runs its install.sh; `updateview.py` is the hub's UI and
`grimoire update [--check]` the CLI. Test it with HOME/XDG dirs in a sandbox, never against the real install.
Dependencies are Ubuntu's `python3-pyside6.*` packages (no pip on this system); `uv` is available for side tools.

## Git
Branch `main`, push to `origin` (github.com/cookedaj/Grimoire). Commit messages: a short title + bullet body.
Parallel work goes in git worktrees under `.worktrees/<name>` (gitignored, skipped by `install.sh`), never as sibling
folders next to the repo; remove them with `git worktree remove` once merged, keep the branch.
