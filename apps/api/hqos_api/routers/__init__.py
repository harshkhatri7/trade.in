"""HTTP routers: parse, validate, delegate."""

from __future__ import annotations

from hqos_api.routers.auth import create_auth_router
from hqos_api.routers.system import create_system_router

__all__ = ["create_auth_router", "create_system_router"]
