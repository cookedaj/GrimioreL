# Security and privacy

Grimoire Linux runs as you. It only asks for your password (through `pkexec` and KDE's own prompt) for the few
things that change the system, and those go through small helper scripts that know a fixed list of actions:

| Helper (source in `grimoire/spells/<spell>/root-helper.sh`) | Used for | Keeps a backup in |
|---|---|---|
| `mural-root-helper.sh` | login screen (SDDM) and boot (Plymouth) themes | `/etc/sddm.conf.grimoire-backup`, `/var/lib/grimoire-plymouth-previous`, so Restore works |
| `optimizel-root-helper.sh` | system tweaks (sysctl.d, journald, zram, GRUB, services…) | `/var/lib/grimoire-optimizel` |
| `systeml-root-helper.sh` | other users' processes, system services, emptying swap | (nothing to restore) |
| `focusl-root-helper.sh` | a marked block of focus-time sites in `/etc/hosts` | `/var/lib/grimoire-focusl`; the block is removed when the session ends |

Every helper validates its arguments and refuses anything else; files it writes carry a Grimoire mark so "off"
only ever removes what Grimoire put there. Your own files are never deleted: they go to the Trash.

### Where the helpers live

pkexec only ever runs a **root-owned system copy** of a helper, never the one in your per-user install
(`~/.local/share/grimoire/app` is writable by anything running as you, so a helper there could be edited before the
next password prompt and run as root):

- `./install.sh` puts them in `/usr/local/libexec/grimoire-linux/` (root:root, 0755) with a polkit action file,
  `/usr/share/polkit-1/actions/io.github.cookedaj.grimoire-linux.local.policy`. It asks for your password once, and
  again only when a newer version changes a helper (it compares sha256 sums). The root step is a fixed script that
  decodes the helpers into a root-only temp folder and installs them from there, so nothing can swap a file in
  between. `./install.sh --no-system` skips it; without the helpers only the root features are unavailable.
- The .deb and AUR packages put them in `/usr/libexec/grimoire-linux/` with
  `/usr/share/polkit-1/actions/io.github.cookedaj.grimoire-linux.policy`.
- Before every run, Grimoire checks that the helper and every folder above it up to `/` are owned by root, aren't
  symlinks and aren't writable by group or others. If not, or if the helper is missing, it refuses and says so
  ("System helpers aren't installed / aren't safe to run; run ./install.sh again"); it never falls back to the
  per-user copy.
- The polkit actions name Grimoire Linux in the prompt and use `auth_admin_keep`: a second root action from the same
  app within a few minutes doesn't ask again.
- `uninstall.sh` removes the `/usr/local` helpers and their polkit file with one prompt (and prints the command if
  you cancel); a package's helpers go with the package.

What this doesn't cover: something already running as you could still start its own `pkexec` prompt, or change the
per-user Python code to ask for root differently. Only answer a password prompt you expected; Grimoire's own say
"Grimoire Linux … needs your password" and name the helper under `/usr/local/libexec` or `/usr/libexec`.

## Network

Nothing is sent anywhere unless you ask, except the update check: every few hours Grimoire asks GitHub's public
API for the newest commit on `main` (no account, no identifiers beyond a normal HTTPS request; turn it off in
Settings → General or with `GRIMOIRE_NO_UPDATE_CHECK=1`). Packaged installs (.deb, AUR) don't check at all.
On demand only: the MuraL community store (KDE Store, Wallhaven) when you open it and install, NetL's public IP and
ping checks when you press them, and GitHub sign-in / gist backup. There is no telemetry and no analytics.

## Sign-in and backups: threat model

- **No password, no server.** Sign-in is GitHub's OAuth *device flow*: Grimoire shows a code, you approve it on
  github.com in your own browser. There's no redirect or local web server, so nothing to forge (no CSRF `state`
  needed), and no client secret exists, in the repo or anywhere else.
- **Least access.** The token only gets the `gist` scope: it can read and write your gists, nothing else on your
  account. Revoke it any time at github.com/settings/applications (Sign out links there; GitHub doesn't let an app
  without a client secret revoke its own token).
- **Token storage.** Only in the system keyring (Secret Service: KWallet on Plasma), as an item with
  `application=grimoire, service=github`. Never in a file, a log, an error message or the UI; inside Grimoire it's
  wrapped so printing it shows `Token(…)`. It crosses the local session bus to the keyring unencrypted ("plain"
  session), like most keyring clients.
- **Secret isn't private.** The backup gist is *secret*: unlisted, but anyone who has its link can read it. It holds
  your Grimoire settings (which can include local file paths such as wallpaper locations), never the token.
- **Restores are untrusted input**, whether a file or the gist: zip only, size and file-count caps, only known
  relative paths under Grimoire's config/data folders, no absolute or `..` paths, no links or special files, every
  file matching the manifest's sha256, JSON that parses; unknown files are ignored and nothing is executed. Machine
  "undo" state (OptimizeL's originals, store install records) is never backed up or restored. A safety backup is
  made before anything is written, and each file is replaced atomically.
- **Network.** All calls run off the UI thread with clear messages for offline, rate limits (GitHub's slow_down and
  hourly limits are respected) and revoked sign-ins. Only github.com, api.github.com, gist.githubusercontent.com and
  avatars.githubusercontent.com are contacted.
