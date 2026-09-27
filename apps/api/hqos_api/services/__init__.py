"""Response builders (pure functions, no HTTP)."""

from __future__ import annotations

from hqos_api.services.system import build_health, build_ready, service_name

__all__ = ["build_health", "build_ready", "service_name"]
