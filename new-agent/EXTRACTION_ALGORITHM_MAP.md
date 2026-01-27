# Case Study Extraction Algorithm - Field-to-Source Mapping

## How the Current Algorithm Works (High Level)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PASS 1: FILE SELECTION                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ INPUT:  Directory tree (text representation)                                 │
│ OUTPUT: JSON with:                                                           │
│         - categories_found: ["Medical Supplies", "Telecom", ...]            │
│         - selected_files: ["Agreement/...", "Categories/Medical/..."]       │
│                                                                              │
│ HOW CATEGORIES ARE DISCOVERED:                                               │
│   1. LLM reads folder names under Categories/ and Wave 2/Categories/        │
│   2. LLM returns list of category names it found                            │
│   3. LLM picks 1 file per category                                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         FILE CONTENT EXTRACTION                              │
├─────────────────────────────────────────────────────────────────────────────┤
│ For each selected file:                                                      │
│   PDF  → PyMuPDF → Text by page                                             │
│   PPTX → python-pptx → Slides + tables + notes                              │
│   XLSX → openpyxl → First 100 rows × 20 cols per sheet                      │
│   DOCX → python-docx → Paragraphs + tables                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PASS 2: SCHEMA EXTRACTION                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ INPUT:  All extracted file contents concatenated                             │
│ OUTPUT: JSON matching CaseStudy Pydantic schema                              │
│                                                                              │
│ LLM reads through all content and fills each field based on prompt rules    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 1️⃣ PROJECT SCOPE, TIMING, AND FEES

### Fee Types (ALWAYS from Agreement/Exhibit B)

**⚠️ IMPORTANT: Each project has EXACTLY ONE fee type. The algorithm must determine which type applies.**

There are **three fee structure types**. All are found in **Agreement → Exhibit B**:

| Fee Type | Also Called | What to Look For in Exhibit B | Fields to Extract |
|----------|-------------|-------------------------------|-------------------|
| **Fixed** | "Project Fee" | "$X fixed fee", "Project Fees: $X", flat dollar amount | `fee_amount` only |
| **Contingent** | "Success Fee", "Savings Share" | "X% of savings", "contingent on savings achieved" | `fee_contingent_percentage` only |
| **Hybrid** | "Blended" | Both a fixed component AND a percentage component | `fee_amount` (fixed portion) + `fee_contingent_percentage` (variable portion) + `fee_hybrid_threshold` (optional) |

### Fee Type Detection Logic

```
Read Agreement/Exhibit B:

IF contains ONLY a flat dollar amount (e.g., "$190,000 fixed fee", "Project Fees: $X"):
    → fee_type = "fixed"
    → Extract fee_amount
    
ELSE IF contains ONLY a percentage of savings (e.g., "25% of implemented savings"):
    → fee_type = "contingent"  
    → Extract fee_contingent_percentage
    
ELSE IF contains BOTH a fixed amount AND a percentage:
    → fee_type = "hybrid"
    → Extract fee_amount (the FIXED portion - e.g., "$100,000 base fee")
    → Extract fee_contingent_percentage (the VARIABLE portion - e.g., "plus 20% of savings")
    → Extract fee_hybrid_threshold (optional - when variable portion kicks in, if stated)
```

### Hybrid Fee Example
```
Exhibit B says: "Project Fee: $100,000 fixed fee plus 20% of implemented savings above $500,000"

Extract:
  fee_type = "hybrid"
  fee_amount = 100000.0          ← The fixed portion
  fee_contingent_percentage = 20  ← The variable portion (%)
  fee_hybrid_threshold = 500000.0 ← When variable kicks in (if stated)
```

### Fee Fields Mapping

