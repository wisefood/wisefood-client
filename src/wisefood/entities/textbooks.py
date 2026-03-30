from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from copy import deepcopy
from typing import Any, Dict, List, Optional

from .base import BaseCollectionProxy, BaseEntity, Field


def _structure_attr_name(identifier: str) -> str:
    normalized = "".join(ch if ch.isalnum() else "_" for ch in identifier).strip("_")
    if not normalized:
        normalized = "_"
    if normalized[0].isdigit():
        normalized = f"_{normalized}"
    return normalized.lower()


class TextbookStructureNode:
    def __init__(self, textbook: Textbook, payload: Dict[str, Any]) -> None:
        self._textbook = textbook
        self._payload = payload

    @property
    def id(self) -> Optional[str]:
        value = self._payload.get("id")
        return value if isinstance(value, str) else None

    @property
    def title(self) -> Optional[str]:
        value = self._payload.get("title")
        return value if isinstance(value, str) else None

    @property
    def kind(self) -> Optional[str]:
        value = self._payload.get("kind")
        return value if isinstance(value, str) else None

    @property
    def page_start(self) -> Optional[int]:
        value = self._payload.get("page_start")
        return value if isinstance(value, int) else None

    @property
    def page_end(self) -> Optional[int]:
        value = self._payload.get("page_end")
        return value if isinstance(value, int) else None

    @property
    def artifact_id(self) -> Optional[str]:
        value = self._payload.get("artifact_id")
        return value if isinstance(value, str) else None

    @property
    def children(self) -> List[TextbookStructureNode]:
        children = self._payload.get("children", [])
        if not isinstance(children, list):
            return []
        return [
            TextbookStructureNode(self._textbook, child)
            for child in children
            if isinstance(child, dict)
        ]

    def set(self, **fields: Any) -> TextbookStructureNode:
        if "children" in fields:
            children = fields["children"]
            if children is None:
                fields["children"] = []
            elif not isinstance(children, list):
                raise TypeError("Structure node children must be provided as a list.")
            else:
                resolved_artifact_id = fields.get("artifact_id", self.artifact_id)
                fields["children"] = [
                    self._textbook._normalize_structure_node(
                        child,
                        default_artifact_id=self._textbook._resolve_textbook_artifact_id(
                            resolved_artifact_id,
                            require=True,
                        ),
                    )
                    for child in children
                ]

        if fields.get("artifact_id") is None:
            fields["artifact_id"] = self._textbook._resolve_textbook_artifact_id(
                self.artifact_id,
                require=True,
            )

        self._payload.update(fields)
        if "children" not in self._payload or not isinstance(self._payload["children"], list):
            self._payload["children"] = []
        self._textbook._mark_structure_tree_dirty()
        return self

    def add_child(
        self,
        *,
        id: str,
        title: str,
        kind: str,
        page_start: Optional[int] = None,
        page_end: Optional[int] = None,
        artifact_id: Optional[str] = None,
        children: Optional[List[Dict[str, Any]]] = None,
        **fields: Any,
    ) -> TextbookStructureNode:
        node = self._textbook._build_structure_node(
            id=id,
            title=title,
            kind=kind,
            page_start=page_start,
            page_end=page_end,
            artifact_id=artifact_id,
            children=children,
            **fields,
        )
        raw_children = self._payload.get("children")
        if not isinstance(raw_children, list):
            raw_children = []
            self._payload["children"] = raw_children
        raw_children.append(node)
        self._textbook._mark_structure_tree_dirty()
        return TextbookStructureNode(self._textbook, node)

    def add_chapter(
        self,
        *,
        id: str,
        title: str,
        page_start: Optional[int] = None,
        page_end: Optional[int] = None,
        artifact_id: Optional[str] = None,
        children: Optional[List[Dict[str, Any]]] = None,
        **fields: Any,
    ) -> TextbookStructureNode:
        return self.add_child(
            id=id,
            title=title,
            kind="chapter",
            page_start=page_start,
            page_end=page_end,
            artifact_id=artifact_id,
            children=children,
            **fields,
        )

    def add_section(
        self,
        *,
        id: str,
        title: str,
        page_start: Optional[int] = None,
        page_end: Optional[int] = None,
        artifact_id: Optional[str] = None,
        children: Optional[List[Dict[str, Any]]] = None,
        **fields: Any,
    ) -> TextbookStructureNode:
        return self.add_child(
            id=id,
            title=title,
            kind="section",
            page_start=page_start,
            page_end=page_end,
            artifact_id=artifact_id,
            children=children,
            **fields,
        )

    def find(self, node_id: str) -> Optional[TextbookStructureNode]:
        if self.id == node_id:
            return self
        for child in self.children:
            found = child.find(node_id)
            if found is not None:
                return found
        return None

    def _find_by_attr(self, attr_name: str) -> Optional[TextbookStructureNode]:
        for child in self.children:
            child_id = child.id
            if isinstance(child_id, str) and _structure_attr_name(child_id) == attr_name:
                return child
            found = child._find_by_attr(attr_name)
            if found is not None:
                return found
        return None

    def __getitem__(self, node_id: str) -> TextbookStructureNode:
        found = self.find(node_id)
        if found is None:
            raise KeyError(f"Structure node '{node_id}' was not found.")
        return found

    def __getattr__(self, name: str) -> TextbookStructureNode:
        if name.startswith("_"):
            raise AttributeError(name)
        found = self._find_by_attr(name)
        if found is None:
            raise AttributeError(
                f"Structure node '{self.id or '<unknown>'}' has no child '{name}'."
            )
        return found

    def to_dict(self) -> Dict[str, Any]:
        return deepcopy(self._payload)

    def dict(self) -> Dict[str, Any]:
        return self.to_dict()

    def __repr__(self) -> str:
        return (
            "TextbookStructureNode("
            f"id={self.id!r}, title={self.title!r}, kind={self.kind!r}"
            ")"
        )


