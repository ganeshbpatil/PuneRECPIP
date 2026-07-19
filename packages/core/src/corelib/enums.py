"""Enumerations shared by every SQLAlchemy model and, later, Pydantic schema.

Stored as ``VARCHAR + CHECK`` (``native_enum=False``) rather than native Postgres
``ENUM`` types: this schema gains new job types, statuses, and categories every
module (3-12), and VARCHAR+CHECK evolves with a plain column/constraint migration
instead of the non-transactional ``ALTER TYPE ... ADD VALUE`` dance.
"""

from enum import StrEnum


class RoleName(StrEnum):
    ADMIN = "admin"
    ANALYST = "analyst"
    SALES = "sales"
    VIEWER = "viewer"


class CompanyStatus(StrEnum):
    DISCOVERED = "discovered"
    CRAWLING = "crawling"
    CRAWLED = "crawled"
    ENRICHING = "enriching"
    ENRICHED = "enriched"
    VERIFIED = "verified"
    MERGED = "merged"
    INACTIVE = "inactive"
    REJECTED = "rejected"


class DataSource(StrEnum):
    CRAWL = "crawl"
    AI_EXTRACTION = "ai_extraction"
    MANUAL = "manual"
    DIRECTORY = "directory"
    RERA_REGISTRY = "rera_registry"
    GOOGLE_MAPS = "google_maps"
    SOCIAL_MEDIA = "social_media"
    SYSTEM = "system"


class PropertySpecialization(StrEnum):
    RESIDENTIAL_SALES = "residential_sales"
    COMMERCIAL_SALES = "commercial_sales"
    RESIDENTIAL_LEASING = "residential_leasing"
    COMMERCIAL_LEASING = "commercial_leasing"
    LUXURY = "luxury"
    INDUSTRIAL = "industrial"
    RETAIL = "retail"
    OFFICE = "office"
    WAREHOUSE = "warehouse"
    LAND = "land"
    INVESTMENT = "investment"
    PROPERTY_MANAGEMENT = "property_management"


class AddressType(StrEnum):
    REGISTERED = "registered"
    CORPORATE_OFFICE = "corporate_office"
    BRANCH_OFFICE = "branch_office"
    SITE_OFFICE = "site_office"


class PhoneType(StrEnum):
    MOBILE = "mobile"
    LANDLINE = "landline"
    WHATSAPP = "whatsapp"
    FAX = "fax"


class EmailType(StrEnum):
    GENERAL = "general"
    SALES = "sales"
    SUPPORT = "support"
    LEASING = "leasing"
    CAREERS = "careers"
    PERSONAL = "personal"


class WebsiteStatus(StrEnum):
    ACTIVE = "active"
    BROKEN = "broken"
    REDIRECT = "redirect"
    PARKED = "parked"
    UNKNOWN = "unknown"


class PageType(StrEnum):
    """Deterministic, keyword-based per-page classification used to decide which
    internal links a crawl follows (Module 4). Not the AI-driven business
    classification of Module 5 — this only routes/labels pages within a site."""

    HOME = "home"
    ABOUT = "about"
    SERVICES = "services"
    TEAM = "team"
    CONTACT = "contact"
    PROJECTS = "projects"
    DEVELOPERS = "developers"
    OTHER = "other"


class SocialPlatform(StrEnum):
    LINKEDIN = "linkedin"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    YOUTUBE = "youtube"
    X = "x"


class DeveloperPartnershipType(StrEnum):
    CHANNEL_PARTNER = "channel_partner"
    EXCLUSIVE_AGENT = "exclusive_agent"
    EMPANELLED_BROKER = "empanelled_broker"
    SUB_BROKER = "sub_broker"
    MARKETING_PARTNER = "marketing_partner"


class ProjectType(StrEnum):
    RESIDENTIAL = "residential"
    COMMERCIAL = "commercial"
    MIXED_USE = "mixed_use"
    INDUSTRIAL = "industrial"
    RETAIL = "retail"
    LAND = "land"


class ProjectStatus(StrEnum):
    PLANNED = "planned"
    UNDER_CONSTRUCTION = "under_construction"
    READY_TO_MOVE = "ready_to_move"
    COMPLETED = "completed"
    ON_HOLD = "on_hold"


class CompanyProjectRole(StrEnum):
    MARKETING_PARTNER = "marketing_partner"
    SOLE_SELLING_AGENT = "sole_selling_agent"
    CHANNEL_PARTNER = "channel_partner"
    CO_BROKER = "co_broker"


class ServiceAreaType(StrEnum):
    STATE = "state"
    CITY = "city"
    ZONE = "zone"
    NEIGHBOURHOOD = "neighbourhood"
    PINCODE = "pincode"


class RERARegistrantType(StrEnum):
    AGENT = "agent"
    PROMOTER = "promoter"


class RERAStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    SUSPENDED = "suspended"


class ChangeSource(StrEnum):
    CRAWL = "crawl"
    AI_EXTRACTION = "ai_extraction"
    MANUAL = "manual"
    DEDUP_MERGE = "dedup_merge"
    RERA_SYNC = "rera_sync"
    SOCIAL_SYNC = "social_sync"
    SYSTEM = "system"


class ScrapeJobType(StrEnum):
    DISCOVERY = "discovery"
    CRAWL = "crawl"
    EXTRACTION = "extraction"
    SOCIAL_ENRICHMENT = "social_enrichment"
    RERA_ENRICHMENT = "rera_enrichment"
    DEDUP = "dedup"
    GEO_RESOLUTION = "geo_resolution"
    LEAD_SCORING = "lead_scoring"
    SEARCH_INDEXING = "search_indexing"
    SCHEDULED_REFRESH = "scheduled_refresh"
    CHANGE_DETECTION = "change_detection"


class ScrapeJobStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


class LogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
