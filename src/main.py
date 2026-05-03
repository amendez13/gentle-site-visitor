"""Main entry point for gentle-site-visitor."""

from __future__ import annotations

import logging
from typing import Optional

from .logging_config import configure_logging
from .release_info import get_release_info

LOGGER = logging.getLogger(__name__)


def greet(name: Optional[str] = None) -> str:
    """Return a greeting message.

    Args:
        name: Optional name to greet. Defaults to "World".

    Returns:
        A greeting string.
    """
    if name is None:
        name = "World"
    return f"Hello, {name}!"


def main() -> None:
    """Main entry point."""
    configure_logging()
    LOGGER.info(
        "Application startup",
        extra={"event": "startup", "release": get_release_info()},
    )
    print(greet())


if __name__ == "__main__":
    main()
