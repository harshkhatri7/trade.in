"""Single source of truth for the project version.

``__version__`` uses the PEP 440 form (``0.1.0a0``) so that packaging tools
accept it. ``DISPLAY_VERSION`` is the human-facing label used in
documentation (``0.1.0-alpha``).
"""

from __future__ import annotations

__version__: str = "0.1.0a0"
DISPLAY_VERSION: str = "0.1.0-alpha"
PROJECT_SLUG: str = "harsh-quant-os"
PROJECT_NAME: str = "HARSH QUANT OS"
