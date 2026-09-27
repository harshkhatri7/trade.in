"""FastAPI service for HARSH QUANT OS.

Layout::

    hqos_api/
    ├── factory.py     application factory: lifespan, CORS, handlers, routers
    ├── core/          cross-cutting HTTP concerns (logging, errors, request id)
    ├── routers/       HTTP only: parse, validate, delegate
    └── services/      pure builders that turn ``Settings`` into responses

Rules enforced by ``docs/architecture/backend.md``:

1. Routers contain no business logic - they call a service builder and return.
2. Configuration comes from exactly one place,
   :class:`harsh_quant_os.config.Settings`, passed explicitly into every
   factory. There is no module-level settings singleton in this package.
3. No broker, order, position or market-data code exists here. The trade gate
   in :mod:`harsh_quant_os.safety` is never bypassed.
"""

from __future__ import annotations

from hqos_api.factory import create_app

__all__ = ["create_app"]
