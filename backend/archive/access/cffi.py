"""Moved: CurlCffiTransport now lives with the other transports, since it is a lane the
real scraper uses and not a research-only one."""

from backend.archive.transport import DEFAULT_IMPERSONATE, CurlCffiTransport

__all__ = ["DEFAULT_IMPERSONATE", "CurlCffiTransport"]
