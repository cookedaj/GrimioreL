"""FileL, Grimoire's file manager."""
import os
import subprocess
import sys
from pathlib import Path


def show(path: Path | str):
    """Open a standalone FileL window at path (a file gets selected in its folder)."""
    repo = Path(__file__).resolve().parents[3]
    env = dict(os.environ, PYTHONPATH=f"{repo}:{os.environ.get('PYTHONPATH', '')}".rstrip(":"))
    subprocess.Popen([sys.executable, "-m", "grimoire.spells.filel", str(path)], env=env, start_new_session=True)