| Field | Schema Path | Source Document | How It's Found | Current Logic | Issues/Notes |
|-------|-------------|-----------------|----------------|---------------|--------------|
| `fee_type` | `project_scope.fee_type` | **Agreement/Exhibit B ONLY** | Determine which of the 3 types based on language | Prompt tells LLM to find Exhibit B section | Must be: "fixed", "contingent", or "hybrid" |
| `fee_amount` | `project_scope.fee_amount` | **Agreement/Exhibit B ONLY** | For Fixed/Hybrid: Look for "$X fixed fee" or "Project Fees: $X" | ⚠️ Must be from Agreement - prompt warns about example calculations | Sometimes pulls from wrong doc |
| `fee_hybrid_threshold` | `project_scope.fee_hybrid_threshold` | **Agreement/Exhibit B ONLY** | For Hybrid: The savings threshold where contingent kicks in | Prompt instruction | Only for hybrid fee type |
| `fee_contingent_percentage` | `project_scope.fee_contingent_percentage` | **Agreement/Exhibit B ONLY** | For Contingent/Hybrid: Look for "X% of savings" | Prompt instruction | Percentage 0-100 |
| `fee_notes` | `project_scope.fee_notes` | **Agreement/Exhibit B ONLY** | Additional fee details (payment schedule, guarantees) | LLM extraction | |

### Other Scope Fields

| Field | Schema Path | Source Document | How It's Found | Current Logic | Issues/Notes |
|-------|-------------|-----------------|----------------|---------------|--------------|
| `engagement_type` | `project_scope.engagement_type` | Assessment, Agreement | LLM infers from context | Pass 2 prompt asks LLM to describe engagement type | Often generic |
| `initial_categories_count` | `project_scope.initial_categories_count` | **Agreement/Exhibit A** | COUNT rows in category table | Prompt tells LLM to count Exhibit A table rows | Often NULL - table hard to parse |
| `addressable_spend` | `project_scope.addressable_spend` | **Agreement/Exhibit A** | SUM of baseline column or "Total" row | ⚠️ Sometimes pulled from Case Study instead | Priority issue |
| `savings_estimate_low` | `project_scope.savings_estimate_low` | **Agreement/Exhibit A** | SUM of "Savings Low" column | Prompt instruction | |
| `savings_estimate_high` | `project_scope.savings_estimate_high` | **Agreement/Exhibit A** | SUM of "Savings High" column | Prompt instruction | |
| `cogs_categories_count` | `project_scope.cogs_categories_count` | Agreement or Assessment | LLM extracts if mentioned | Optional | Often missing |
| `cogs_categories_percentage` | `project_scope.cogs_categories_percentage` | Agreement or Assessment | COGS as % of total | Calculation | Often missing |
| `cogs_spend_addressed` | `project_scope.cogs_spend_addressed` | Agreement or Assessment | COGS spend total | LLM extraction | Often missing |
| `cogs_categories_list` | `project_scope.cogs_categories_list` | Agreement or Assessment | List of COGS categories | LLM extraction | Often missing |
| `operational_objectives` | `project_scope.operational_objectives` | Assessment, Proposal | LLM extracts non-savings goals | Pass 2 prompt | |
| `start_date` | `project_scope.start_date` | Agreement signature date | From dates in filenames/content | Often approximate | |
| `end_date` | `project_scope.end_date` | Close-out date | From dates in filenames/content | Often approximate | |
| `source_folder_url` | `project_scope.source_folder_url` | Not extracted | N/A | Not implemented | |

---

## 2️⃣ CLIENT CONTEXT

| Field | Schema Path | Source Document | How It's Found | Current Logic | Issues/Notes |
|-------|-------------|-----------------|----------------|---------------|--------------|
| `client_name` | `client.client_name` | Folder name, any document | Project folder name is used as hint | Pass 2 prompt includes `client_name_hint` | Usually accurate |
| `industry_primary` | `client.industry_primary` | Assessment, Case Study | LLM infers from content | Pass 2 general extraction | |
| `industry_secondary` | `client.industry_secondary` | Assessment, Case Study | LLM infers | Optional | |
| `business_model` | `client.business_model` | Assessment, Case Study | "manufacturer", "multi-site", etc. | LLM inference | |
| `sponsor_pe_firm` | `client.sponsor_pe_firm` | Assessment, Case Study, Web | PE sponsor name | LLM looks for "backed by", "portfolio of" | |
| `client_history` | `client.client_history` | Assessment, Case Study | Background on client | LLM extraction | |
| `revenue` | `client.size_metrics.revenue` | **Web Search** | OpenAI web_search tool | Step 3.5 does web search for "{client} company revenue" | Unreliable |
| `ebitda` | `client.size_metrics.ebitda` | Documents or Web | If mentioned | Often not found | |
| `locations_count` | `client.size_metrics.locations_count` | Assessment, Case Study, Web | "X locations", "X sites" | LLM extraction + web search | |
| `locations_source` | `client.size_metrics.locations_source` | (derived) | File where found | Tracked for sourcing | |
| `locations_confidence` | `client.size_metrics.locations_confidence` | (derived) | high/medium/low | LLM assigns | |
| `employees_count` | `client.size_metrics.employees_count` | Web Search | Employee count | Web search fallback | |

