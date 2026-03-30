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


from typing import Callable, Generic

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

        identifier_field = getattr(instance, "IDENTIFIER_FIELD", "urn")

        # Auto-fetch lazy entities when accessing a field other than the identifier.
        if key != identifier_field and key not in instance.data:
            # Check if this is a lazy entity (only has the identifier in data)
            if len(instance.data) == 1 and identifier_field in instance.data:
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
      - ENDPOINT          (e.g. "articles")
      - IDENTIFIER_FIELD  (e.g. "urn" or "id")
      - URN_PREFIX / IDENTIFIER_PREFIX for URN-backed entities
    """

    client: "DataClient"
    data: Dict[str, Any] = field(default_factory=dict)

    sync: bool = field(default=True, repr=False, compare=False)

    _dirty_fields: Set[str] = field(default_factory=set, repr=False, compare=False)

    ENDPOINT: ClassVar[str] = ""
    URN_PREFIX: ClassVar[str] = ""
    IDENTIFIER_FIELD: ClassVar[str] = "urn"
    IDENTIFIER_PREFIX: ClassVar[str] = ""
    IMMUTABLE_FIELDS: ClassVar[Set[str]] = {
        "urn",
        "id",
        "creator",
        "created_at",
        "updated_at",
    }

    # ------------------------------------------------------------------ #
    # URN handling
    # ------------------------------------------------------------------ #

    @classmethod
    def _identifier_prefix(cls) -> str:
        return cls.IDENTIFIER_PREFIX or cls.URN_PREFIX

    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        value = value.lstrip("/")
        prefix = cls._identifier_prefix()

        if prefix and value.startswith(prefix):
            return value[len(prefix) :]

        # Preserve the legacy "URN or slug" behavior for URN-backed entities.
        if cls.IDENTIFIER_FIELD == "urn" and ":" in value:
            return value.rsplit(":", 1)[1]

        return value

    @classmethod
    def build_identifier(cls, value: str) -> str:
        normalized = cls.normalize_identifier(value)
        prefix = cls._identifier_prefix()
        if not prefix:
            return normalized
        return prefix + normalized

    @classmethod
    def normalize_urn(cls, urn_or_slug: str) -> str:
        return cls.normalize_identifier(urn_or_slug)

    @property
    def identifier(self) -> str:
        return self.data[self.IDENTIFIER_FIELD]

    @property
    def urn(self) -> str:
        """URN of the underlying entity."""
        if "urn" not in self.data:
            raise AttributeError(f"{self.__class__.__name__} does not expose a URN.")
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
    def get(cls, client: "DataClient", identifier: str) -> "BaseEntity":
        """Fetch a single entity by identifier and return a proxy."""
        full = cls.normalize_identifier(identifier)
        resp = client.get(f"{cls.ENDPOINT}/{full}")
        payload = resp.json()
        result = cls._extract_result(payload)
        return cls(client=client, data=result)

    @classmethod
    def create(
        cls,
        client: "DataClient",
        *,
        urn: Optional[str] = None,
        identifier: Optional[str] = None,
        **fields: Any,
    ) -> "BaseEntity":
        """Create a new entity and return a proxy for it."""
        payload: Dict[str, Any] = {**fields}
        lookup_value = identifier if identifier is not None else urn
        if lookup_value is not None:
            payload[cls.IDENTIFIER_FIELD] = cls.normalize_identifier(lookup_value)
        resp = client.post(cls.ENDPOINT, json=payload)
        payload = resp.json()
        result = cls._extract_result(payload)
        return cls(client=client, data=result)

    @classmethod
    def enhance(
        cls,
        client: "DataClient",
        *,
        urn: Optional[str] = None,
        identifier: Optional[str] = None,
        agent: str,
        **fields: Any,
    ) -> "BaseEntity":
        """Enhance an existing entity and return a proxy for it."""
        lookup_value = identifier if identifier is not None else urn
        if lookup_value is None:
            raise ValueError("An identifier is required for enhancement.")
        full_identifier = cls.normalize_identifier(lookup_value)
        payload = {"agent": agent, **fields}
        resp = client.post(f"{cls.ENDPOINT}/{full_identifier}/enhance", json=payload)
        payload = resp.json()
        result = cls._extract_result(payload)
        return cls(client=client, data=result)

    # ------------------------------------------------------------------ #
    # CRUD (instance methods)
    # ------------------------------------------------------------------ #

    def refresh(self) -> None:
        """Reload the entity data from the API."""
        full = self.normalize_identifier(self.identifier)
        resp = self.client.get(f"{self.ENDPOINT}/{full}")
        payload = resp.json()
        self.data = self._extract_result(payload)

    def save(self, *, only_dirty: bool = False) -> None:
        """
        Persist local changes to the API using PATCH.

        If only_dirty=True, only fields that have been changed via Field
        descriptors are sent (based on `_dirty_fields`).
        """
        immutable_fields = set(self.IMMUTABLE_FIELDS)

        if only_dirty and self._dirty_fields:
            keys = self._dirty_fields
            body = {
                k: self.data[k]
                for k in keys
                if k not in immutable_fields
            }
        else:
            body = {
                k: v
                for k, v in self.data.items()
                if k not in immutable_fields
            }

        if not body:
            return  # nothing to send

        full = self.normalize_identifier(self.identifier)
        resp = self.client.patch(f"{self.ENDPOINT}/{full}", json=body)
        payload = resp.json()
        self.data = self._extract_result(payload)
        self._dirty_fields.clear()

    def delete(self) -> None:
        full = self.normalize_identifier(self.identifier)
        self.client.delete(f"{self.ENDPOINT}/{full}")

    def enhance_self(self, *, agent: str, **fields: Any) -> None:
        """
        Enhance this entity using an AI agent and update its data.

        Args:
            agent: The AI agent identifier to use for enhancement
            **fields: Additional fields to send with the enhancement request
        """
        payload = {"agent": agent, **fields}
        full = self.normalize_identifier(self.identifier)
        resp = self.client.patch(f"{self.ENDPOINT}/{full}/enhance", json=payload)
        payload = resp.json()
        self.data = self._extract_result(payload)
        self._dirty_fields.clear()

        return self.get(self.client, self.identifier)

    @property
    def artifacts(self):
        """
        Return a parent-bound artifacts proxy for URN-backed entities.
        """
        if "urn" not in self.data:
            raise AttributeError(
                f"{self.__class__.__name__} cannot be used as an artifact parent."
            )

        proxy = getattr(self, "_artifacts_proxy", None)
        if proxy is None:
            from .artifacts import ParentArtifactsProxy

            embedded_records = None
            artifacts_payload = self.data.get("artifacts")
            if isinstance(artifacts_payload, list):
                embedded_records = artifacts_payload

            proxy = ParentArtifactsProxy(
                self.client,
                parent_urn=self.urn,
                parent_entity=self,
                embedded_records=embedded_records,
            )
            setattr(self, "_artifacts_proxy", proxy)
        return proxy

    # ------------------------------------------------------------------ #
    # Representation / display helpers
    # ------------------------------------------------------------------ #

    def __repr__(self) -> str:
        """Short, machine-oriented representation."""
        identifier_field = self.IDENTIFIER_FIELD
        return f"<{self.__class__.__name__} {identifier_field}='{self.identifier}'>"

    def __str__(self) -> str:
        """Compact human-oriented summary."""
        title = self.data.get("title")
        identifier_field = self.IDENTIFIER_FIELD
        identifier_value = self.identifier
        if title:
            return (
                f"{self.__class__.__name__}"
                f"({identifier_field}='{identifier_value}', title='{title}')"
            )
        return f"{self.__class__.__name__}({identifier_field}='{identifier_value}')"

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
      - {"result": ["uuid-...","uuid-...", ...]}
      - {"result": [{"urn": "...", ...}, ...]}
      - {"result": [{"id": "...", ...}, ...]}
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
        """Normalize list responses into a list of entity identifiers."""
        result = payload.get("result", payload)
        identifier_field = self.ENTITY_CLS.IDENTIFIER_FIELD

        if isinstance(result, list) and (not result or isinstance(result[0], str)):
            return result
        if isinstance(result, list) and isinstance(result[0], dict):
            return [item[identifier_field] for item in result]

        raise ValueError(f"Unexpected list endpoint format: {result!r}")

    def _fetch_urns(self, *, limit: int, offset: int = 0) -> List[str]:
        """Fetch a page of entity identifiers using limit/offset."""
        resp = self.client.get(self.ENDPOINT, limit=limit, offset=offset)
        payload = resp.json()
        return self._parse_list_result(payload)

    def _ensure_index(self) -> None:
        """Populate an initial page of identifiers for len()/iteration/completions."""
        if self._urns is not None:
            return
        self._urns = self._fetch_urns(
            limit=self.DEFAULT_PAGE_SIZE,
            offset=0,
        )

    def _get_entity(self, urn: str, *, lazy: bool = False) -> BaseEntity:
        """
        Return an entity proxy for a given identifier.

        Args:
            urn: The identifier of the entity
            lazy: If True, return a lazy proxy without fetching data immediately.
                  The entity will only contain the identifier until accessed.
        """
        urn = urn.lstrip("/")

        if lazy:
            # Create a lazy proxy with just the identifier, no API call.
            full_identifier = self.ENTITY_CLS.build_identifier(urn)
            return self.ENTITY_CLS(
                client=self.client,
                data={self.ENTITY_CLS.IDENTIFIER_FIELD: full_identifier},
            )

        return self.ENTITY_CLS.get(self.client, urn)

    def get(self, identifier: str, *, lazy: bool = False) -> BaseEntity:
        """Fetch a single entity by identifier."""
        return self._get_entity(identifier, lazy=lazy)

    # ------------------------------------------------------------------ #
    # Creation helpers
    # ------------------------------------------------------------------ #

    def create(
        self,
        *,
        urn: Optional[str] = None,
        identifier: Optional[str] = None,
        **fields: Any,
    ) -> BaseEntity:
        """
        Create a new entity through the proxy and return its proxy object.

        Keeps the cached index in sync when it has already been populated.
        """
        entity = self.ENTITY_CLS.create(
            self.client,
            urn=urn,
            identifier=identifier,
            **fields,
        )

        if self._urns is not None:
            full_identifier = entity.identifier
            if full_identifier not in self._urns:
                self._urns.append(full_identifier)

        return entity

    # ------------------------------------------------------------------ #
    # Enhancement helpers
    # ------------------------------------------------------------------ #
    def enhance(
        self,
        agent: str,
        *,
        urn: Optional[str] = None,
        identifier: Optional[str] = None,
        **fields: Any,
    ) -> BaseEntity:
        """
        Enhance an existing entity through the proxy and return its proxy object.

        Keeps the cached index in sync when it has already been populated.
        """
        entity = self.ENTITY_CLS.enhance(
            self.client,
            urn=urn,
            identifier=identifier,
            agent=agent,
            **fields,
        )

        if self._urns is not None:
            full_identifier = entity.identifier
            if full_identifier not in self._urns:
                self._urns.append(full_identifier)

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
        identifier_field = self.ENTITY_CLS.IDENTIFIER_FIELD
        for item in results:
            if isinstance(item, dict) and identifier_field in item:
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
          - proxy["slug"]      → entity by slug for URN-backed collections
          - proxy["urn:..."]   → entity by full URN
          - proxy["uuid"]      → entity by UUID for ID-backed collections
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

        # string: identifier / URN / slug
        if isinstance(key, str):
            key = key.lstrip("/")

            normalized = self.ENTITY_CLS.normalize_identifier(key)
            full_identifier = self.ENTITY_CLS.build_identifier(key)

            if self._urns is not None:
                if full_identifier in self._urns:
                    return self._get_entity(full_identifier)
                if normalized in self._urns:
                    return self._get_entity(normalized)

            # Not in cache, try fetching from API directly.
            return self._get_entity(key)

        raise TypeError(f"Unsupported key type: {type(key)!r}")

    # ------------------------------------------------------------------ #
    # Helpers for editor / IPython completion
    # ------------------------------------------------------------------ #

    def slugs(self) -> List[str]:
        """Return completion-friendly identifiers for all known entities."""
        self._ensure_index()
        prefix = self.ENTITY_CLS._identifier_prefix()
        if not prefix:
            return list(self._urns or [])
        return [
            u[len(prefix):] if u.startswith(prefix) else u
            for u in (self._urns or [])
        ]

    def __dir__(self):
        slugs = self.slugs()
        return list(super().__dir__()) + slugs

    def _ipython_key_completions_(self):
        try:
            return self.slugs()
        except Exception:
            return []
