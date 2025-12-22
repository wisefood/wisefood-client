# entities/articles.py
from typing import List, Optional

from .base import BaseEntity, BaseCollectionProxy, Field

class FCTable(BaseEntity):
    """
    Schema-backed entity for /fctables. Thin accessors over `self.data`.
    Adapted to represent a Food Composition Table (FCT).
    """

    ENDPOINT = "fctables"
    URN_PREFIX = "urn:fctable:"

    # Core metadata
    id: str = Field("id", read_only=True)
    title: str = Field("title", default="")
    description: Optional[str] = Field("description")
    status: str = Field("status", default="active")
    type: str = Field("type", default="food_composition_table")

    # Specific metadata from FoodCompositionTableSchema
    compiling_institution: str = Field("compiling_institution", default="")
    database_name: str = Field("database_name", default="")

    classification_schemes: List[str] = Field("classification_schemes", default_factory=list)
    standardization_schemes: List[str] = Field("standardization_schemes", default_factory=list)

    measurement_units: List[str] = Field("measurement_units", default_factory=list)
    reference_portions: List[str] = Field("reference_portions", default_factory=list)

    completeness_percent: Optional[float] = Field("completeness_percent")
    completeness_description: Optional[str] = Field("completeness_description")
    nutrient_coverage: List[str] = Field("nutrient_coverage", default_factory=list)

    data_formats: List[str] = Field("data_formats", default_factory=list)
    tasks_supported: List[str] = Field("tasks_supported", default_factory=list)

    number_of_entries: Optional[int] = Field("number_of_entries")
    min_nutrients_per_item: Optional[int] = Field("min_nutrients_per_item")
    max_nutrients_per_item: Optional[int] = Field("max_nutrients_per_item")

    # Links / identifiers
    url: Optional[str] = Field("url")
    license: Optional[str] = Field("license")
    external_id: Optional[str] = Field("external_id")
    organization_urn: Optional[str] = Field("organization_urn")

    # Content-ish fields (kept for compatibility)
    abstract: Optional[str] = Field("abstract")
    category: Optional[str] = Field("category")
    content: str = Field("content", default="")
    venue: str = Field("venue", default="")

    # Authorship & tags
    authors: List[str] = Field("authors", default_factory=list)
    tags: List[str] = Field("tags", default_factory=list)
    language: Optional[str] = Field("language")

    # Artifacts & region
    artifacts: List[dict] = Field("artifacts", default_factory=list)
    region: Optional[str] = Field("region")

    # Timestamps / system fields
    creator: Optional[str] = Field("creator", read_only=True)
    created_at: Optional[str] = Field("created_at", read_only=True)
    updated_at: Optional[str] = Field("updated_at", read_only=True)


class FCTablesProxy(BaseCollectionProxy):
    ENTITY_CLS = FCTable
    ENDPOINT = "fctables"