---

## 3️⃣ ENGAGEMENT BACKGROUND

| Field | Schema Path | Source Document | How It's Found | Current Logic | Issues/Notes |
|-------|-------------|-----------------|----------------|---------------|--------------|
| `objective` | `engagement_background.objective` | Assessment, Case Study | "Why" of the engagement | LLM summarizes | |
| `scope_summary` | `engagement_background.scope_summary` | Assessment, Agreement | What's in/out of scope | LLM summarizes | |
| `constraints_challenges` | `engagement_background.constraints_challenges` | Assessment, Case Study, Updates | Challenges faced | LLM extracts as array | |
| `operating_model` | `engagement_background.procurement_environment.operating_model` | Assessment | "centralized", "decentralized" | LLM classifies into enum | |
| `maturity` | `engagement_background.procurement_environment.maturity` | Assessment | Low/medium/high | LLM classifies | |
| `data_availability` | `engagement_background.procurement_environment.data_availability` | Assessment | Data quality notes | LLM extracts | |
| `data_quality_notes` | `engagement_background.procurement_environment.data_quality_notes` | Assessment | Additional notes | LLM extracts | |
| `source_file` | `engagement_background.procurement_environment.source_file` | (derived) | File where found | Tracked for sourcing | |
| `confidence` | `engagement_background.procurement_environment.confidence` | (derived) | high/medium/low | LLM assigns | |

---



## 5️⃣ CATEGORIES (Array) - **THE KEY SECTION**

### How Categories Are Currently Discovered (Pass 1)

| Step | What Happens | Source | Issues |
|------|--------------|--------|--------|
| 1 | LLM reads directory tree text | Directory scan | Only sees folder structure |
| 2 | Looks for folders under `Categories/` | Folder names | May miss categories without folders |
| 3 | Looks for folders under `Wave 2/Categories/` | Folder names | Same issue |
| 4 | Returns `categories_found` array | LLM output | Based only on folder names |
| 5 | Picks 1 file per category | LLM selection | May not pick best file |

### Category Fields Mapping

| Field | Schema Path | Primary Source | Secondary Source | How Found | Issues/Notes |
|-------|-------------|----------------|------------------|-----------|--------------|
| `category_label` | `categories[].category_label` | Folder name, Exhibit A table | — | Direct from folder or table | Required |
| `category_l1` | `categories[].category_l1` | — | — | L1 taxonomy | Optional, rarely used |
| `category_l2` | `categories[].category_l2` | — | — | L2 taxonomy | Optional, rarely used |
| `category_l3` | `categories[].category_l3` | — | — | L3 taxonomy | Optional, rarely used |
| `start_date` | `categories[].start_date` | Category files | — | Date work started | Often missing |
| `end_date` | `categories[].end_date` | Category files | — | Date work ended | Often missing |
| `status` | `categories[].status` | Final Update, Close-out | Category file | "implemented", "in progress", etc. | Enum values |
| `vendors_before` | `categories[].vendors_before` | Category RFP files | — | Incumbent vendors | Array of strings |
| `vendors_after` | `categories[].vendors_after` | Category files, Updates | — | Winning vendors with context | Array of strings |
| `levers` | `categories[].levers` | Category files, Updates | — | "GPO", "RFP", "consolidation", etc. | Array of strings |
| `constraints.supplier_constraints` | `categories[].constraints.supplier_constraints` | Category files | — | Must-use, diversity, preferred | Optional |
| `constraints.operational_constraints` | `categories[].constraints.operational_constraints` | Category files | — | No downtime, spec lock, clinical | Optional |
| `constraints.contractual_constraints` | `categories[].constraints.contractual_constraints` | Category files | — | Existing terms, renewals | Optional |
| `constraints.implementation_constraints` | `categories[].constraints.implementation_constraints` | Category files | — | Labor, seasonality, regulatory | Optional |
| `baseline_spend` | `categories[].baseline_spend` | **Category Excel file** | Agreement Exhibit A, Final Update | "baseline", "historical spend" | ClaimMoney with source |
| `savings_annual_run_rate` | `categories[].savings_annual_run_rate` | **Final Update / Close-out** | Category Excel | "savings", "annual", "run rate" | ClaimMoney with source |
| `savings_one_time` | `categories[].savings_one_time` | Category files, Updates | — | One-time savings | ClaimMoney |
| `savings_percentage` | `categories[].savings_percentage` | Calculated or stated | — | savings ÷ baseline | Float 0-100 |
| `notes` | `categories[].notes` | Category files | — | Additional context | String |
| `evidence` | `categories[].evidence[]` | File paths | — | Where data was found | Array of Evidence |

