"""Nox configuration file for the captive portal project."""

from __future__ import annotations

__all__: tuple[str, ...] = ()

from pathlib import Path

import nox

ROOT_DIR: Path = Path(__file__).parent
SRC_DIR: Path = ROOT_DIR / "src" / "captive-portal"


@nox.session(default=False)
def wipe_board(session: nox.Session) -> None:
    """Wipe board."""
    session.install("mpremote")
    session.run("mpremote", "fs", "rm", "-r", ":")


@nox.session(default=False)
def copy_files(session: nox.Session) -> None:
    """Copy source files to board."""
    session.install("mpremote")
    for file in SRC_DIR.iterdir():
        session.run("mpremote", "fs", "cp", str(file), ":")
