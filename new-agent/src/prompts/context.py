"""
Background Knowledge and Context Builder.

This module provides the system prompts and context for the LLM.
The prompts are organized in phases to allow for iterative refinement.

PHASES:
- Phase 1: Company Background (who is Treya Partners)
- Phase 2: Project Structure (what the folders mean)
- Phase 3: Analysis Instructions (what to extract)
- Phase 4: Output Format (how to structure responses)

EXTRACTION PASSES:
- Pass 1: File Selection (given directory tree, pick 15-20 key files)
- Pass 2: Schema Extraction (given file contents, fill the Pydantic schema)
"""

from __future__ import annotations

from typing import Optional


class ContextBuilder:
    """
    Builds system prompts with background knowledge.
    
    Each phase can be customized independently.
    Call build_full_context() to get the complete system prompt.
    """
    
    def __init__(self):
        """Initialize with default prompts."""
        # These can be overridden by setting the attributes directly
        pass
    
    def build_full_context(self) -> str:
        """
        Build the complete system prompt from all phases.
        
        Returns:
            Complete system prompt string
        """
        sections = [
            self._phase1_company_background(),
            self._phase2_project_structure(),
            self._phase3_analysis_instructions(),
            self._phase4_output_format(),
        ]
        
        return "\n\n".join(section for section in sections if section)
    
    # =========================================================================
    # PHASE 1: Company Background
    # =========================================================================
    def _phase1_company_background(self) -> str:
        """
        Phase 1: Background about Treya Partners.
        
        CUSTOMIZE THIS to accurately describe the company and its work.
        """
        return """# About Treya Partners

Treya Partners is a procurement and strategic sourcing consulting firm that helps 
companies optimize their spend across various categories. 

## What Treya Does:
- Analyzes client spending patterns across different categories
- Negotiates better rates and contracts with suppliers
- Implements procurement best practices
- Delivers measurable cost savings and value

## Typical Engagement:
1. Initial assessment of client's current spend
2. Identification of savings opportunities by category
3. Strategic sourcing and supplier negotiations
4. Implementation and tracking of savings
5. Ongoing project updates and reporting

## Key Metrics Treya Tracks:
- Addressable spend (total spend that can be optimized)
- Identified savings (potential savings found)
- Implemented savings (actual savings achieved)
- ROI and value delivered to client"""

    # =========================================================================
    # PHASE 2: Project Structure
    # =========================================================================
    def _phase2_project_structure(self) -> str:
        """
        Phase 2: Explanation of the project folder structure.
        
        CUSTOMIZE THIS to match the actual folder conventions used.
        """
        return """# Project Folder Structure

Each client project folder typically contains the following directories:

## Agreement/
Contains contractual documents:
- Master Service Agreements (MSA)
- Statements of Work (SOW)
- Amendment documents
- Fee schedules and payment terms

## Assessment & Proposal/
Contains initial engagement materials:
- Original assessment presentations (usually PPTX or PDF)
- Proposal documents
- Scope definitions
- Baseline spend analysis

## Categories/
Contains work done by Treya organized by spend category.
Common categories include:
- IT/Technology
- Marketing
- Professional Services
- Facilities/Real Estate
- Travel & Expense
- Logistics/Transportation
- HR/Benefits
- Telecom
Each category folder may contain analysis, sourcing documents, and results.

## Project Updates/
Contains periodic status updates:
- Weekly/Monthly update presentations
- Progress reports
- Savings tracking documents
- Timeline/milestone updates
These are time-series documents showing project progression.

## Case Study/
May contain drafted or final case study documents about the engagement.

## Archive/ (IGNORED)
Contains old or outdated files. This folder is intentionally excluded 
from analysis to avoid confusion with outdated information."""

    # =========================================================================
    # PHASE 3: Analysis Instructions
    # =========================================================================
    def _phase3_analysis_instructions(self) -> str:
        """
        Phase 3: Instructions for what the LLM should analyze.
        
        CUSTOMIZE THIS to add specific extraction requirements.
        """
        return """# Analysis Instructions

When analyzing a project folder structure, focus on:

## Key Information to Identify:
1. **Client Name**: The company Treya is working with
2. **Project Timeline**: Start date, current phase, expected completion
3. **Categories in Scope**: Which spend categories are being addressed
4. **Key Documents**: Most important files for understanding the project
5. **Recent Activity**: Latest updates or changes based on folder contents

## What to Look For:
- Patterns in file naming that indicate versions or dates
- Folder organization that suggests project maturity
- Balance of categories (which have more work done)
- Presence of key deliverables (assessments, proposals, updates)

## What to Avoid:
- Making assumptions about file contents you haven't seen
- Speculating on specific numbers without data
- Ignoring folder structure context"""

    # =========================================================================
    # PHASE 4: Output Format
    # =========================================================================
    def _phase4_output_format(self) -> str:
        """
        Phase 4: How the LLM should structure its response.
        
        CUSTOMIZE THIS to match desired output format.
        """
        return """# Output Format

Structure your analysis as follows:

## Project Overview
Brief summary of what this project appears to be about based on the folder structure.

## Key Observations
- Notable patterns in the folder organization
- Important files or folders identified
- Gaps or areas that seem incomplete

## Categories Breakdown
List each category folder found and what it might contain.

## Recommendations
- What additional information would be helpful
- Which folders/files seem most important to review first
- Any concerns or questions about the project structure

## Questions for Clarification
List any ambiguities that would need human clarification."""


