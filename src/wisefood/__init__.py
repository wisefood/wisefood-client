"""wisefood - A small client for accessing and populating the data infrastructure of the WiseFood platform."""

from .client import DataClient, Credentials
from .api_client import Client

__all__ = ["Client", "DataClient", "Credentials"]
# Read from the installed package rather than duplicated here: the literal had
# already drifted three releases behind `pyproject.toml`, and it is what the
# telemetry client reports as `X-Client`, so a stale value quietly mislabels
# every request an SDK user makes.
try:  # pragma: no cover - trivial
    from importlib.metadata import PackageNotFoundError, version as _pkg_version

    __version__ = _pkg_version("wisefood")
except Exception:  # not installed (a source checkout, say)
    __version__ = "0.0.0+local"
