"""
DigitMatchStar startup wrapper.

The existing app package initializes the current ranking/scoring patches first.
Then proposal_retry_v9 adds only the explicit invalid-proposal recovery.
"""

from . import proposal_retry_v9  # noqa: F401
from .rank_main import app  # noqa: F401