# =============================================================================
# EXTRACTION PROMPTS (Pass 1 and Pass 2)
# =============================================================================

# Number of files to select - easy to change!
FILE_SELECTION_COUNT: int = 30  # Increased to capture ALL categories


def get_file_selection_prompt(directory_tree: str) -> str:
    """
    Get the Pass 1 prompt: File Selection.
    
    Given a directory tree, ask LLM to select the most important files
    for extracting case study information.
    
    Args:
        directory_tree: String representation of the project structure
        
    Returns:
        Complete prompt for file selection
    """
    return f"""You are analyzing a Treya Partners project folder to select files for a comprehensive case study extraction.

## Background: Treya Partners
Treya Partners is a procurement consulting firm that helps PE-backed companies achieve cost savings through strategic sourcing across multiple spend categories.

## Project Folder Structure:
```
{directory_tree}
```

## STEP 1: IDENTIFY ALL CATEGORIES
First, look at the directory tree and list ALL spend categories you can find.
Categories appear in:
- `Categories/` folder (each subfolder is a category)
- `Wave 2/Categories/` folder (additional categories)
- Any folder named after a spend type (e.g., "Medical Supplies", "Telecom", "IT Hardware")

## STEP 2: SELECT FILES (Total: {FILE_SELECTION_COUNT} files)

### MANDATORY FILES - MUST INCLUDE:

**1. Agreement Folder (3-5 files) - CRITICAL FOR FEES!**
- Look for: "signed", "final", "executed", "Agreement" in filename
- MUST include the main signed agreement (usually PDF)
- This contains:
  - **Exhibit A**: Categories table with baseline spend and savings estimates
  - **Exhibit B**: Fee structure (fixed fee, contingent %, or hybrid)
- ALL fee and scope data comes from here:
  - Fee type (fixed, contingent, or hybrid - each project has exactly ONE)
  - Fee amount (if fixed or hybrid)
  - Fee percentage (if contingent or hybrid)
  - Addressable spend, savings estimates, initial category count

**2. Case Study Folder (2-3 files)**
- Any file with "Case Study" in the name
- Prioritize: "vF" (version final), latest version numbers

**3. Project Updates - FINAL/CLOSE-OUT (2-3 files)**
- Look for: "Close-out", "Final", "Phase 2", highest dates
- These have ACTUAL results for all categories
- Include the MOST RECENT update for each phase/wave

**4. Assessment/Proposal (1-2 files)**
- Opportunity Assessment files
- Initial proposal with projected savings

### CATEGORY FILES - ONE PER CATEGORY:

**5. For EACH Category You Identified:**
Select 1 file per category that shows:
- Savings analysis or summary (prefer .xlsx with "Analysis" or "Savings")
- RFP results or vendor comparison
- Final negotiation outcomes

Common categories to look for:
- Medical Supplies, Office Supplies, Small Parcel, Courier
- Telecom, IT Hardware/Software, Copiers
- Employee Benefits, HR, Insurance
- Facilities, Janitorial, Laundry
- Path Lab, Billing Systems
- Any other category folders you see

### FILES TO SKIP:
- Raw invoices, payment data, AP files
- Files in "Additional Invoices" folders
- Duplicate versions (keep newest only)
- Archive/ folder contents
- Files ending with "(002)", "(copy)", "backup"
- Individual vendor contracts (unless it's the final negotiated one)

## OUTPUT FORMAT:
Return a JSON object with two parts:

```json
{{
  "categories_found": [
    "Medical Supplies",
    "Office Supplies", 
    "Telecom",
    "... list ALL categories you see in the directory tree"
  ],
  "selected_files": [
    "Agreement/Signed Agreement/Agreement - signed.pdf",
    "Case Study/Treya Case Study vF.pdf",
    "Project Updates/Close-out.pptx",
    "Categories/Medical Supplies/Analysis/Savings Summary.xlsx",
    "... one file per category minimum"
  ]
}}
```

**IMPORTANT**: You must select at least ONE file for EACH category in `categories_found`.
"""


