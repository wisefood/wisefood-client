from typing import Any, Dict, List, Optional

from .base import BaseEntity, BaseCollectionProxy, Field


class Guide(BaseEntity):
    ENDPOINT = "guides"
    URN_PREFIX = "urn:guide:"
    IMMUTABLE_FIELDS = BaseEntity.IMMUTABLE_FIELDS | {"type"}

    id: str = Field("id", read_only=True)
    title: str = Field("title", default="")
    description: Optional[str] = Field("description")
    status: str = Field("status", default="active")
    type: str = Field("type", default="guide", read_only=True)
    tags: List[str] = Field("tags", default_factory=list)
    url: Optional[str] = Field("url")
    license: Optional[str] = Field("license")
    language: Optional[str] = Field("language")

    region: Optional[str] = Field("region")
    organization_urn: Optional[str] = Field("organization_urn")
    content: str = Field("content", default="")
    topic: Optional[str] = Field("topic")
    audience: Optional[str] = Field("audience")
    short_title: Optional[str] = Field("short_title")
    issuing_authority: Optional[str] = Field("issuing_authority")
    responsible_ministry: Optional[str] = Field("responsible_ministry")
    document_type: Optional[str] = Field("document_type")
    legal_status: Optional[str] = Field("legal_status")
    target_audiences: List[str] = Field("target_audiences", default_factory=list)
    graphical_model: Optional[str] = Field("graphical_model")
    evidence_basis: Optional[str] = Field("evidence_basis")
    notes: Optional[str] = Field("notes")
    review_status: Optional[str] = Field("review_status")
    verifier_user_id: Optional[str] = Field("verifier_user_id")
    visibility: Optional[str] = Field("visibility")
    applicability_status: Optional[str] = Field("applicability_status")
    applicability_start_date: Optional[str] = Field("applicability_start_date")
    applicability_end_date: Optional[str] = Field("applicability_end_date")
    publication_date: Optional[str] = Field("publication_date")
    publication_year: Optional[int] = Field("publication_year")
    page_count: Optional[int] = Field("page_count")
    revision: Optional[Dict[str, Any]] = Field("revision")
    identifiers: List[Dict[str, Any]] = Field("identifiers", default_factory=list)

    # Embedded relationship payloads, when present in API responses.
    artifact_records: List[Dict[str, Any]] = Field("artifacts", default_factory=list)
    guideline_ids: List[str] = Field("guidelines", default_factory=list)

    creator: Optional[str] = Field("creator", read_only=True)
    created_at: Optional[str] = Field("created_at", read_only=True)
    updated_at: Optional[str] = Field("updated_at", read_only=True)

    @property
    def guidelines(self):
        proxy = getattr(self, "_guidelines_proxy", None)
        if proxy is None:
            proxy = GuideGuidelinesProxy(self.client, guide_urn=self.urn)
            setattr(self, "_guidelines_proxy", proxy)
        return proxy

    @property
    def page(self):
        proxy = getattr(self, "_page_proxy", None)
        if proxy is None:
            proxy = GuidePageProxy(self.guidelines)
            setattr(self, "_page_proxy", proxy)
        return proxy


