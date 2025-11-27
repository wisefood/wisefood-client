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
    from ..client import Client


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

    client: "Client"
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

    ENTITY_CLS: ClassVar[type[BaseEntity]] = BaseEntity
    ENDPOINT: ClassVar[str] = ""
    DEFAULT_PAGE_SIZE: ClassVar[int] = 100  # used for index/completions

    def __init__(self, client: "Client") -> None:
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

    def _get_entity(self, urn: str) -> BaseEntity:
        """Return an entity proxy for a given URN."""
        urn = urn.lstrip("/")                  
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
            return [self._get_entity(u) for u in urns]

        # string: URN / slug / fuzzy search → use cached index
        if isinstance(key, str):
            key = key.lstrip("/")  
            self._ensure_index()
            if self._urns is None:
                raise IndexError("Index not loaded")

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
        slugs = self.slugs()
        return list(super().__dir__()) + slugs

    def _ipython_key_completions_(self):
        try:
            return self.slugs()
        except Exception:
            return []