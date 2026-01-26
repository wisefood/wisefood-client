# entities/base.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import (
    Any,
    ClassVar,
    Dict,
    List,
    Optional,
    Set,
    TypeVar,
    TYPE_CHECKING,
)

TEntity = TypeVar("TEntity", bound="BaseEntity")

if TYPE_CHECKING:
    from ..client import DataClient


from typing import Generic, Callable, TypeVar, Optional

T = TypeVar("T")


class Field(Generic[T]):
    """
    Descriptor mapping an attribute to a key in `entity.data`.

    Example:
        title: str = Field("title", default="")
    """

    def __init__(
        self,
        key: Optional[str] = None,
        *,
        default: Optional[T] = None,
        default_factory: Optional[Callable[[], T]] = None,
        read_only: bool = False,
    ) -> None:
        self.key = key
        self.default = default
        self.default_factory = default_factory
        self.read_only = read_only
        self.name: Optional[str] = None

    def __set_name__(self, owner, name: str) -> None:
        if self.key is None:
            self.key = name
        self.name = name

    def __get__(self, instance, owner=None) -> T:
        if instance is None:
            return self

        key = self.key
        assert key is not None

        # Auto-fetch lazy entities when accessing a field other than 'urn'
        if key != "urn" and key not in instance.data:
            # Check if this is a lazy entity (only has 'urn' in data)
            if len(instance.data) == 1 and "urn" in instance.data:
                instance.refresh()

        if key in instance.data:
            return instance.data[key]

        if self.default_factory is not None:
            value = self.default_factory()
            instance.data[key] = value
            return value

        return self.default

    def __set__(self, instance, value: T) -> None:
        if self.read_only:
            raise AttributeError(f"Field '{self.name}' is read-only")

        key = self.key
        assert key is not None

        instance.data[key] = value

        # Track as dirty if supported
        dirty = getattr(instance, "_dirty_fields", None)
        if isinstance(dirty, set):
            dirty.add(key)

        # Auto-sync on write if enabled
        if getattr(instance, "sync", False):
            instance.save(only_dirty=True)


@dataclass
class BaseEntity:
    """
    Lightweight proxy for a single API entity.

    Subclasses must define:
      - ENDPOINT   (e.g. "articles")
      - URN_PREFIX (e.g. "urn:article:")
    """

    client: "DataClient"
    data: Dict[str, Any] = field(default_factory=dict)

    sync: bool = field(default=True, repr=False, compare=False)

    _dirty_fields: Set[str] = field(default_factory=set, repr=False, compare=False)

    ENDPOINT: ClassVar[str] = ""
    URN_PREFIX: ClassVar[str] = ""

    # ------------------------------------------------------------------ #
    # URN handling
    # ------------------------------------------------------------------ #

    @classmethod
    def normalize_urn(cls, urn_or_slug: str) -> str:
        urn_or_slug = urn_or_slug.lstrip("/")

        # If a full URN like "urn:article:slug" (contains ':') is provided,
        # return the bare slug (the part after the last colon).
        if ":" in urn_or_slug:
            return urn_or_slug.rsplit(":", 1)[1]

        # Otherwise, if the class has a URN_PREFIX and the input starts with it,
        # strip the prefix.
        if cls.URN_PREFIX and urn_or_slug.startswith(cls.URN_PREFIX):
            return urn_or_slug[len(cls.URN_PREFIX) :]

        return urn_or_slug

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
    def get(cls, client: "DataClient", urn: str) -> "BaseEntity":
        """Fetch a single entity by URN (or slug) and return a proxy."""
        full = cls.normalize_urn(urn)
        resp = client.get(f"{cls.ENDPOINT}/{full}")
        payload = resp.json()
        result = cls._extract_result(payload)
        return cls(client=client, data=result)

    @classmethod
    def create(cls, client: "DataClient", *, urn: str, **fields: Any) -> "BaseEntity":
        """Create a new entity and return a proxy for it."""
        payload = {"urn": cls.normalize_urn(urn), **fields}
        resp = client.post(cls.ENDPOINT, json=payload)
        payload = resp.json()
        result = cls._extract_result(payload)
        return cls(client=client, data=result)

    @classmethod
    def enhance(
        cls, client: "DataClient", *, urn: str, agent: str, **fields: Any
    ) -> "BaseEntity":
        """Enhance an existing entity and return a proxy for it."""
        full_urn = cls.normalize_urn(urn)
        payload = {"agent": agent, **fields}
        resp = client.post(f"{cls.ENDPOINT}/{full_urn}/enhance", json=payload)
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

    def save(self, *, only_dirty: bool = False) -> None:
        """
        Persist local changes to the API using PATCH.

        If only_dirty=True, only fields that have been changed via Field
        descriptors are sent (based on `_dirty_fields`).
        """
        if only_dirty and self._dirty_fields:
            keys = self._dirty_fields
            body = {
                k: self.data[k]
                for k in keys
                if k not in {"id", "creator", "created_at", "updated_at"}
            }
        else:
            body = {
                k: v
                for k, v in self.data.items()
                if k not in {"id", "creator", "created_at", "updated_at"}
            }

        if not body:
            return  # nothing to send

        resp = self.client.patch(f"{self.ENDPOINT}/{self.urn}", json=body)
        payload = resp.json()
        self.data = self._extract_result(payload)
        self._dirty_fields.clear()

    def delete(self) -> None:
        self.client.delete(f"{self.ENDPOINT}/{self.urn}")

    def enhance_self(self, *, agent: str, **fields: Any) -> None:
        """
        Enhance this entity using an AI agent and update its data.

        Args:
            agent: The AI agent identifier to use for enhancement
            **fields: Additional fields to send with the enhancement request
        """
        payload = {"agent": agent, **fields}
        resp = self.client.patch(f"{self.ENDPOINT}/{self.urn}/enhance", json=payload)
        payload = resp.json()
        self.data = self._extract_result(payload)
        self._dirty_fields.clear()

        return self.get(self.client, self.urn)

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

    def json(self) -> None:
        """Pretty-print the full metadata payload."""
        import json

        print(json.dumps(self.data, indent=4, ensure_ascii=False))

    def dict(self) -> Dict[str, Any]:
        """Return the full metadata payload as a dictionary."""
        return self.data

    def show(self) -> None:
        """Pretty-print the full metadata payload via Pandas"""
        import pandas as pd

        df = pd.json_normalize(self.data)
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", None)
        print(df.T)


