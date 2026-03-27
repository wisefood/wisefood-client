from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import BaseCollectionProxy, BaseEntity, Field


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
    structure_tree: Optional[Dict[str, Any]] = Field("structure_tree")

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

    @property
    def passages(self):
        proxy = getattr(self, "_passages_proxy", None)
        if proxy is None:
            proxy = BoundTextbookPassagesProxy(self.client, textbook_urn=self.urn)
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

    def __init__(self, client, textbook_urn: str) -> None:
        super().__init__(client)
        self.textbook_urn = textbook_urn

    def _textbook_endpoint(self) -> str:
        identifier = Textbook.normalize_identifier(self.textbook_urn)
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

    def create(
        self,
        *,
        urn: Optional[str] = None,
        identifier: Optional[str] = None,
        **fields: Any,
    ) -> BaseEntity:
        payload = dict(fields)
        payload["textbook_urn"] = self.textbook_urn
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
        artifact_id: str,
        passages: Optional[List[Dict[str, Any]]] = None,
        page_count: Optional[int] = None,
        structure_tree: Optional[Dict[str, Any]] = None,
        extractor_name: Optional[str] = None,
        extractor_run_id: Optional[str] = None,
    ) -> Any:
        payload: Dict[str, Any] = {"artifact_id": artifact_id}
        if page_count is not None:
            payload["page_count"] = page_count
        if structure_tree is not None:
            payload["structure_tree"] = structure_tree
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
