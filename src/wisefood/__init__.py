"""wisefood - A small client for accessing and populating the data infrastructure of the WiseFood platform."""

from .client import DataClient, Credentials
from .api_client import Client

__all__ = ["Client", "DataClient", "Credentials"]
__version__ = "0.0.1"
