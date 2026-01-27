"""
Pydantic Models for Case Study Extraction.

Based on the LLM Case Study Extraction Output Schema Draft.
This schema captures all the key information from a Treya Partners project.

SCHEMA VERSION: v1
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================

class OperatingModel(str, Enum):
    """Procurement operating model types."""
    CENTRALIZED = "centralized"
    DECENTRALIZED = "decentralized"
    HYBRID = "hybrid"
    UNKNOWN = "unknown"


class Maturity(str, Enum):
    """Procurement maturity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class CategoryStatus(str, Enum):
    """Status of a spend category in the project."""
    # Core statuses
    IDENTIFIED = "identified"
    NEGOTIATED = "negotiated"
    IMPLEMENTED = "implemented"
    NOT_PURSUED = "not_pursued"
    UNKNOWN = "unknown"
    
    # In-progress statuses
    IN_PROGRESS = "in_progress"
    IMPLEMENTATION = "implementation"
    AWARD_REVIEW = "award_review"
    REPORTING = "reporting"
    RFP = "rfp"
    ANALYSIS = "analysis"
    
    # Completed aliases
    COMPLETE = "complete"
    COMPLETED = "completed"
    CLOSED = "closed"


class FeeType(str, Enum):
    """Types of fee structures."""
    FIXED = "fixed"
    HYBRID = "hybrid"
    CONTINGENT = "contingent"
    UNKNOWN = "unknown"


# =============================================================================
# Supporting Types
# =============================================================================

class ClaimMoney(BaseModel):
    """A monetary claim with optional evidence and confidence."""
    amount: Optional[float] = Field(None, description="Dollar amount")
    currency: str = Field(default="USD", description="Currency code")
    confidence: Optional[str] = Field(None, description="low/medium/high confidence in this number")
    source_file: Optional[str] = Field(None, description="File this was extracted from")
    notes: Optional[str] = Field(None, description="Additional context about this amount")


class ClaimNumber(BaseModel):
    """A numeric claim with optional evidence."""
    value: Optional[float] = Field(None, description="Numeric value")
    unit: Optional[str] = Field(None, description="Unit (days, percent, count, etc.)")
    confidence: Optional[str] = Field(None, description="low/medium/high confidence")
    source_file: Optional[str] = Field(None, description="File this was extracted from")
    notes: Optional[str] = Field(None, description="Additional context")


class Evidence(BaseModel):
    """Evidence supporting a claim."""
    source_file: str = Field(..., description="Relative path to source file")
    page_or_slide: Optional[str] = Field(None, description="Page number, slide number, or sheet name")
    quote: Optional[str] = Field(None, description="Relevant quote or excerpt")
    date_extracted: Optional[str] = Field(None, description="When this was found in the file name/content")


# =============================================================================
# 1) Project Scope, Timing, and Fees
# =============================================================================

class ProjectScope(BaseModel):
    """Project scope, timing, and fee information."""
    
    # Engagement type
    engagement_type: Optional[str] = Field(
        None,
        description="Type of engagement: broad multi-category strategic sourcing, rapid cost takeout, pre-sale value maximization, post-merger synergy, etc."
    )
    
    # Fee structure
    fee_type: Optional[FeeType] = Field(None, description="Fee structure type")
    fee_amount: Optional[ClaimMoney] = Field(None, description="Fixed fee amount if applicable")
    fee_hybrid_threshold: Optional[ClaimMoney] = Field(None, description="Threshold for hybrid fee model")
    fee_contingent_percentage: Optional[float] = Field(None, description="Contingent percentage (0-100)")
    fee_notes: Optional[str] = Field(None, description="Additional fee structure details")
    
    # Initial scope
    initial_categories_count: Optional[int] = Field(None, description="Number of categories in initial scope")
    addressable_spend: Optional[ClaimMoney] = Field(None, description="Total addressable spend")
    savings_estimate_low: Optional[ClaimMoney] = Field(None, description="Low estimate of savings")
    savings_estimate_high: Optional[ClaimMoney] = Field(None, description="High estimate of savings")
    
    # COGS focus (if applicable)
    cogs_categories_count: Optional[int] = Field(None, description="Number of COGS categories")
    cogs_categories_percentage: Optional[float] = Field(None, description="COGS categories as % of total")
    cogs_spend_addressed: Optional[ClaimMoney] = Field(None, description="COGS spend addressed")
    cogs_categories_list: Optional[List[str]] = Field(None, description="List of specific COGS categories")
    
    # Non-savings objectives
    operational_objectives: Optional[List[str]] = Field(
        None,
        description="Non-savings related process/operational objectives"
    )
    
    # Timing
    start_date: Optional[date] = Field(None, description="Project start date")
    end_date: Optional[date] = Field(None, description="Project end date or expected end")
    
    # Source
    source_folder_url: Optional[str] = Field(None, description="SharePoint or source folder URL")


# =============================================================================
# 2) Client Context
# =============================================================================