class TextbookStructureTree(MutableMapping[str, Any]):
    def __init__(self, textbook: Textbook) -> None:
        self._textbook = textbook

    def _payload_for_read(self) -> Dict[str, Any]:
        payload = self._textbook.data.get("structure_tree")
        if not isinstance(payload, dict):
            return {"roots": []}
        roots = payload.get("roots")
        if isinstance(roots, list):
            return payload
        normalized = dict(payload)
        normalized["roots"] = []
        return normalized

    def _ensure_payload(self) -> Dict[str, Any]:
        payload = self._textbook.data.get("structure_tree")
        if isinstance(payload, dict) and isinstance(payload.get("roots"), list):
            return payload

        normalized = {"roots": []}
        self._textbook._set_structure_tree_payload(normalized)
        return normalized

    @property
    def roots(self) -> List[TextbookStructureNode]:
        roots = self._payload_for_read().get("roots", [])
        if not isinstance(roots, list):
            return []
        return [
            TextbookStructureNode(self._textbook, root)
            for root in roots
            if isinstance(root, dict)
        ]

    @property
    def root(self) -> TextbookStructureNode:
        roots = self.roots
        if len(roots) != 1:
            raise ValueError(
                f"Expected exactly one root node, found {len(roots)}. "
                "Use .roots or .set_root(...) when working with multi-root trees."
            )
        return roots[0]

    def clear(self) -> None:
        self._textbook._set_structure_tree_payload({"roots": []})

    def add_root(
        self,
        *,
        id: str,
        title: str,
        kind: str,
        page_start: Optional[int] = None,
        page_end: Optional[int] = None,
        artifact_id: Optional[str] = None,
        children: Optional[List[Dict[str, Any]]] = None,
        **fields: Any,
    ) -> TextbookStructureNode:
        payload = self._ensure_payload()
        root = self._textbook._build_structure_node(
            id=id,
            title=title,
            kind=kind,
            page_start=page_start,
            page_end=page_end,
            artifact_id=artifact_id,
            children=children,
            **fields,
        )
        payload["roots"].append(root)
        self._textbook._mark_structure_tree_dirty()
        return TextbookStructureNode(self._textbook, root)

    def set_root(
        self,
        *,
        id: str,
        title: str,
        kind: str,
        page_start: Optional[int] = None,
        page_end: Optional[int] = None,
        artifact_id: Optional[str] = None,
        children: Optional[List[Dict[str, Any]]] = None,
        **fields: Any,
    ) -> TextbookStructureNode:
        self.clear()
        return self.add_root(
            id=id,
            title=title,
            kind=kind,
            page_start=page_start,
            page_end=page_end,
            artifact_id=artifact_id,
            children=children,
            **fields,
        )

    def add_chapter(
        self,
        *,
        id: str,
        title: str,
        page_start: Optional[int] = None,
        page_end: Optional[int] = None,
        artifact_id: Optional[str] = None,
        children: Optional[List[Dict[str, Any]]] = None,
        **fields: Any,
    ) -> TextbookStructureNode:
        return self.add_root(
            id=id,
            title=title,
            kind="chapter",
            page_start=page_start,
            page_end=page_end,
            artifact_id=artifact_id,
            children=children,
            **fields,
        )

    def find(self, node_id: str) -> Optional[TextbookStructureNode]:
        for root in self.roots:
            found = root.find(node_id)
            if found is not None:
                return found
        return None

    def _find_by_attr(self, attr_name: str) -> Optional[TextbookStructureNode]:
        for root in self.roots:
            root_id = root.id
            if isinstance(root_id, str) and _structure_attr_name(root_id) == attr_name:
                return root
            found = root._find_by_attr(attr_name)
            if found is not None:
                return found
        return None

    def to_dict(self) -> Dict[str, Any]:
        return deepcopy(self._payload_for_read())

    def dict(self) -> Dict[str, Any]:
        return self.to_dict()

    def __getitem__(self, key: str) -> Any:
        return self._payload_for_read()[key]

    def __setitem__(self, key: str, value: Any) -> None:
        payload = self._payload_for_read()
        payload[key] = value
        normalized = self._textbook._prepare_structure_tree_payload(payload)
        self._textbook._set_structure_tree_payload(normalized)

    def __delitem__(self, key: str) -> None:
        payload = self._payload_for_read()
        del payload[key]
        if "roots" not in payload:
            payload["roots"] = []
        normalized = self._textbook._prepare_structure_tree_payload(payload)
        self._textbook._set_structure_tree_payload(normalized)

    def __iter__(self) -> Iterator[str]:
        return iter(self._payload_for_read())

    def __len__(self) -> int:
        return len(self._payload_for_read())

    def __getattr__(self, name: str) -> TextbookStructureNode:
        if name.startswith("_"):
            raise AttributeError(name)
        found = self._find_by_attr(name)
        if found is None:
            raise AttributeError(f"Structure tree has no node '{name}'.")
        return found

    def __repr__(self) -> str:
        return f"TextbookStructureTree({self.to_dict()!r})"