class BaseCollectionProxy:
    """
    Indexable / sliceable view over a collection of entities.

    The list endpoint is expected to return either:
      - {"result": ["urn:...","urn:...", ...]}
      - {"result": [{"urn": "...", ...}, ...]}
    """

    ENTITY_CLS: ClassVar[type[BaseEntity]] = BaseEntity
    ENDPOINT: ClassVar[str] = ""
    DEFAULT_PAGE_SIZE: ClassVar[int] = 100  # used for index/completions

    def __init__(self, client: "DataClient") -> None:
        self.client = client
        self._urns: Optional[List[str]] = None

    # ------------------------------------------------------------------ #
    # Low-level fetching helpers
    # ------------------------------------------------------------------ #

    def _parse_list_result(self, payload: Any) -> List[str]:
        """Normalize list responses into a list of URNs."""
        result = payload.get("result", payload)

        if isinstance(result, list) and (not result or isinstance(result[0], str)):
            return result
        if isinstance(result, list) and isinstance(result[0], dict):
            return [item["urn"] for item in result]

        raise ValueError(f"Unexpected list endpoint format: {result!r}")

    def _fetch_urns(self, *, limit: int, offset: int = 0) -> List[str]:
        """Fetch a page of URNs using limit/offset."""
        resp = self.client.get(self.ENDPOINT, limit=limit, offset=offset)
        payload = resp.json()
        return self._parse_list_result(payload)

    def _ensure_index(self) -> None:
        """Populate an initial page of URNs for len()/iteration/completions."""
        if self._urns is not None:
            return
        self._urns = self._fetch_urns(
            limit=self.DEFAULT_PAGE_SIZE,
            offset=0,
        )

    def _get_entity(self, urn: str, *, lazy: bool = False) -> BaseEntity:
        """
        Return an entity proxy for a given URN.

        Args:
            urn: The URN or slug of the entity
            lazy: If True, return a lazy proxy without fetching data immediately.
                  The entity will only contain the URN until accessed.
        """
        urn = urn.lstrip("/")

        if lazy:
            # Create a lazy proxy with just the URN, no API call
            full_urn = (
                urn
                if urn.startswith(self.ENTITY_CLS.URN_PREFIX)
                else self.ENTITY_CLS.URN_PREFIX + urn
            )
            return self.ENTITY_CLS(client=self.client, data={"urn": full_urn})

        return self.ENTITY_CLS.get(self.client, urn)

    # ------------------------------------------------------------------ #
    # Creation helpers
    # ------------------------------------------------------------------ #

    def create(self, *, urn: str, **fields: Any) -> BaseEntity:
        """
        Create a new entity through the proxy and return its proxy object.

        Keeps the cached index in sync when it has already been populated.
        """
        entity = self.ENTITY_CLS.create(self.client, urn=urn, **fields)

        if self._urns is not None:
            full_urn = entity.urn
            if full_urn not in self._urns:
                self._urns.append(full_urn)

        return entity

    # ------------------------------------------------------------------ #
    # Enhancement helpers
    # ------------------------------------------------------------------ #
    def enhance(self, agent: str, *, urn: str, **fields: Any) -> BaseEntity:
        """
        Enhance an existing entity through the proxy and return its proxy object.

        Keeps the cached index in sync when it has already been populated.
        """
        entity = self.ENTITY_CLS.enhance(self.client, urn=urn, agent=agent, **fields)

        if self._urns is not None:
            full_urn = entity.urn
            if full_urn not in self._urns:
                self._urns.append(full_urn)

        return entity

    # ------------------------------------------------------------------ #
    # Search helpers
    # ------------------------------------------------------------------ #
    def search(
        self,
        q: str,
        fl: Optional[List[str]] = None,
        limit: int = 10,
        offset: int = 0,
        fq: Optional[List[str]] = None,
        sort: Optional[str] = None,
        fields: Optional[List[str]] = None,
        facet_limit: int = 50,
        highlight: bool = False,
        highlight_fields: Optional[List[str]] = None,
        highlight_pre_tag: str = "<em>",
        highlight_post_tag: str = "</em>",
    ) -> List[BaseEntity]:
        """Search entities with optional filters and highlighting."""
        payload = {
            "q": q,
            "limit": limit,
            "offset": offset,
        }
        if fl is not None:
            payload["fl"] = fl
        if fq is not None:
            payload["fq"] = fq
        if sort is not None:
            payload["sort"] = sort
        if fields is not None:
            payload["fields"] = fields
        if facet_limit != 50:
            payload["facet_limit"] = facet_limit
        if highlight:
            payload["highlight"] = highlight
            if highlight_fields is not None:
                payload["highlight_fields"] = highlight_fields
            payload["highlight_pre_tag"] = highlight_pre_tag
            payload["highlight_post_tag"] = highlight_post_tag

        resp = self.client.post(f"{self.ENDPOINT}/search", json=payload).json()
        results = resp.get("result", {}).get("results", [])

        # Parse results into entities
        entities = []
        for item in results:
            if isinstance(item, dict) and "urn" in item:
                entity = self.ENTITY_CLS(client=self.client, data=item)
                entities.append(entity)
            elif isinstance(item, str):
                entities.append(self._get_entity(item))

        return entities

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
          - proxy[1:10]        → list of entities (using limit/offset)
          - proxy["slug"]      → entity by slug
          - proxy["urn:..."]   → entity by full URN
          - proxy["text"]      → fuzzy URN search (substring)
        """

        # integer index → use cached index
        if isinstance(key, int):
            self._ensure_index()
            if self._urns is None:
                raise IndexError("Index not loaded")
            urn = self._urns[key]
            return self._get_entity(urn)

        # slice → use limit/offset when possible
        if isinstance(key, slice):
            start = key.start or 0
            stop = key.stop
            step = key.step or 1

            if step != 1:
                raise ValueError("Step other than 1 is not supported for slices.")

            if stop is None:
                raise ValueError("Open-ended slices are not supported; specify stop.")

            limit = max(0, stop - start)
            if limit == 0:
                return []

            urns = self._fetch_urns(limit=limit, offset=start)
            # Return lazy proxies - entities are only fetched when actually accessed
            return [self._get_entity(u, lazy=True) for u in urns]

        # string: URN / slug / fuzzy search
        if isinstance(key, str):
            key = key.lstrip("/")
            self._ensure_index()

            prefix = self.ENTITY_CLS.URN_PREFIX

            # full URN - check cache first, then fetch from API
            if key.startswith(prefix):
                if self._urns is not None and key in self._urns:
                    return self._get_entity(key)
                # Not in cache, try fetching from API
                return self._get_entity(key)

            # slug → full URN - check cache first, then fetch from API
            full = prefix + key
            if self._urns is not None and full in self._urns:
                return self._get_entity(full)

            # Not in cache, try fetching from API directly
            # This handles the case where entity exists on server but not in local index
            return self._get_entity(key)

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
        slugs = self.slugs()
        return list(super().__dir__()) + slugs

    def _ipython_key_completions_(self):
        try:
            return self.slugs()
        except Exception:
            return []
