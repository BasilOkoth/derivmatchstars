"""
DigitMatchStar V10 startup shim.

Import the rank reliability patch before exposing the existing FastAPI app.
No API routes or trading strategy math are replaced here.
"""

from . import rank_reliability_v10  # noqa: F401
from .main import app  # noqa: F401
