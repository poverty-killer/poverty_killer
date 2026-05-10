"""
Subordinate source adapter scaffolds for the world-awareness subsystem.

These adapters are intentionally pre-integration and non-live-attached.
They define starter fetch/normalize boundaries without attaching to active consumers.
"""

from .sec_edgar import SecEdgarAdapter
from .openinsider import OpenInsiderAdapter

__all__ = [
    "SecEdgarAdapter",
    "OpenInsiderAdapter",
]
