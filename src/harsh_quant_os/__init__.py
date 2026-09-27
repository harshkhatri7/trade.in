"""HARSH QUANT OS shared foundation package.

This package contains the cross-cutting foundation used by every future
service in the monorepo:

* :mod:`harsh_quant_os.config` - typed, environment-driven configuration.
* :mod:`harsh_quant_os.safety` - the hard safety gates (live trading stays off).
* :mod:`harsh_quant_os.contracts` - provider-independent data contracts.
* :mod:`harsh_quant_os.memory` - persistent research memory categories.

Scope of Phase 0: configuration, safety gates and contracts only.
No market data, no strategies, no trading.
"""

from harsh_quant_os.version import PROJECT_SLUG, __version__

__all__ = ["PROJECT_SLUG", "__version__"]
