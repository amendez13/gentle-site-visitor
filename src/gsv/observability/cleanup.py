"""Session artifact cleanup helpers."""

from __future__ import annotations

import logging
from pathlib import Path

LOG = logging.getLogger(__name__)

_SUCCESS_CLEANUP_PATTERNS = ("trace.zip", "video.webm", "video_*.webm", "network.har")


def cleanup_session_artifacts_on_success(session_dir: Path | None, mode: str) -> None:
    """Remove heavy artifacts after successful runs in failures-only mode."""
    if mode != "failures" or session_dir is None or not session_dir.exists():
        return

    for pattern in _SUCCESS_CLEANUP_PATTERNS:
        for artifact in session_dir.glob(pattern):
            artifact.unlink()
            LOG.debug("Cleaned up success artifact: %s", artifact)

    try:
        if not any(session_dir.iterdir()):
            session_dir.rmdir()
            LOG.debug("Removed empty session directory: %s", session_dir)
    except OSError:
        LOG.debug("Could not remove session directory after cleanup: %s", session_dir, exc_info=True)
