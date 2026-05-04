"""Session and authentication API for Gentle Site Visitor."""

from __future__ import annotations

from gsv.session.adapter import SiteAuthAdapter
from gsv.session.challenge import ChallengePolicy
from gsv.session.credentials import Credentials
from gsv.session.runner import Session, SessionAuthError

__all__ = [
    "ChallengePolicy",
    "Credentials",
    "Session",
    "SessionAuthError",
    "SiteAuthAdapter",
]
