"""Unit tests: no database needed. Guards against import cycles, missing
model registrations, and enum/table naming regressions as new models are added."""

from corelib import enums
from corelib.models import Base

EXPECTED_TABLES = {
    "addresses",
    "ai_summaries",
    "audit_logs",
    "business_categories",
    "change_history",
    "companies",
    "company_categories",
    "company_developer_partnerships",
    "company_projects",
    "company_specializations",
    "contacts",
    "crawl_snapshots",
    "developers",
    "emails",
    "google_maps_listings",
    "lead_scores",
    "logs",
    "merge_history",
    "phone_numbers",
    "projects",
    "rera_details",
    "roles",
    "scrape_jobs",
    "service_areas",
    "social_profiles",
    "user_roles",
    "users",
    "websites",
}


def test_all_expected_tables_are_registered_on_metadata():
    assert set(Base.metadata.tables.keys()) == EXPECTED_TABLES


def test_every_table_has_a_primary_key():
    for table in Base.metadata.tables.values():
        assert table.primary_key is not None and len(table.primary_key.columns) > 0, table.name


def test_property_specialization_enum_covers_master_prompt_flags():
    values = {member.value for member in enums.PropertySpecialization}
    assert values == {
        "residential_sales",
        "commercial_sales",
        "residential_leasing",
        "commercial_leasing",
        "luxury",
        "industrial",
        "retail",
        "office",
        "warehouse",
        "land",
        "investment",
        "property_management",
    }


def test_role_enum_matches_rbac_roles():
    assert {member.value for member in enums.RoleName} == {"admin", "analyst", "sales", "viewer"}
