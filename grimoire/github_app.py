# SPDX-License-Identifier: GPL-3.0-or-later
"""Grimoire's GitHub OAuth App, for "Sign in with GitHub" (device flow).

The client ID is public by design (device flow has no client secret, so there is none to keep here or anywhere
in the repo). Empty until the owner registers the app; GRIMOIRE_GITHUB_CLIENT_ID overrides it for testing.
"""
import os

GITHUB_CLIENT_ID = ""


def client_id() -> str:
    cid = os.environ.get("GRIMOIRE_GITHUB_CLIENT_ID", GITHUB_CLIENT_ID).strip()
    return cid if cid.isascii() and cid.replace("_", "").replace(".", "").isalnum() and len(cid) <= 64 else ""
