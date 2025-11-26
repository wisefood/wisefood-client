# entities/base.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import (
    Any,
    Dict,
    List,
    Optional,
    TypeVar,
    TYPE_CHECKING,
)

TEntity = TypeVar("TEntity", bound="BaseEntity")

if TYPE_CHECKING:
    from ..client import Client


@dataclass
class BaseEntity:
    """
    Lightweight proxy for a single API entity.

    Subclasses must define:
      - ENDPOINT   (e.g. "articles")
      - URN_PREFIX (e.g. "urn:article:")
    """

    client: "Client"
    data: Dict[str, Any] = field(default_factory=dict)

    ENDPOINT: str = ""
    URN_PREFIX: str = ""

    # ------------------------------------------------------------------ #
    # URN handling
    # ------------------------------------------------------------------ #

    @classmethod
    def normalize_urn(cls, urn_or_slug: str) -> str:
        """Return a full URN given either a slug or a URN."""
        if urn_or_slug.startswith(cls.URN_PREFIX):
            return urn_or_slug
        return f"{cls.URN_PREFIX}{urn_or_slug}"

    @property
    def urn(self) -> str:
        """URN of the underlying entity."""
        return self.data["urn"]

    @staticmethod
    def _extract_result(payload: Any) -> Any:
        """
        Unwrap the API response and return the actual entity payload.

        The Wisefood API usually nests data under a "result" key.
        """
        if isinstance(payload, dict) and "result" in payload:
            return payload["result"]
        return payload

    # ------------------------------------------------------------------ #
    # CRUD (class methods)
    # ------------------------------------------------------------------ #

    @classmethod
    def get(cls, client: "Client", urn: str) -> "BaseEntity":
        """Fetch a single entity by URN (or slug) and return a proxy."""
        full = cls.normalize_urn(urn)
        resp = client.get(f"{cls.ENDPOINT}/{full}")
        payload = resp.json()
        result = cls._extract_result(payload)
        return cls(client=client, data=result)

    @classmethod
    def create(cls, client: "Client", *, urn: str, **fields: Any) -> "BaseEntity":
        """Create a new entity and return a proxy for it."""
        payload = {"urn": cls.normalize_urn(urn), **fields}
        resp = client.post(cls.ENDPOINT, json=payload)
        payload = resp.json()
        result = cls._extract_result(payload)
        return cls(client=client, data=result)

    # ------------------------------------------------------------------ #
    # CRUD (instance methods)
    # ------------------------------------------------------------------ #

    def refresh(self) -> None:
        """Reload the entity data from the API."""
        resp = self.client.get(f"{self.ENDPOINT}/{self.urn}")
        payload = resp.json()
        self.data = self._extract_result(payload)

    def save(self) -> None:
        """Persist local changes to the API using PATCH."""
        body = {
            k: v
            for k, v in self.data.items()
            if k not in {"id", "creator", "created_at", "updated_at"}
        }
        resp = self.client.patch(f"{self.ENDPOINT}/{self.urn}", json=body)
        payload = resp.json()
        self.data = self._extract_result(payload)

    def delete(self) -> None:
        """Delete the entity from the API."""
        self.client.delete(f"{self.ENDPOINT}/{self.urn}")

    # ------------------------------------------------------------------ #
    # Representation / display helpers
    # ------------------------------------------------------------------ #

    def __repr__(self) -> str:
        """Short, machine-oriented representation."""
        return f"<{self.__class__.__name__} urn='{self.urn}'>"

    def __str__(self) -> str:
        """Compact human-oriented summary."""
        title = self.data.get("title")
        if title:
            return f"{self.__class__.__name__}(urn='{self.urn}', title='{title}')"
        return f"{self.__class__.__name__}(urn='{self.urn}')"

    def show(self) -> None:
        """Pretty-print the full metadata payload."""
        import json

        print(json.dumps(self.data, indent=2, ensure_ascii=False))


