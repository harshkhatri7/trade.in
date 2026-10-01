"""Concrete providers, isolated behind the interfaces.

Adding a provider means adding a module here — never editing domain code,
and never importing a vendor SDK. Nothing outside this package names a
provider, and a test that parses every file under ``src/`` fails the
build if that ever changes.

Each adapter states which typed failures it can raise and which it never
does, so the claim is testable rather than a sentence in a docstring.
"""

from __future__ import annotations

from harsh_quant_os.data.adapters.kraken import KrakenProvider
from harsh_quant_os.data.adapters.yahoo import YahooProvider

__all__ = ["KrakenProvider", "YahooProvider"]