### Best Sources for Category Data (Priority Order)

| Priority | Source | What It Contains | Quality |
|----------|--------|------------------|---------|
| 1 | **F## 4️⃣ IMPACT

| Field | Schema Path | Source Document | How It's Found | Current Logic | Issues/Notes |
|-------|-------------|-----------------|----------------|---------------|--------------|
| `headline` | `impact.summary.headline` | Case Study | Marketing headline | LLM creates or extracts | |
| `narrative` | `impact.summary.narrative` | Case Study | 2-4 sentence summary | LLM writes | Required field |
| `annual_savings` | `impact.financials.annual_savings` | **Case Study, Final Project Update** | Total savings achieved | ⚠️ This is ACTUAL savings (vs. estimates in Agreement) | Key metric |
| `one_time_savings` | `impact.financials.one_time_savings` | Case Study, Final Update | One-time savings | LLM extraction | |
| `value_realized_in_days` | `impact.time_to_value.value_realized_in_days` | Case Study, Updates | Days to value | Often not found | |
| `time_to_value_notes` | `impact.time_to_value.notes` | Case Study, Updates | Additional notes | LLM extraction | |
| `operational_improvements` | `impact.operational_improvements` | Case Study | Process improvements | LLM extraction | |
| `proof_points` | `impact.proof_points[]` | Case Study, Updates | Specific wins | LLM extracts with evidence | Array of ProofPoint |
| `proof_points[].statement` | `impact.proof_points[].statement` | Case Study, Updates | The proof point text | LLM extraction | Required |
| `proof_points[].category` | `impact.proof_points[].category` | Case Study, Updates | Related category | LLM links | Optional |
| `proof_points[].evidence` | `impact.proof_points[].evidence[]` | Case Study, Updates | Source files, quotes | LLM extraction | Optional |

---inal Project Update / Close-out PPTX** | ALL categories in one table with final numbers | ⭐⭐⭐⭐⭐ |
| 2 | **Agreement Exhibit A** | Initial category list, baseline spend, estimates | ⭐⭐⭐⭐ |
| 3 | **Case Study** | Aggregate totals, narrative | ⭐⭐⭐ |
| 4 | **Category-specific Excel files** | Detailed analysis for ONE category | ⭐⭐⭐ |
| 5 | **Category-specific PPTX files** | Summary for ONE category | ⭐⭐ |

---

## 6️⃣ CASE STUDY PACKAGING

| Field | Schema Path | Source Document | How It's Found | Current Logic | Issues/Notes |
|-------|-------------|-----------------|----------------|---------------|--------------|
| `case_study_ready` | `case_study_packaging.case_study_ready` | LLM judgment | Does it have enough info? | LLM decides | Boolean |
| `headline` | `case_study_packaging.headline` | Case Study or LLM creates | Marketing headline | LLM extraction/generation | |
| `client_problem_statement` | `case_study_packaging.client_problem_statement` | Case Study | Problem faced | LLM extraction | |
| `approach_summary` | `case_study_packaging.approach_summary` | Case Study | 3-5 bullets | LLM extraction | Array |
| `top_levers` | `case_study_packaging.top_levers` | Aggregated from categories | Ranked list | LLM aggregates | Array |
| `value_delivered_blurb` | `case_study_packaging.value_delivered_blurb` | Case Study | Value narrative | LLM extraction | |
| `where_we_were_unique` | `case_study_packaging.where_we_were_unique` | Case Study | Differentiators | LLM extraction | Array |

