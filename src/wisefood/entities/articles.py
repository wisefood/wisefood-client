# entities/articles.py
from typing import List, Optional

from .base import BaseEntity, BaseCollectionProxy, Field


class Article(BaseEntity):
    """
    Schema for /articles entities.

    All attributes here are thin accessors over `self.data`.
    """

    ENDPOINT = "articles"
    URN_PREFIX = "urn:article:"

    # Core metadata
    id: str = Field("id", read_only=True)
    title: str = Field("title", default="")
    description: Optional[str] = Field("description")
    status: str = Field("status", default="active")
    type: str = Field("type", default="article")

    # Links / identifiers
    url: Optional[str] = Field("url")
    license: Optional[str] = Field("license")
    external_id: Optional[str] = Field("external_id")
    doi: Optional[str] = Field("doi")
    organization_urn: Optional[str] = Field("organization_urn")

    # Content-ish fields
    abstract: Optional[str] = Field("abstract")
    category: Optional[str] = Field("category")
    content: str = Field("content", default="")
    venue: Optional[str] = Field("venue")
    publication_year: Optional[str] = Field("publication_year")

    # Authorship & tags
    authors: List[str] = Field("authors", default_factory=list)
    tags: List[str] = Field("tags", default_factory=list)
    ai_tags: List[str] = Field("ai_tags", default_factory=list)
    language: Optional[str] = Field("language")

    # Classification
    region: Optional[str] = Field("region")
    ai_category: Optional[str] = Field("ai_category")

    # Key takeaways
    key_takeaways: List[str] = Field("key_takeaways", default_factory=list)
    ai_key_takeaways: List[str] = Field("ai_key_takeaways", default_factory=list)

    # Timestamps / system fields
    creator: Optional[str] = Field("creator", read_only=True)
    created_at: Optional[str] = Field("created_at", read_only=True)
    updated_at: Optional[str] = Field("updated_at", read_only=True)
    embedded_at: Optional[str] = Field("embedded_at")

    # Extra metadata
    extras: Optional[dict] = Field("extras")


class ArticlesProxy(BaseCollectionProxy):
    ENTITY_CLS = Article
    ENDPOINT = "articles"
