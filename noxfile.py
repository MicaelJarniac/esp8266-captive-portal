"""Nox configuration file for the captive portal project."""

from __future__ import annotations

__all__: tuple[str, ...] = ()

import nox
import nox_uv

nox.options.default_venv_backend = "uv"
