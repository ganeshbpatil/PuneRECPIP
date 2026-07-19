"""Import every model module so `Base.metadata` is fully populated before Alembic
autogeneration or `Base.metadata.create_all()` runs. Import this package (not an
individual model module) whenever you need the full schema registered."""

from corelib.models.address import Address
from corelib.models.ai_summary import AISummary
from corelib.models.audit import AuditLog
from corelib.models.base import Base
from corelib.models.business_category import BusinessCategory
from corelib.models.change_history import ChangeHistory
from corelib.models.company import Company, CompanyCategory
from corelib.models.contact import Contact
from corelib.models.developer import CompanyDeveloperPartnership, Developer
from corelib.models.email import EmailAddress
from corelib.models.gmaps import GoogleMapsListing
from corelib.models.lead_score import LeadScore
from corelib.models.log import JobLog
from corelib.models.merge_history import MergeHistory
from corelib.models.phone import PhoneNumber
from corelib.models.project import CompanyProject, Project
from corelib.models.rera import RERADetail
from corelib.models.scrape_job import ScrapeJob
from corelib.models.service_area import ServiceArea
from corelib.models.social import SocialProfile
from corelib.models.specialization import CompanySpecialization
from corelib.models.user import Role, User, UserRole
from corelib.models.website import Website

__all__ = [
    "Base",
    "Address",
    "AISummary",
    "AuditLog",
    "BusinessCategory",
    "ChangeHistory",
    "Company",
    "CompanyCategory",
    "Contact",
    "CompanyDeveloperPartnership",
    "Developer",
    "EmailAddress",
    "GoogleMapsListing",
    "LeadScore",
    "JobLog",
    "MergeHistory",
    "PhoneNumber",
    "CompanyProject",
    "Project",
    "RERADetail",
    "ScrapeJob",
    "ServiceArea",
    "SocialProfile",
    "CompanySpecialization",
    "Role",
    "User",
    "UserRole",
    "Website",
]
