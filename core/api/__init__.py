"""Small, dependency-free HTTP API for gateway health and observability."""

from .server import GatewayApiServer

__all__ = ["GatewayApiServer"]
