"""Credential value objects for site login flows."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Credentials:
    """Username/password credentials supplied by an app, not by framework YAML."""

    username: str
    password: str

    @classmethod
    def from_env(cls, prefix: str) -> "Credentials":
        """Read credentials from ``<PREFIX>_USERNAME`` and ``<PREFIX>_PASSWORD``."""
        return cls(
            username=os.environ[f"{prefix}_USERNAME"],
            password=os.environ[f"{prefix}_PASSWORD"],
        )
