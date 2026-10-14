#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Build the grimoire-linux .deb from this checkout's committed HEAD (nothing is installed):
#   packaging/build-deb.sh [OUTDIR]            OUTDIR defaults to ./dist
# Works in a throwaway folder under ~/.cache/grimoire-linux-build, runs dpkg-buildpackage with the hand-written
# packaging/debian/rules (needs only dpkg-dev; PySide6 too if the spell icons should be drawn), and checks that
# debian/changelog's version matches grimoire/__init__.py. GRIMOIRE_DEB_WORKTREE=1 builds the working tree instead
# of HEAD (uncommitted changes included), for trying packaging edits.
set -euo pipefail
SRC="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
OUT="$(mkdir -p "${1:-$SRC/dist}" && cd "${1:-$SRC/dist}" && pwd)"
WORK="${XDG_CACHE_HOME:-$HOME/.cache}/grimoire-linux-build"

VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/grimoire/__init__.py")"
DEBVER="$(dpkg-parsechangelog -l "$SRC/packaging/debian/changelog" -S Version)"
if [ "$VERSION" != "$DEBVER" ]; then
    echo "Version mismatch: grimoire/__init__.py says $VERSION, packaging/debian/changelog says $DEBVER." >&2
    echo "scripts/release.sh <version> sets both; or fix one by hand." >&2
    exit 1
fi

rm -rf "$WORK"
TREE="$WORK/grimoire-linux-$VERSION"
mkdir -p "$TREE"
if [ -n "${GRIMOIRE_DEB_WORKTREE:-}" ] || ! git -C "$SRC" rev-parse --verify -q HEAD >/dev/null; then
    tar -C "$SRC" --exclude=.git --exclude=.worktrees --exclude=dist --exclude=__pycache__ -cf - . | tar -C "$TREE" -xf -
else
    git -C "$SRC" archive --format=tar HEAD | tar -C "$TREE" -xf -
fi
cp -r "$TREE/packaging/debian" "$TREE/debian"

(cd "$TREE" && dpkg-buildpackage -b -us -uc -d)

DEB="grimoire-linux_${VERSION}_all.deb"
cp "$WORK/$DEB" "$OUT/"
rm -rf "$WORK"
echo "Built $OUT/$DEB"