class SizeMetrics(BaseModel):
    """Client size metrics."""
    revenue: Optional[ClaimMoney] = Field(None, description="Annual revenue - USE WEB SEARCH if not in docs")
    ebitda: Optional[ClaimMoney] = Field(None, description="EBITDA if available")
    locations_count: Optional[int] = Field(None, description="Number of locations/sites")
    locations_source: Optional[str] = Field(None, description="Source file for locations count")
    locations_confidence: Optional[str] = Field(None, description="Confidence: high/medium/low")
    employees_count: Optional[int] = Field(None, description="Number of employees")


class ClientContext(BaseModel):
    """Information about the client."""
    
    client_name: str = Field(..., description="Client company name")
    
    # Industry
    industry_primary: Optional[str] = Field(None, description="Primary industry")
    industry_secondary: Optional[str] = Field(None, description="Secondary industry if applicable")
    primary_industry_sector: Optional[str] = Field(
        None, 
        description="Industry cluster classification from predefined list of 11 sectors"
    )
    
    # Business model
    business_model: Optional[str] = Field(
        None,
        description="Business model: manufacturer, distributor, services, healthcare, multi-site, etc."
    )
    
    # Ownership
    sponsor_pe_firm: Optional[str] = Field(None, description="PE sponsor/owner if applicable")
    
    # History/background
    client_history: Optional[str] = Field(
        None,
        description="Client background: founder-run, first institutional equity, multiple PE turns, roll-up, M&A history, etc."
    )
    
    # Size
    size_metrics: Optional[SizeMetrics] = Field(None, description="Size metrics")


# =============================================================================
# 3) Engagement Background
# =============================================================================

class ProcurementEnvironment(BaseModel):
    """Client's procurement environment context."""
    operating_model: Optional[OperatingModel] = Field(None, description="Procurement operating model")
    maturity: Optional[Maturity] = Field(None, description="Procurement maturity level")
    data_availability: Optional[str] = Field(
        None,
        description="Data availability: poor/good, decentralized, multiple supplier accounts, etc."
    )
    data_quality_notes: Optional[str] = Field(None, description="Notes on data quality challenges")
    source_file: Optional[str] = Field(None, description="Document where procurement environment was assessed")
    confidence: Optional[str] = Field(None, description="Confidence level: high/medium/low")


class EngagementBackground(BaseModel):
    """Background context for the engagement."""
    
    objective: Optional[str] = Field(
        None,
        description="One-sentence 'why' - primary objective of the engagement"
    )
    
    scope_summary: Optional[str] = Field(
        None,
        description="Short paragraph describing what's in/out of scope"
    )
    
    constraints_challenges: Optional[List[str]] = Field(
        None,
        description="Array of constraints or challenges faced"
    )
    
    procurement_environment: Optional[ProcurementEnvironment] = Field(
        None,
        description="Context about client's procurement environment"
    )


# =============================================================================
# 4) Impact
# =============================================================================

class TimeToValue(BaseModel):
    """Time to value metrics."""
    value_realized_in_days: Optional[ClaimNumber] = Field(None, description="Days to realize value")
    notes: Optional[str] = Field(None, description="Additional context")


class ProofPoint(BaseModel):
    """A short, defensible proof point for marketing/sales."""
    statement: str = Field(..., description="The proof point statement")
    category: Optional[str] = Field(None, description="Related category if applicable")
    evidence: Optional[List[Evidence]] = Field(None, description="Supporting evidence")


class Financials(BaseModel):
    """Financial impact metrics."""
    annual_savings: Optional[ClaimMoney] = Field(None, description="Annual run-rate savings")
    one_time_savings: Optional[ClaimMoney] = Field(None, description="One-time savings")


class ImpactSummary(BaseModel):
    """High-level impact summary."""
    headline: Optional[str] = Field(
        None,
        description="Marketing-safe headline (e.g., '$X run-rate savings across Y categories')"
    )
    narrative: str = Field(
        ...,
        description="2-4 sentence narrative describing the impact"
    )


class Impact(BaseModel):
    """Overall project impact."""
    
    summary: ImpactSummary = Field(..., description="High-level impact summary")
    
    financials: Optional[Financials] = Field(None, description="Financial impact metrics")
    
    time_to_value: Optional[TimeToValue] = Field(None, description="Time to value metrics")
    
    operational_improvements: Optional[str] = Field(
        None,
        description="Description of operational improvements achieved"
    )
    
    proof_points: Optional[List[ProofPoint]] = Field(
        None,
        description="Short, defensible bullets for marketing/sales"
    )


# =============================================================================
# 5) Categories (Spend Category Outcomes)
# =============================================================================

class CategoryConstraints(BaseModel):
    """Constraints specific to a category."""
    supplier_constraints: Optional[List[str]] = Field(
        None,
        description="Must-use, diversity requirements, preferred vendors"
    )
    operational_constraints: Optional[List[str]] = Field(
        None,
        description="No downtime, spec lock, clinical constraints"
    )
    contractual_constraints: Optional[List[str]] = Field(
        None,
        description="Existing terms, renewals, exclusivity"
    )
    implementation_constraints: Optional[List[str]] = Field(
        None,
        description="Labor relations, seasonality, regulatory"
    )


