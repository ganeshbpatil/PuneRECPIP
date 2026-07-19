"""Structured output contract for Module 5 (AI Enrichment). One Pydantic
model drives everything: the JSON schema handed to the AI provider (Claude
tool-use / OpenAI structured outputs both consume `.model_json_schema()`
directly, so the schema is defined exactly once), response validation, and
the shape persisted verbatim as `ai_summaries.structured_json`.

Field selection matches the master prompt's AI Extraction spec: business
category, the twelve property-specialization flags, residential-vs-commercial
and sales-vs-leasing focus, areas served, years in business, ideal customer
profile, developers represented, and an overall confidence score — plus a
short Markdown profile (`ai_summaries.summary_markdown`), satisfying "Store
JSON and Markdown summaries."
"""

from typing import Literal

from pydantic import BaseModel, Field

from corelib.enums import PropertySpecialization


class SpecializationAssessment(BaseModel):
    specialization: PropertySpecialization
    confidence: float = Field(ge=0.0, le=1.0)


class CompanyExtraction(BaseModel):
    company_name: str = Field(description="The company's name as stated on its own website")
    business_category: str = Field(
        description=(
            "Best free-text label for what kind of real estate business this is, e.g. "
            "'Broker', 'Channel Partner', 'Developer', 'Consultant', 'Leasing Firm', "
            "'Property Management Company'. Matched against a curated taxonomy afterward "
            "— pick the most natural label, do not try to guess exact taxonomy wording."
        )
    )
    services: list[str] = Field(
        default_factory=list, description="Concrete services offered, as short phrases"
    )
    specializations: list[SpecializationAssessment] = Field(
        default_factory=list,
        description=(
            "Only include property specializations the content actually supports; omit "
            "ones with no evidence rather than guessing"
        ),
    )
    residential_vs_commercial_focus: Literal["residential", "commercial", "both", "unclear"]
    sales_vs_leasing_focus: Literal["sales", "leasing", "both", "unclear"]
    areas_served: list[str] = Field(
        default_factory=list,
        description="Locality/city/neighbourhood names the company states it serves",
    )
    year_established: int | None = Field(
        default=None,
        description="Only if explicitly stated in the content (e.g. 'since 2010'); do not infer",
    )
    ideal_customer_profile: str | None = Field(
        default=None,
        description="Who this business is best suited to serve, in one or two sentences",
    )
    developers_represented: list[str] = Field(
        default_factory=list,
        description="Developer/builder names explicitly mentioned as partners",
    )
    contact_summary: str | None = Field(
        default=None,
        description=(
            "One-line note on how to reach them, if notable beyond the raw "
            "phone/email already on file"
        ),
    )
    confidence_score: float = Field(
        ge=0.0, le=1.0, description="Overall confidence in this extraction as a whole"
    )
    summary_markdown: str = Field(
        description=(
            "A concise (roughly 150-400 word) Markdown company profile synthesizing the above"
        )
    )