class Textbook(BaseEntity):
    ENDPOINT = "textbooks"
    URN_PREFIX = "urn:textbook:"
    IMMUTABLE_FIELDS = BaseEntity.IMMUTABLE_FIELDS | {"type"}

    id: str = Field("id", read_only=True)
    title: str = Field("title", default="")
    description: Optional[str] = Field("description")
    status: str = Field("status", default="draft")
    type: str = Field("type", default="textbook", read_only=True)
    tags: List[str] = Field("tags", default_factory=list)
    url: Optional[str] = Field("url")
    license: Optional[str] = Field("license")
    language: Optional[str] = Field("language")
    organization_urn: Optional[str] = Field("organization_urn")
    subtitle: Optional[str] = Field("subtitle")
    authors: List[str] = Field("authors", default_factory=list)
    editors: List[str] = Field("editors", default_factory=list)
    publisher: Optional[str] = Field("publisher")
    edition: Optional[str] = Field("edition")
    isbn10: Optional[str] = Field("isbn10")
    isbn13: Optional[str] = Field("isbn13")
    doi: Optional[str] = Field("doi")
    topics: List[str] = Field("topics", default_factory=list)
    keywords: List[str] = Field("keywords", default_factory=list)
    audience: Optional[str] = Field("audience")
    region: Optional[str] = Field("region")
    review_status: Optional[str] = Field("review_status", default="unreviewed")
    verifier_user_id: Optional[str] = Field("verifier_user_id")
    visibility: Optional[str] = Field("visibility", default="internal")
    applicability_status: Optional[str] = Field(
        "applicability_status",
        default="unknown",
    )
    applicability_start_date: Optional[str] = Field("applicability_start_date")
    applicability_end_date: Optional[str] = Field("applicability_end_date")
    publication_date: Optional[str] = Field("publication_date")
    publication_year: Optional[int] = Field("publication_year")
    page_count: Optional[int] = Field("page_count")
    structure_tree_payload: Optional[Dict[str, Any]] = Field("structure_tree")

    # Embedded relationship payloads, when present in API responses.
    artifact_records: List[Dict[str, Any]] = Field("artifacts", default_factory=list)

    creator: Optional[str] = Field("creator", read_only=True)
    created_at: Optional[str] = Field("created_at", read_only=True)
    updated_at: Optional[str] = Field("updated_at", read_only=True)

    @property
    def artifact_record(self) -> Optional[Dict[str, Any]]:
        if not self.artifact_records:
            return None
        return self.artifact_records[0]

    def _resolve_textbook_artifact_id(
        self,
        artifact_id: Optional[str] = None,
        *,
        require: bool = False,
    ) -> Optional[str]:
        if artifact_id is not None:
            return artifact_id

        if not self.artifact_records:
            if require:
                raise ValueError(
                    "Textbook structure and passage operations require exactly one "
                    "associated artifact, but this textbook has none."
                )
            return None

        if len(self.artifact_records) != 1:
            raise ValueError(
                "Textbook structure and passage operations require exactly one "
                f"associated artifact, but this textbook has {len(self.artifact_records)}."
            )

        record = self.artifact_records[0]
        artifact_id = record.get("id")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise ValueError(
                "The associated textbook artifact is missing its 'id' field."
            )
        return artifact_id

    def _mark_structure_tree_dirty(self) -> None:
        self._dirty_fields.add("structure_tree")
        if self.sync:
            self.save(only_dirty=True)

    def _set_structure_tree_payload(
        self,
        payload: Optional[Dict[str, Any]],
    ) -> None:
        self.data["structure_tree"] = payload
        self._mark_structure_tree_dirty()

    def _normalize_structure_node(
        self,
        node: Dict[str, Any],
        *,
        default_artifact_id: Optional[str],
    ) -> Dict[str, Any]:
        if not isinstance(node, dict):
            raise TypeError("Structure tree nodes must be dictionaries.")

        normalized = dict(node)
        artifact_id = self._resolve_textbook_artifact_id(
            normalized.get("artifact_id", default_artifact_id),
            require=default_artifact_id is not None or "artifact_id" in normalized,
        )
        if artifact_id is not None:
            normalized["artifact_id"] = artifact_id

        raw_children = normalized.get("children", [])
        if raw_children is None:
            raw_children = []
        if not isinstance(raw_children, list):
            raise TypeError("Structure node children must be provided as a list.")
        normalized["children"] = [
            self._normalize_structure_node(
                child,
                default_artifact_id=artifact_id,
            )
            for child in raw_children
        ]
        return normalized

    def _build_structure_node(
        self,
        *,
        id: str,
        title: str,
        kind: str,
        page_start: Optional[int] = None,
        page_end: Optional[int] = None,
        artifact_id: Optional[str] = None,
        children: Optional[List[Dict[str, Any]]] = None,
        **fields: Any,
    ) -> Dict[str, Any]:
        resolved_artifact_id = self._resolve_textbook_artifact_id(
            artifact_id,
            require=True,
        )
        node: Dict[str, Any] = {
            "id": id,
            "title": title,
            "kind": kind,
            "artifact_id": resolved_artifact_id,
            "children": children or [],
        }
        if page_start is not None:
            node["page_start"] = page_start
        if page_end is not None:
            node["page_end"] = page_end
        node.update(fields)
        return self._normalize_structure_node(
            node,
            default_artifact_id=resolved_artifact_id,
        )

    def _prepare_structure_tree_payload(
        self,
        payload: Optional[Dict[str, Any] | TextbookStructureTree],
        *,
        default_artifact_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if payload is None:
            return None
        if isinstance(payload, TextbookStructureTree):
            payload_dict = payload.to_dict()
        elif isinstance(payload, dict):
            payload_dict = deepcopy(payload)
        else:
            raise TypeError(
                "structure_tree must be a dict, TextbookStructureTree, or None."
            )

        roots = payload_dict.get("roots", [])
        if roots is None:
            roots = []
        if not isinstance(roots, list):
            raise TypeError("structure_tree['roots'] must be a list.")

        resolved_default_artifact_id = self._resolve_textbook_artifact_id(
            default_artifact_id,
            require=bool(roots),
        )
        payload_dict["roots"] = [
            self._normalize_structure_node(
                root,
                default_artifact_id=resolved_default_artifact_id,
            )
            for root in roots
        ]
        return payload_dict

    @property
    def structure_tree(self) -> TextbookStructureTree:
        helper = getattr(self, "_structure_tree_helper", None)
        if helper is None:
            helper = TextbookStructureTree(self)
            setattr(self, "_structure_tree_helper", helper)
        return helper

    @structure_tree.setter
    def structure_tree(
        self,
        value: Optional[Dict[str, Any] | TextbookStructureTree],
    ) -> None:
        normalized = self._prepare_structure_tree_payload(value)
        self._set_structure_tree_payload(normalized)

    @property
    def passages(self):
        proxy = getattr(self, "_passages_proxy", None)
        if proxy is None:
            proxy = BoundTextbookPassagesProxy(
                self.client,
                textbook_urn=self.urn,
                textbook=self,
            )
            setattr(self, "_passages_proxy", proxy)
        return proxy

    @property
    def page(self):
        proxy = getattr(self, "_page_proxy", None)
        if proxy is None:
            proxy = TextbookPageProxy(self.passages)
            setattr(self, "_page_proxy", proxy)
        return proxy


class TextbookPassage(BaseEntity):
    ENDPOINT = "textbook-passages"
    IDENTIFIER_FIELD = "id"
    IMMUTABLE_FIELDS = {
        "id",
        "textbook_urn",
        "artifact_id",
        "structure_node_id",
        "structure_path",
        "creator",
        "created_at",
        "updated_at",
    }

    id: str = Field("id", read_only=True)
    textbook_urn: str = Field("textbook_urn", read_only=True)
    artifact_id: str = Field("artifact_id", read_only=True)
    page_no: Optional[int] = Field("page_no")
    sequence_no: Optional[int] = Field("sequence_no")
    text: str = Field("text", default="")
    char_start: Optional[int] = Field("char_start")
    char_end: Optional[int] = Field("char_end")
    structure_node_id: Optional[str] = Field("structure_node_id", read_only=True)
    structure_path: List[str] = Field(
        "structure_path",
        default_factory=list,
        read_only=True,
    )
    extractor_name: Optional[str] = Field("extractor_name")
    extractor_run_id: Optional[str] = Field("extractor_run_id")
    creator: Optional[str] = Field("creator", read_only=True)
    created_at: Optional[str] = Field("created_at", read_only=True)
    updated_at: Optional[str] = Field("updated_at", read_only=True)


class TextbooksProxy(BaseCollectionProxy):
    ENTITY_CLS = Textbook
    ENDPOINT = "textbooks"


class TextbookPassagesProxy(BaseCollectionProxy):
    ENTITY_CLS = TextbookPassage
    ENDPOINT = "textbook-passages"

    def _fetch_urns(self, *, limit: int, offset: int = 0) -> List[str]:
        raise NotImplementedError(
            "Textbook passages do not expose a top-level list endpoint; "
            "use client.textbook_passages.get(...) for direct lookups or "
            "textbook.passages for textbook-bound browsing."
        )

    def by_textbook(self, textbook_urn: str) -> BoundTextbookPassagesProxy:
        return BoundTextbookPassagesProxy(self.client, textbook_urn=textbook_urn)

    def search(
        self,
        q: Optional[str] = None,
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
        raise NotImplementedError(
            "Textbook passage search is scoped to a textbook; use "
            "client.textbook_passages.by_textbook(textbook_urn).search(...) "
            "or textbook.passages.search(...)."
        )

    def _parse_search_result(self, payload: Any) -> List[TextbookPassage]:
        result = BaseEntity._extract_result(payload)
        items = result.get("results", []) if isinstance(result, dict) else result

        if not isinstance(items, list):
            raise ValueError(f"Unexpected textbook passage search format: {items!r}")

        passages = []
        for item in items:
            if isinstance(item, dict):
                passages.append(self.ENTITY_CLS(client=self.client, data=item))
                continue
            if isinstance(item, str):
                passages.append(self._get_entity(item))
                continue
            raise ValueError(f"Unexpected textbook passage search item: {item!r}")

        return passages


class BoundTextbookPassagesProxy(TextbookPassagesProxy):
    DEFAULT_PAGE_SIZE = 1000

    def __init__(self, client, textbook_urn: str, textbook: Optional[Textbook] = None) -> None:
        super().__init__(client)
        self.textbook_urn = textbook_urn
        self.textbook = textbook

    def _textbook_endpoint(self) -> str:
        identifier = Textbook.build_identifier(self.textbook_urn)
        return f"{self.ENDPOINT}/by-textbook/{identifier}"

    def _fetch_urns(self, *, limit: int, offset: int = 0) -> List[str]:
        resp = self.client.get(
            self._textbook_endpoint(),
            limit=limit,
            offset=offset,
        )
        payload = resp.json()
        return self._parse_list_result(payload)

    def _get_entity(self, identifier: str, *, lazy: bool = False) -> BaseEntity:
        entity = super()._get_entity(identifier, lazy=lazy)
        if lazy:
            return entity
        if entity.textbook_urn != self.textbook_urn:
            raise KeyError(
                f"Textbook passage '{identifier}' does not belong to "
                f"textbook '{self.textbook_urn}'."
            )
        return entity

    def _resolve_artifact_id(self, artifact_id: Optional[str] = None) -> str:
        if artifact_id is not None:
            return artifact_id
        if self.textbook is None:
            raise ValueError(
                "An artifact_id is required when the passages proxy is not bound "
                "to a loaded textbook entity."
            )
        resolved_artifact_id = self.textbook._resolve_textbook_artifact_id(require=True)
        assert resolved_artifact_id is not None
        return resolved_artifact_id

    def create(
        self,
        *,
        urn: Optional[str] = None,
        identifier: Optional[str] = None,
        **fields: Any,
    ) -> BaseEntity:
        payload = dict(fields)
        payload["textbook_urn"] = self.textbook_urn
        payload["artifact_id"] = self._resolve_artifact_id(payload.get("artifact_id"))
        return super().create(
            urn=urn,
            identifier=identifier,
            **payload,
        )

    def search(
        self,
        q: Optional[str] = None,
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
    ) -> List[TextbookPassage]:
        payload: Dict[str, Any] = {
            "limit": limit,
            "offset": offset,
        }
        if q is not None:
            payload["q"] = q
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

        resp = self.client.post(f"{self._textbook_endpoint()}/search", json=payload)
        return self._parse_search_result(resp.json())

    def by_page(self, page_no: int) -> List[TextbookPassage]:
        if not isinstance(page_no, int):
            raise TypeError(f"Page number must be an int, got {type(page_no)!r}.")
        if page_no < 1:
            raise ValueError("Page number must be greater than or equal to 1.")

        return self.search(fq=[f"page_no:{page_no}"])

    def bulk_replace(
        self,
        *,
        artifact_id: Optional[str] = None,
        passages: Optional[List[Dict[str, Any]]] = None,
        page_count: Optional[int] = None,
        structure_tree: Optional[Dict[str, Any] | TextbookStructureTree] = None,
        extractor_name: Optional[str] = None,
        extractor_run_id: Optional[str] = None,
    ) -> Any:
        resolved_artifact_id = self._resolve_artifact_id(artifact_id)
        payload: Dict[str, Any] = {"artifact_id": resolved_artifact_id}
        if page_count is not None:
            payload["page_count"] = page_count
        if structure_tree is not None:
            if self.textbook is not None:
                payload["structure_tree"] = self.textbook._prepare_structure_tree_payload(
                    structure_tree,
                    default_artifact_id=resolved_artifact_id,
                )
            elif isinstance(structure_tree, TextbookStructureTree):
                payload["structure_tree"] = structure_tree.to_dict()
            elif isinstance(structure_tree, dict):
                payload["structure_tree"] = deepcopy(structure_tree)
            else:
                raise TypeError(
                    "structure_tree must be a dict, TextbookStructureTree, or None."
                )
        if extractor_name is not None:
            payload["extractor_name"] = extractor_name
        if extractor_run_id is not None:
            payload["extractor_run_id"] = extractor_run_id
        if passages is not None:
            payload["passages"] = passages

        resp = self.client.post(f"{self._textbook_endpoint()}/replace", json=payload)
        result = BaseEntity._extract_result(resp.json())
        if isinstance(result, list):
            return self._parse_search_result({"result": result})
        if isinstance(result, dict) and "results" in result:
            return self._parse_search_result({"result": result})
        return result


class TextbookPageProxy:
    def __init__(self, passages: BoundTextbookPassagesProxy) -> None:
        self.passages = passages

    def __getitem__(self, page_no: int) -> List[TextbookPassage]:
        return self.passages.by_page(page_no)