class CategoryOutcome(BaseModel):
    """Outcome for a single spend category."""
    
    category_label: str = Field(..., description="Category name (e.g., 'Telecom', 'IT Hardware')")
    
    # Optional taxonomy (L1/L2/L3)
    category_l1: Optional[str] = Field(None, description="Level 1 category")
    category_l2: Optional[str] = Field(None, description="Level 2 category")
    category_l3: Optional[str] = Field(None, description="Level 3 category")
    
    # Timing
    start_date: Optional[date] = Field(None, description="Category work start date")
    end_date: Optional[date] = Field(None, description="Category work end date")
    
    # Status
    status: Optional[CategoryStatus] = Field(None, description="Current status of the category")
    
    # Vendors - Pre and Post Sourcing
    vendors_before: Optional[List[str]] = Field(
        None,
        description="Vendors used BEFORE sourcing (e.g., 'Multiple local suppliers', 'Henry Schein')"
    )
    vendors_after: Optional[List[str]] = Field(
        None,
        description="Vendors used AFTER sourcing with context (e.g., 'McKesson (GPO contract)', 'Incumbent - renegotiated terms')"
    )
    
    # Levers used
    levers: Optional[List[str]] = Field(
        None,
        description="Savings levers used: consolidation, rate_reduction, term_improvement, etc."
    )
    
    # Constraints
    constraints: Optional[CategoryConstraints] = Field(None, description="Category-specific constraints")
    
    # Savings
    savings_annual_run_rate: Optional[ClaimMoney] = Field(None, description="Annual run-rate savings")
    savings_one_time: Optional[ClaimMoney] = Field(None, description="One-time savings")
    
    # Additional info
    baseline_spend: Optional[ClaimMoney] = Field(None, description="Baseline spend in this category")
    savings_percentage: Optional[float] = Field(None, description="Savings as percentage of baseline")
    
    notes: Optional[str] = Field(None, description="Additional notes about this category")
    
    evidence: Optional[List[Evidence]] = Field(None, description="Evidence supporting category claims")


# =============================================================================
# 6) Case Study Packaging
# =============================================================================

class CaseStudyPackaging(BaseModel):
    """How to present the case study for marketing/sales."""
    
    # Ready flag
    case_study_ready: bool = Field(
        default=False,
        description="Whether this case study has enough info to be marketing-ready"
    )
    
    headline: Optional[str] = Field(
        None,
        description="One-liner headline: '$X run-rate savings across Y categories'"
    )
    
    client_problem_statement: Optional[str] = Field(
        None,
        description="What problem was the client facing"
    )
    
    client_problem_anonymized: Optional[str] = Field(
        None,
        description="Anonymized version of client problem: company name replaced with industry descriptor, PE firm name genericized, and PE expectations softened"
    )
    
    approach_summary: Optional[List[str]] = Field(
        None,
        description="3-5 bullet points describing Treya's approach"
    )
    
    top_levers: Optional[List[str]] = Field(
        None,
        description="Ranked list of top savings levers used"
    )
    
    value_delivered_blurb: Optional[str] = Field(
        None,
        description="Short blurb about value delivered"
    )
    
    where_we_were_unique: Optional[List[str]] = Field(
        None,
        description="What made Treya unique: speed, data approach, negotiations, etc."
    )


# =============================================================================
# MAIN SCHEMA: Case Study
# =============================================================================

class CaseStudy(BaseModel):
    """
    Complete case study extraction from a Treya Partners project.
    
    This is the top-level model that contains all extracted information.
    """
    
    # Metadata
    schema_version: str = Field(default="v1", description="Schema version")
    extraction_date: Optional[str] = Field(None, description="When this was extracted")
    extraction_model: Optional[str] = Field(None, description="LLM model used for extraction")
    source_project_path: Optional[str] = Field(None, description="Path to source project folder")
    
    # Main sections
    client: ClientContext = Field(..., description="Client information")
    project_scope: Optional[ProjectScope] = Field(None, description="Project scope, timing, and fees")
    engagement_background: Optional[EngagementBackground] = Field(None, description="Engagement context")
    impact: Optional[Impact] = Field(None, description="Overall project impact")
    categories: List[CategoryOutcome] = Field(default_factory=list, description="Category-level outcomes")
    case_study_packaging: Optional[CaseStudyPackaging] = Field(None, description="Marketing-ready packaging")
    
    # Extraction notes
    extraction_notes: Optional[List[str]] = Field(
        None,
        description="Notes from the extraction process (gaps, uncertainties, etc.)"
    )
    files_analyzed: Optional[List[str]] = Field(
        None,
        description="List of files that were analyzed for extraction"
    )