class BaseCollectionProxy:
    """
    Indexable / sliceable view over a collection of entities.

    The list endpoint is expected to return either:
      - {"result": ["urn:...","urn:...", ...]}
      - {"result": [{"urn": "...", ...}, ...]}
    """

    ENTITY_CLS = BaseEntity
    ENDPOINT: str = ""

    def __init__(self, client: "Client") -> None:
        self.client = client
        self._urns: Optional[List[str]] = None

    # ------------------------------------------------------------------ #
    # Index loading
    # ------------------------------------------------------------------ #

    def _ensure_index(self) -> None:
        """Fetch and cache the list of URNs for this collection."""
        if self._urns is not None:
            return

        resp = self.client.get(self.ENDPOINT)
        payload = resp.json()
        result = payload.get("result", payload)

        if isinstance(result, list) and (not result or isinstance(result[0], str)):
            # API returned a plain list of URNs
            self._urns = result
        elif isinstance(result, list) and isinstance(result[0], dict):
            # API returned a list of entity dicts
            self._urns = [item["urn"] for item in result]
        else:
            raise ValueError(f"Unexpected list endpoint format: {result!r}")

    def _get_entity(self, urn: str) -> BaseEntity:
        """Return an entity proxy for a given URN."""
        return self.ENTITY_CLS.get(self.client, urn)

    # ------------------------------------------------------------------ #
    # Python container protocol
    # ------------------------------------------------------------------ #

    def __len__(self) -> int:
        self._ensure_index()
        return len(self._urns or [])

    def __iter__(self):
        """Iterate over entity proxies (one API call per entity)."""
        self._ensure_index()
        for urn in self._urns or []:
            yield self._get_entity(urn)

    def __getitem__(self, key):
        """
        Support:
          - proxy[0]           → entity by position
          - proxy[1:10]        → list of entities
          - proxy["slug"]      → entity by slug
          - proxy["urn:..."]   → entity by full URN
          - proxy["text"]      → fuzzy URN search (substring)
        """
        self._ensure_index()
        if self._urns is None:
            raise IndexError("Index not loaded")

        # integer index
        if isinstance(key, int):
            urn = self._urns[key]
            return self._get_entity(urn)

        # slice
        if isinstance(key, slice):
            urns = self._urns[key]
            return [self._get_entity(u) for u in urns]

        # string: URN / slug / fuzzy search
        if isinstance(key, str):
            prefix = self.ENTITY_CLS.URN_PREFIX

            # full URN
            if key.startswith(prefix) and key in self._urns:
                return self._get_entity(key)

            # slug → full URN
            full = prefix + key
            if full in self._urns:
                return self._get_entity(full)

            # substring search
            q = key.lower()
            matches = [u for u in self._urns if q in u.lower()]
            if not matches:
                raise KeyError(f"No {self.ENDPOINT} matching {key!r}")
            if len(matches) == 1:
                return self._get_entity(matches[0])
            return [self._get_entity(u) for u in matches]

        raise TypeError(f"Unsupported key type: {type(key)!r}")

    # ------------------------------------------------------------------ #
    # Helpers for editor / IPython completion
    # ------------------------------------------------------------------ #

    def slugs(self) -> List[str]:
        """Return slug forms of all known URNs (URN prefix stripped)."""
        self._ensure_index()
        prefix = self.ENTITY_CLS.URN_PREFIX
        return [u.replace(prefix, "") for u in (self._urns or [])]

    def __dir__(self):
        """
        Extend dir() with known slugs so IDEs can suggest them,
        even though attribute access is not used for lookup.
        """
        slugs = self.slugs()
        return list(super().__dir__()) + slugs

    def _ipython_key_completions_(self):
        """
        Provide key completions for expressions like:

            collection["<TAB>

        Used by IPython/Jupyter and tools that build on them.
        """
        try:
            return self.slugs()
        except Exception:
            return []
