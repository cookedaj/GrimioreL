#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Prepare a release locally: scripts/release.sh 0.2.0
#   1. sets __version__ in grimoire/__init__.py
#   2. adds a packaging/debian/changelog entry from the commit titles since the last v* tag (kept as is when the
#      changelog already starts with this version, so you can write that entry by hand first)
#   3. sets pkgver in packaging/aur/PKGBUILD and .SRCINFO's base version
#   4. commits "Release <version>" and makes the annotated tag v<version>
# Nothing is pushed. Check `git show`, then publish with: git push origin main v<version>
# (the tag starts .github/workflows/release.yml, which builds the .deb and the source tarball and makes the
# GitHub Release). Run it on a clean main.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
VERSION="${1:-}"
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "usage: scripts/release.sh X.Y.Z" >&2
    exit 2
fi
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "Commit or stash your changes first." >&2
    exit 1
fi
if git rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null; then
    echo "Tag v$VERSION already exists." >&2
    exit 1
fi

sed -i "s/^__version__ = \".*\"/__version__ = \"$VERSION\"/" grimoire/__init__.py

CHANGELOG=packaging/debian/changelog
if [ "$(dpkg-parsechangelog -l "$CHANGELOG" -S Version 2>/dev/null || head -1 "$CHANGELOG" | sed 's/.*(\(.*\)).*/\1/')" != "$VERSION" ]; then
    LAST="$(git describe --tags --abbrev=0 --match 'v*' 2>/dev/null || true)"
    {
        echo "grimoire-linux ($VERSION) unstable; urgency=medium"
        echo
        git log --no-merges --format='%s' ${LAST:+"$LAST"..HEAD} | head -40 | sed 's/^/  * /'
        echo
        echo " -- cookedaj <285303240+cookedaj@users.noreply.github.com>  $(LC_ALL=C date -R)"
        echo
        cat "$CHANGELOG"
    } > "$CHANGELOG.new"
    mv "$CHANGELOG.new" "$CHANGELOG"
fi

sed -i "s/^pkgver=.*/pkgver=$VERSION/; s/^pkgrel=.*/pkgrel=1/" packaging/aur/PKGBUILD
sed -i "s/^\tpkgver = .*/\tpkgver = $VERSION/; s/^\tpkgrel = .*/\tpkgrel = 1/" packaging/aur/.SRCINFO

git add grimoire/__init__.py "$CHANGELOG" packaging/aur/PKGBUILD packaging/aur/.SRCINFO
git commit -q -m "Release $VERSION" -m "- Version $VERSION in the app, the Debian changelog and the AUR package"
git tag -a "v$VERSION" -m "Grimoire Linux $VERSION"
echo "Made commit $(git rev-parse --short HEAD) and tag v$VERSION (nothing pushed)."
echo "Publish: git push origin main v$VERSION"