class Guideline(BaseEntity):
    ENDPOINT = "guidelines"
    IDENTIFIER_FIELD = "id"
    IMMUTABLE_FIELDS = {
        "id",
        "guide_urn",
        "guide_region",
        "creator",
        "created_at",
        "updated_at",
    }

    id: str = Field("id", read_only=True)
    guide_urn: str = Field("guide_urn", read_only=True)
    guide_region: Optional[str] = Field("guide_region", read_only=True)
    title: Optional[str] = Field("title")
    rule_text: str = Field("rule_text", default="")
    sequence_no: Optional[int] = Field("sequence_no")
    page_no: Optional[int] = Field("page_no")
    action_type: Optional[str] = Field("action_type")
    target_populations: List[Any] = Field("target_populations", default_factory=list)
    frequency: Optional[Any] = Field("frequency")
    quantity: Optional[Dict[str, Any]] = Field("quantity")
    food_groups: List[Any] = Field("food_groups", default_factory=list)
    source_refs: List[Dict[str, Any]] = Field("source_refs", default_factory=list)
    notes: Optional[str] = Field("notes")
    status: str = Field("status", default="active")
    review_status: Optional[str] = Field("review_status")
    verifier_user_id: Optional[str] = Field("verifier_user_id")
    visibility: Optional[str] = Field("visibility")
    applicability_status: Optional[str] = Field("applicability_status")
    applicability_start_date: Optional[str] = Field("applicability_start_date")
    applicability_end_date: Optional[str] = Field("applicability_end_date")
    creator: Optional[str] = Field("creator", read_only=True)
    created_at: Optional[str] = Field("created_at", read_only=True)
    updated_at: Optional[str] = Field("updated_at", read_only=True)


class GuidesProxy(BaseCollectionProxy):
    ENTITY_CLS = Guide
    ENDPOINT = "guides"


class GuidelinesProxy(BaseCollectionProxy):
    ENTITY_CLS = Guideline
    ENDPOINT = "guidelines"


class GuideGuidelinesProxy(GuidelinesProxy):
    def __init__(self, client, guide_urn: str) -> None:
        super().__init__(client)
        self.guide_urn = guide_urn

    @property
    def _by_guide_endpoint(self) -> str:
        return f"{self.ENDPOINT}/by-guide/{self.guide_urn}"

    def _fetch_urns(self, *, limit: int, offset: int = 0) -> List[str]:
        resp = self.client.get(
            self._by_guide_endpoint,
            limit=limit,
            offset=offset,
        )
        payload = resp.json()
        return self._parse_list_result(payload)

    def _get_entity(self, urn: str, *, lazy: bool = False) -> BaseEntity:
        entity = super()._get_entity(urn, lazy=lazy)
        if lazy:
            return entity
        if entity.guide_urn != self.guide_urn:
            raise KeyError(
                f"Guideline '{urn}' does not belong to guide '{self.guide_urn}'."
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
        payload["guide_urn"] = self.guide_urn
        return super().create(
            urn=urn,
            identifier=identifier,
            **payload,
        )

    def _parse_search_results(self, payload: Any) -> List[Guideline]:
        result = BaseEntity._extract_result(payload)
        items = result.get("results", []) if isinstance(result, dict) else result

        if not isinstance(items, list):
            raise ValueError(f"Unexpected search response format: {items!r}")

        guidelines = []
        for item in items:
            if isinstance(item, dict) and "id" in item:
                guidelines.append(self.ENTITY_CLS(client=self.client, data=item))
            elif isinstance(item, str):
                guidelines.append(self._get_entity(item))
            else:
                raise ValueError(f"Unexpected guideline search item: {item!r}")

        return guidelines

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
    ) -> List[Guideline]:
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

        resp = self.client.post(f"{self._by_guide_endpoint}/search", json=payload)
        return self._parse_search_results(resp.json())

    def by_page(self, page_no: int) -> List[Guideline]:
        if not isinstance(page_no, int):
            raise TypeError(f"Page number must be an int, got {type(page_no)!r}.")
        if page_no < 0:
            raise ValueError("Page number must be non-negative.")

        filters = [
            f'guide_urn:"{self.guide_urn}"',
            f"page_no:{page_no}",
        ]
        resp = self.client.post(
            f"{self.ENDPOINT}/search",
            json={
                "limit": 1000,
                "offset": 0,
                "fq": filters,
            },
        )
        return self._parse_search_results(resp.json())


class GuidePageProxy:
    def __init__(self, guidelines: GuideGuidelinesProxy) -> None:
        self.guidelines = guidelines

    def __getitem__(self, page_no: int) -> List[Guideline]:
        return self.guidelines.by_page(page_no)
