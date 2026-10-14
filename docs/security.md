# Security and privacy

Grimoire Linux runs as you. It only asks for your password (through `pkexec` and KDE's own prompt) for the few
things that change the system, and those go through small helper scripts that know a fixed list of actions:

| Helper | Used for | Keeps a backup in |
|---|---|---|
| `grimoire/spells/mural/root-helper.sh` | login screen (SDDM) and boot (Plymouth) themes | the helper's backup folder, so Restore works |
| `grimoire/spells/optimizel/root-helper.sh` | system tweaks (sysctl.d, journald, zram, GRUB, services…) | `/var/lib/grimoire-optimizel` |
| `grimoire/spells/systeml/root-helper.sh` | other users' processes, system services, emptying swap | (nothing to restore) |
| `grimoire/spells/focusl/root-helper.sh` | a marked block of focus-time sites in `/etc/hosts` | the block is removed when the session ends |

Every helper validates its arguments and refuses anything else; files it writes carry a Grimoire mark so "off"
only ever removes what Grimoire put there. Your own files are never deleted: they go to the Trash.

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