def get_schema_extraction_prompt(
    file_contents: str,
    schema_json: str,
    client_name_hint: Optional[str] = None,
) -> str:
    """
    Get the Pass 2 prompt: Schema Extraction.
    
    Given extracted file contents, fill in the case study schema.
    
    Args:
        file_contents: Concatenated text from selected files
        schema_json: JSON schema defining what to extract
        client_name_hint: Optional hint about client name from folder
        
    Returns:
        Complete prompt for schema extraction
    """
    client_context = ""
    if client_name_hint:
        client_context = f"\n**Hint**: The project folder is named '{client_name_hint}' - this is likely the client name.\n"
    
    return f"""You are extracting structured case study information from Treya Partners project documents.

## Background: Treya Partners
Treya Partners is a procurement consulting firm that helps companies (often PE-backed) achieve cost savings through strategic sourcing. Projects typically involve:
- Analyzing client spend across categories
- Running RFP processes and negotiations
- Implementing savings and tracking results
{client_context}

## Your Task:
Read the extracted document contents below and fill in the case study schema COMPLETELY.

**⚠️ DOCUMENT PRIORITY ORDER ⚠️**
When the same information appears in multiple documents, USE THIS PRIORITY:
1. **Agreement/** documents (highest priority for fees, scope, addressable spend)
2. **Case Study/** documents (for outcomes and narrative)
3. **Project Updates/** - specifically the FINAL/close-out update (for category results)
4. **Assessment/** documents (for projected savings if not in Agreement)
5. Other category-level documents

## CRITICAL REQUIREMENTS:

### 1. SOURCES FOR EVERY FACT
For EVERY ClaimMoney and ClaimNumber field, you MUST include:
- `source_file`: The exact file name where you found this information
- `confidence`: One of "high", "medium", or "low"

### 2. CONFIDENCE LEVEL DEFINITIONS
- **high**: Explicitly stated in a "final", "signed", or "vF" document (agreements, final case studies, close-out reports)
- **medium**: Found in project updates, analysis documents, or assessment materials; may be estimates
- **low**: Inferred from context, found in older documents, or conflicting across sources

### 2b. FIELDS REQUIRING SOURCES
The following fields MUST always have `source_file` and `confidence` populated:
- **Client Overview**: Revenue (from WEB SEARCH), EBITDA, Locations
- **Engagement Background**: `procurement_environment` must include `source_file` and `confidence`
- **Impact**: Annual Savings, One-Time Savings, and each Proof Point (via evidence array)
- **Categories**: All baseline_spend, savings amounts

### 2c. REVENUE - USE WEB SEARCH
For client `revenue`:
- Look in the "Web Search Results" section at the top of the content
- Set `source_file` to "Web Search" (not a document)
- Set `confidence` based on how authoritative the source seems

For `locations_count`:
- If found in documents, set `locations_source` to the document name
- If from web search, set `locations_source` to "Web Search"
- Set `locations_confidence` appropriately

### 3. FEE & SCOPE FIELDS - MUST BE FROM AGREEMENT (CRITICAL!)

**⚠️ STOP AND READ THIS CAREFULLY ⚠️**

When extracting fee and scope data, you MUST:
1. **FIRST** search for documents with "Agreement" in the file path
2. **LOOK for "Exhibit B" or "Project Fees"** - this is where fee structure lives
3. **ONLY use Agreement values** for these fields:

**AGREEMENT HAS TWO KEY EXHIBITS - READ BOTH!**

### EXHIBIT A - PROJECT SCOPE TABLE
Look for a TABLE in Exhibit A that lists all categories. This table typically has columns like:
| Category | Baseline/Addressable Spend | Savings Low | Savings High |

From this table, extract:
- `initial_categories_count`: COUNT the rows in this table (number of categories)
- `addressable_spend`: SUM of the baseline/addressable spend column OR look for "Total" row
- `savings_estimate_low`: SUM of "Savings Low" column OR look for total row
- `savings_estimate_high`: SUM of "Savings High" column OR look for total row

**The categories listed in Exhibit A are the INITIAL categories in scope!**

### EXHIBIT B - PROJECT FEES

**⚠️ CRITICAL: Each project has EXACTLY ONE fee type. Determine which type applies.**

There are THREE fee types. Read Exhibit B and determine which ONE applies:

| Fee Type | Also Called | What to Look For | Fields to Extract |
|----------|-------------|------------------|-------------------|
| **fixed** | "Project Fee" | ONLY a flat dollar amount: "$X fixed fee", "Project Fees: $X" | `fee_amount` only |
| **contingent** | "Success Fee" | ONLY a percentage: "X% of savings", "contingent on savings" | `fee_contingent_percentage` only |
| **hybrid** | "Blended" | BOTH a fixed amount AND a percentage | `fee_amount` + `fee_contingent_percentage` + `fee_hybrid_threshold` |

**FEE TYPE DETECTION LOGIC:**
```
IF Exhibit B contains ONLY a flat dollar amount (e.g., "$190,000 fixed fee"):
    → fee_type = "fixed"
    → Extract fee_amount = 190000.0
    
ELSE IF Exhibit B contains ONLY a percentage (e.g., "25% of implemented savings"):
    → fee_type = "contingent"  
    → Extract fee_contingent_percentage = 25.0
    
ELSE IF Exhibit B contains BOTH a fixed amount AND a percentage:
    → fee_type = "hybrid"
    → Extract fee_amount (the FIXED portion, e.g., "$100,000 base fee" → 100000.0)
    → Extract fee_contingent_percentage (the VARIABLE portion, e.g., "plus 20% of savings" → 20.0)
    → Extract fee_hybrid_threshold (when variable kicks in, if stated)
```

**HYBRID FEE EXAMPLE:**
Exhibit B says: "Project Fee: $100,000 fixed fee plus 20% of implemented savings above $500,000"
Extract:
- fee_type = "hybrid"
- fee_amount = 100000.0 (the fixed portion)
- fee_contingent_percentage = 20.0 (the variable portion)
- fee_hybrid_threshold = 500000.0 (when variable kicks in)

**⚠️ BEWARE OF EXAMPLE CALCULATIONS! ⚠️**
The Agreement may contain example calculations like:
- "if savings are $600,000 then... $300,000 ($600,000/2)"
These are EXAMPLES to explain formulas, NOT actual fees!
The actual fee is the one explicitly labeled "fixed fee", "Project Fees", or "% of savings".

**⚠️ "Minimum Savings Guarantee" is NOT the fee!** It's a guarantee threshold, not a fee amount.

### Field Mapping Summary:
- `fee_type`: EXACTLY ONE of "fixed", "contingent", or "hybrid"
- `fee_amount`: The FIXED FEE portion (only for fixed or hybrid)
- `fee_contingent_percentage`: The percentage (only for contingent or hybrid)
- `fee_hybrid_threshold`: When variable portion kicks in (only for hybrid, if stated)
- `initial_categories_count`: COUNT of categories in Exhibit A table
- `addressable_spend`: TOTAL from Exhibit A table
- `savings_estimate_low`: LOW end from Exhibit A table
- `savings_estimate_high`: HIGH end from Exhibit A table

**IGNORE other documents for these fields!** The Agreement is the contractual source of truth.

**How to set source correctly:**
- `source_file`: MUST contain "Agreement" in the path
- `confidence`: "high" if from Agreement
- If you CANNOT find it in Agreement documents:
  - Still try to find it in Assessment/Proposal as fallback
  - Set `confidence`: "low"
  - Add to notes: "⚠️ WARNING: Not found in Agreement - fallback from [filename]"

### 4. SAVINGS: PROJECTED vs ACTUAL
Distinguish between:
- `savings_estimate_low` / `savings_estimate_high`: From Agreement ONLY (what was projected)
- `impact.financials.annual_savings`: From Case Study or Close-out (what was actually achieved)

### 5. EXTRACT ALL CATEGORIES (CRITICAL!)

**STEP 1: Start with Agreement Exhibit A**
The Agreement's Exhibit A table lists ALL initial categories in scope. 
This is your baseline - you MUST extract data for EACH category listed there.

**STEP 2: Check for Additional Categories**
Some categories may have been added after the Agreement was signed.
Look for additional categories in:
- Categories/ folder structure
- Wave 2/Categories/ folder (if exists)
- Project Updates that mention new categories

**STEP 3: For EACH Category, Extract:**
- `category_label`: Exact name (e.g., "Medical Supplies", "Telecom - Circuits")
- `status`: "implemented", "negotiated", "identified", "not_pursued", "in_progress", or "unknown"
- `baseline_spend`: With amount, confidence, and source_file
- `savings_annual_run_rate`: With amount, confidence, and source_file
- `savings_percentage`: Calculated or stated percentage
- `levers`: List of tactics used (rate_reduction, GPO, consolidation, RFP, incumbent_negotiation)
- `vendors_before`: Who they bought from BEFORE
- `vendors_after`: Who they buy from AFTER (with context like "GPO contract", "renegotiated")

**STEP 4: For Categories with Sparse Data**
Even if you only have partial information:
- Still include the category
- Set `status: "unknown"` if unclear
- Set `confidence: "low"` on any values you're uncertain about
- Add notes explaining what information is missing

**⚠️ CRITICAL: DO NOT AGGREGATE CATEGORIES ⚠️**

DO NOT create a single "Multiple Categories" or "Aggregate" entry!
Each category MUST be a SEPARATE entry in the categories array.

**MINIMUM REQUIREMENT:**
- You MUST extract INDIVIDUAL categories, NOT aggregate them
- If you see Medical Supplies, Office Supplies, Courier, etc. → create SEPARATE entries for each
- Most Treya projects have 7-15 individual categories

**WHERE TO FIND CATEGORY DATA:**
1. Category Excel files (e.g., "APDerm - Courier Services RFP - Savings Analysis.xlsx") - HIGH VALUE
2. Project Updates with category tables - HIGH VALUE  
3. Assessment documents with category breakdowns - MEDIUM VALUE
4. Final Case Study (usually only has aggregate totals) - LOW VALUE for individual categories

**NEVER do this:**
```json
{{
  "category_label": "Multiple Indirect Categories",
  "baseline_spend": {{"amount": 6300000}}
}}
```

**ALWAYS do this:**
```json
[
  {{"category_label": "Medical Supplies", "baseline_spend": {{"amount": 1817711}}}},
  {{"category_label": "Courier Services", "baseline_spend": {{"amount": 432024}}}},
  {{"category_label": "Office Supplies", "baseline_spend": {{"amount": 174287}}}},
  ...
]
```

### 6. VENDOR INFORMATION (Pre/Post Sourcing)
For each category, extract:
- `vendors_before`: Who they were buying from BEFORE Treya's work
  - Example: ["Henry Schein", "Multiple local suppliers", "Various distributors"]
- `vendors_after`: Who they ended up with AFTER implementation, with context
  - Example: ["McKesson (GPO contract)", "Henry Schein (renegotiated terms)", "Incumbent - 15% rate reduction"]

### 7. PROJECT UPDATES OVERRIDE (CRITICAL!)
When extracting category data, if the FINAL project update (close-out, latest dated update) has different numbers than other documents:
- **ALWAYS use the final project update values** - they are the most accurate
- Set `confidence: "high"` for data from final project updates
- In notes, mention if there was a discrepancy: "Updated from final close-out (previously X in earlier docs)"

### 8. FORMAT RULES - CRITICAL

⚠️ **MONEY AMOUNTS - VERY IMPORTANT** ⚠️
- ALL monetary values MUST be in FULL DOLLAR amounts (not millions, not thousands)
- CORRECT: 1817711.0 for $1,817,711
- CORRECT: 485087.0 for $485,087
- CORRECT: 50000000.0 for $50 million
- WRONG: 1.817711 (this looks like $1.82, not $1.8M)
- WRONG: 0.485 (this looks like 48 cents, not $485K)
- WRONG: 50.0 (this looks like $50, not $50M)

If you see "$1.8M" in a document, output: 1800000.0
If you see "$485K" in a document, output: 485000.0
If you see "$190,000", output: 190000.0

- **Dates**: Use ISO format (YYYY-MM-DD)
- **Percentages**: As decimal 0-100 (e.g., 25.0 for 25%)

### 9. EXTRACTION NOTES
Add to `extraction_notes` array:
- Any gaps in information
- Conflicting data between sources
- Fields you couldn't populate and why
- Assumptions you had to make

## Output Schema (JSON):
```json
{schema_json}
```

## Extracted Document Contents:
---
{file_contents}
---

## Your Response:
Return a single JSON object matching the CaseStudy schema.
- Include ALL categories found
- Include source_file and confidence on EVERY monetary claim
- Include extraction_notes listing any gaps or uncertainties
"""


# ============================================================================
# Convenience function for quick access
# ============================================================================
def get_default_system_prompt() -> str:
    """Get the default system prompt with all phases."""
    builder = ContextBuilder()
    return builder.build_full_context()
