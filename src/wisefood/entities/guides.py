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
    life_stage: List[str] = Field("life_stage", default_factory=list)
    age_min_months: Optional[int] = Field("age_min_months")
    age_max_months: Optional[int] = Field("age_max_months")
    setting: List[str] = Field("setting", default_factory=list)
    health_conditions: List[str] = Field("health_conditions", default_factory=list)
    nutrients: List[str] = Field("nutrients", default_factory=list)
    guideline_type: Optional[str] = Field("guideline_type")
    topic: List[str] = Field("topic", default_factory=list)
    audience: List[str] = Field("audience", default_factory=list)
    applicable_regions: List[str] = Field("applicable_regions", default_factory=list)
    extractor_name: Optional[str] = Field("extractor_name")
    extractor_run_id: Optional[str] = Field("extractor_run_id")
    extraction_model: Optional[str] = Field("extraction_model")
    enrichment_version: Optional[int] = Field("enrichment_version", read_only=True)
    enrichment_confidence: Optional[float] = Field("enrichment_confidence", read_only=True)
    ai_generated_fields: List[str] = Field("ai_generated_fields", default_factory=list)
    enhancements: Optional[List[Dict[str, Any]]] = Field("enhancements", read_only=True)
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

    def enrich(
        self,
        identifier: str,
        *,
        agent: str,
        fields: Dict[str, Any],
        force_fields: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Machine-enrich a single guideline (PATCH /guidelines/{id}/enrich).

        Human-edited values are preserved server-side unless listed in
        ``force_fields``.
        """
        payload: Dict[str, Any] = {"agent": agent, "fields": fields}
        if force_fields:
            payload["force_fields"] = force_fields
        resp = self.client.patch(f"{self.ENDPOINT}/{identifier}/enrich", json=payload)
        return BaseEntity._extract_result(resp.json())

    def enrich_batch(
        self,
        *,
        agent: str,
        items: List[Dict[str, Any]],
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Machine-enrich up to 200 guidelines in one call.

        Each item is ``{"id": <uuid>, "fields": {...}, "force_fields": [...]}``.
        With ``dry_run=True`` the server reports what would be written without
        writing anything.
        """
        resp = self.client.post(
            f"{self.ENDPOINT}/enrich-batch",
            json={"agent": agent, "items": items, "dry_run": dry_run},
        )
        return BaseEntity._extract_result(resp.json())

    def set_editorial_policy(
        self,
        *,
        ids: Optional[List[str]] = None,
        q: Optional[str] = None,
        fq: Optional[List[str]] = None,
        status: Optional[str] = None,
        review_status: Optional[str] = None,
        visibility: Optional[str] = None,
        applicability_status: Optional[str] = None,
        max_docs: Optional[int] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Bulk-edit guideline lifecycle state (POST /guidelines/editorial-policy).

        Requires admin. Selection needs ids, q, or fq; always preview a
        query-driven edit with ``dry_run=True`` first.
        """
        payload: Dict[str, Any] = {"dry_run": dry_run}
        if ids:
            payload["ids"] = ids
        if q is not None:
            payload["q"] = q
        if fq is not None:
            payload["fq"] = fq
        if status is not None:
            payload["status"] = status
        if review_status is not None:
            payload["review_status"] = review_status
        if visibility is not None:
            payload["visibility"] = visibility
        if applicability_status is not None:
            payload["applicability_status"] = applicability_status
        if max_docs is not None:
            payload["max_docs"] = max_docs
        resp = self.client.post(f"{self.ENDPOINT}/editorial-policy", json=payload)
        return BaseEntity._extract_result(resp.json())


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

    def bulk_import(self, guidelines: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Create many guidelines for this guide in one request.

        Creating them one at a time costs an HTTP round trip per rule, and each
        one re-resolves the guide and its artifacts server-side. Prefer this for
        anything larger than a handful. The server caps a batch at 1000.
        """
        resp = self.client.post(
            f"{self._by_guide_endpoint}/import",
            json={"guidelines": guidelines},
        )
        return BaseEntity._extract_result(resp.json())

    def fetch_all(self, *, page_size: int = 500, fl: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Every guideline on this guide, as plain dicts.

        Deliberately not `proxy[0:n]`: that returns lazy proxies which fetch
        themselves individually on first attribute access, so reading one field
        off 500 rules costs 500 HTTP requests.
        """
        collected: List[Dict[str, Any]] = []
        offset = 0

        while True:
            payload = {
                "limit": page_size,
                "offset": offset,
                "sort": "sequence_no asc",
            }
            if fl:
                payload["fl"] = fl

            resp = self.client.post(f"{self._by_guide_endpoint}/search", json=payload)
            result = BaseEntity._extract_result(resp.json())
            items = result.get("results", []) if isinstance(result, dict) else result
            if not items:
                return collected

            collected.extend(item for item in items if isinstance(item, dict))
            if len(items) < page_size:
                return collected
            offset += len(items)

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