---

## Supporting Types

### ClaimMoney Structure
```json
{
  "amount": 1234567.0,      // Full dollars (not millions/thousands)
  "currency": "USD",
  "confidence": "high",     // high | medium | low
  "source_file": "Agreement/Signed Agreement/...",
  "notes": "Optional context"
}
```

### ClaimNumber Structure
```json
{
  "value": 90.0,
  "unit": "days",
  "confidence": "medium",
  "source_file": "...",
  "notes": "..."
}
```

### Evidence Structure
```json
{
  "source_file": "relative/path/to/file.pdf",
  "page_or_slide": "5",
  "quote": "Relevant quote from document",
  "date_extracted": "2026-01-21"
}
```

---

## Configuration Parameters

| Parameter | Location | Current Value | Description |
|-----------|----------|---------------|-------------|
| `MODEL` | `src/config.py` | `"o3"` | LLM model to use |
| `REASONING_EFFORT` | `src/config.py` | `"medium"` | For o3: low/medium/high |
| `MAX_TOKENS` | `src/config.py` | `16000` | Max output tokens |
| `FILE_SELECTION_COUNT` | `src/prompts/context.py` | `30` | Files to select in Pass 1 |
| Excel max rows | `src/extractors/xlsx.py` | `100` | Rows extracted per sheet |
| Excel max cols | `src/extractors/xlsx.py` | `20` | Columns extracted per sheet |
| Agreement file max_chars | `src/console/app.py` | `40000` | Chars for agreement files |
| Other file max_chars | `src/console/app.py` | `20000` | Chars for other files |

---

## Known Issues & Improvement Opportunities

### Issue 1: Category Discovery Relies on Folder Names
- **Current:** LLM only sees folder names in directory tree
- **Problem:** Some categories exist in Agreement Exhibit A but NOT as separate folders
- **Fix:** Also extract categories from Agreement Exhibit A table

### Issue 2: Fee/Scope Data Source Priority
- **Current:** Sometimes pulls from Case Study instead of Agreement
- **Problem:** Case Study may have rounded/different numbers
- **Fix:** Stricter prompt instructions, validate source_file contains "Agreement"

### Issue 3: Excel Extraction Limits
- **Current:** Only first 100 rows × 20 columns
- **Problem:** Key data may be in row 150 or column 25
- **Fix:** Increase limits or add smart sheet detection

### Issue 4: Final Update Not Prioritized
- **Current:** Category files selected individually
- **Problem:** Final Update often has ALL categories in one comprehensive table
- **Fix:** Always select Final Update, use category files only for gaps

### Issue 5: PDF Table Extraction
- **Current:** PyMuPDF extracts text, tables become messy
- **Problem:** Agreement Exhibit A table hard to parse
- **Fix:** Consider table-aware PDF extraction (pdfplumber, camelot)

---

## Recommended Algorithm Changes

### Option A: Two-Source Category Discovery
```
1. Get categories from folder names (current)
2. ALSO get categories from Agreement Exhibit A table
3. ALSO get categories from Final Update table
4. Merge and deduplicate
```

### Option B: Change File Selection Priority
```
Current:
1. Agreement (3-5 files)
2. Case Study (2-3 files)
3. Final Update (2-3 files)
4. 1 file per category

Proposed:
1. Agreement - specifically Exhibit A and B sections (1-2 files)
2. Final Project Update / Close-out (1 file) ← MOST VALUABLE
3. Case Study (1-2 files)
4. Only for categories NOT in Final Update: 1 file each
```

### Option C: Multi-Pass Extraction
```
Pass 1: File selection (current)
Pass 2: Extract Agreement data (fees, scope, category list)
Pass 3: Extract Final Update data (category results)
Pass 4: Fill gaps from individual category files
Pass 5: Merge and validate
```
