"""
Template-Based PowerPoint Generator for /powerpoint2 command.

Uses "LLM Case Study Format.pptx" as an exact template and only replaces text.
Preserves all styling, positioning, and formatting from the template.

Template Structure:
- Slide 1: "Unlock Hidden Value" - Leave as is
- Slide 2: Client name title + "IMPACT CASE STUDY"
- Slide 3: The Challenge - Client info, challenge text, approach bullets
- Slide 4: Key Levers - Levers, value metrics, differentiators
- Slide 5: Selected Category Outcomes - Table with top 7 categories + bar chart
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from pptx import Presentation
from pptx.util import Inches


# Template file name (in new-agent directory)
TEMPLATE_FILENAME = "LLM Case Study Format.pptx"


class TemplatePPTXGenerator:
    """
    Generator that modifies text in an existing template.
    
    Preserves all styling and only replaces text content.
    """
    
    def __init__(self, template_path: Path):
        """Initialize with template path."""
        self.template_path = template_path
        
        if not template_path.exists():
            raise FileNotFoundError(f"Template not found: {template_path}")
    
    def generate(
        self,
        client_context: Dict[str, Any],
        case_study: Dict[str, Any],
        impact: Dict[str, Any],
        categories_data: Optional[Dict[str, Any]],
        output_path: Path,
        pe_description: Optional[str] = None,
        summarized_content: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """
        Generate PowerPoint by replacing text in template.
        
        Args:
            client_context: Client context data
            case_study: Case study packaging data
            impact: Impact data
            categories_data: Categories data with list of category outcomes
            output_path: Where to save the output
            pe_description: Optional PE firm description from web search
            summarized_content: Optional LLM-summarized content with:
                - challenge: summarized challenge text
                - approach: summarized approach bullets
                - value_metrics: list of {value, description} dicts
            
        Returns:
            Path to the generated file
        """
        # Load the template
        prs = Presentation(str(self.template_path))
        
        # Extract data for each slide
        client = client_context.get("client", client_context)
        packaging = case_study.get("case_study_packaging", case_study)
        
        # Get client info
        client_name = client.get("client_name", "Client")
        industry = client.get("industry_primary", "")
        pe_sponsor = client.get("sponsor_pe_firm", "")
        
        # =========================================================================
        # SLIDE 2: Anonymized Title
        # =========================================================================
        # Prefer LLM-generated title, fall back to client name
        if summarized_content and summarized_content.get("title"):
            slide_2_title = summarized_content["title"]
            print(f"DEBUG: Using LLM-generated title: {slide_2_title}")
        else:
            slide_2_title = client_name
            print(f"DEBUG: Using client name as title: {slide_2_title}")
        
        # =========================================================================
        # SLIDE 3: Client Description, Challenge, Approach
        # =========================================================================
        # Client description: prefer LLM-generated, fall back to rule-based
        if summarized_content and summarized_content.get("client_description"):
            client_description = summarized_content["client_description"]
            print(f"DEBUG: Using LLM-generated client description: {client_description}")
        else:
            client_description = self._build_client_description(client)
            print(f"DEBUG: Using rule-based client description: {client_description}")
        
        # PE relationship: prefer passed web search result, fall back to rule-based
        if pe_description:
            # Use the web search result that was passed in
            print(f"DEBUG: Using web search PE description: {pe_description}")
        else:
            # Fall back to rule-based generation
            pe_description = self._build_pe_description(industry, pe_sponsor)
            print(f"DEBUG: Using rule-based PE description: {pe_description}")
        
        # Challenge text: prefer LLM-generated, fall back to raw
        if summarized_content and summarized_content.get("challenge"):
            challenge_text = summarized_content["challenge"]
        else:
            challenge_text = (
                packaging.get("client_problem_anonymized") or 
                packaging.get("client_problem_statement", "")
            )
        
        # Approach: prefer LLM-generated, fall back to raw
        if summarized_content and summarized_content.get("approach"):
            approach_bullets = summarized_content["approach"]
        else:
            approach_bullets = packaging.get("approach_summary", [])
        
        # =========================================================================
        # SLIDE 4: Top Levers, Value Metrics, Differentiators
        # =========================================================================
        # Value metrics: ALWAYS calculated for consistency
        financials = impact.get("financials", {})
        value_blurb = packaging.get("value_delivered_blurb", "")
        impact_metrics = self._parse_value_metrics(value_blurb, financials, categories_data)
        print(f"DEBUG - Calculated impact_metrics: {impact_metrics}")
        
        # Top levers: prefer LLM-generated, fall back to raw
        if summarized_content and summarized_content.get("top_levers"):
            top_levers = summarized_content["top_levers"]
            print(f"DEBUG - Using LLM-generated top_levers: {top_levers}")
        else:
            top_levers = (
                packaging.get("top_levers") or 
                case_study.get("top_levers") or 
                []
            )
            print(f"DEBUG - Using raw top_levers from database")
        
        # Differentiators: prefer LLM-generated, fall back to raw
        if summarized_content and summarized_content.get("differentiators"):
            differentiators = summarized_content["differentiators"]
            print(f"DEBUG - Using LLM-generated differentiators: {differentiators}")
        else:
            differentiators = (
                packaging.get("where_we_were_unique") or 
                case_study.get("where_we_were_unique") or 
                []
            )
            print(f"DEBUG - Using raw differentiators from database")
        
        # Debug summary
        print(f"DEBUG - top_levers ({len(top_levers)}): {top_levers[:2] if top_levers else 'EMPTY'}")
        print(f"DEBUG - differentiators ({len(differentiators)}): {differentiators[:2] if differentiators else 'EMPTY'}")
        
        # Get categories (top 7 by savings)
        categories = self._get_top_categories(categories_data, max_count=7)
        
        # Modify each slide
        slides = list(prs.slides)
        
        # Slide 1: Leave as is (Unlock Hidden Value)
        
        # Slide 2: Replace title with anonymized title (not client name)
        if len(slides) >= 2:
            self._update_slide_2(slides[1], slide_2_title)
        
        # Slide 3: Challenge slide
        if len(slides) >= 3:
            self._update_slide_3(
                slides[2], 
                client_description, 
                pe_description,
                challenge_text,
                approach_bullets
            )
        
        # Slide 4: Key Levers / Value Delivered
        if len(slides) >= 4:
            self._update_slide_4(
                slides[3],
                top_levers,
                impact_metrics,
                differentiators
            )
        
        # Slide 5: Category table + bar chart
        if len(slides) >= 5:
            self._update_slide_5(slides[4], categories, prs)
        
        # Save to output path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        prs.save(str(output_path))
        
        return output_path
    
    def _preserve_acronyms(self, text: str) -> str:
        """
        Restore common acronyms that get mangled by title() case conversion.
        
        Example: "Hvac" -> "HVAC", "Saas" -> "SaaS"
        """
        # Common acronyms and their correct forms
        acronym_fixes = {
            r'\bHvac\b': 'HVAC',
            r'\bIt\b': 'IT',
            r'\bHr\b': 'HR',
            r'\bPe\b': 'PE',
            r'\bB2B\b': 'B2B',
            r'\bB2C\b': 'B2C',
            r'\bSaas\b': 'SaaS',
            r'\bIot\b': 'IoT',
            r'\bAi\b': 'AI',
            r'\bErp\b': 'ERP',
            r'\bCrm\b': 'CRM',
            r'\bLlc\b': 'LLC',
            r'\bInc\b': 'Inc.',
            r'\bUsa\b': 'USA',
            r'\bUs\b': 'US',
            r'\bUk\b': 'UK',
        }
        
        result = text
        for pattern, replacement in acronym_fixes.items():
            result = re.sub(pattern, replacement, result)
        
        return result
    
    def _build_client_description(self, client: Dict[str, Any]) -> str:
        """
        Build a rich, anonymized client description.
        
        Format: "A Leading Provider of {industry} {business_model}"
        Example: "A Leading Provider of Healthcare Services"
        
        Character limit: ~70 chars to prevent overflow and leave spacing.
        Does NOT include revenue or employee count (unreliable).
        """
        MAX_CHARS = 70
        
        industry = client.get("industry_primary", "")
        business_model = client.get("business_model", "")
        
        # Build natural sentence: "A Leading Provider of {industry} {service_type}"
        parts = ["A Leading Provider of"]
        
        # Add industry (apply title case then restore acronyms)
        if industry:
            titled_industry = self._preserve_acronyms(industry.title())
            parts.append(titled_industry)
        
        # Add business model as service type (natural phrasing)
        if business_model:
            model_lower = business_model.lower()
            if "multi-site" in model_lower or "multisite" in model_lower:
                parts.append("Services")
            elif "manufacturer" in model_lower or "manufacturing" in model_lower:
                parts.append("Products")
            elif "distributor" in model_lower or "distribution" in model_lower:
                parts.append("Distribution")
            elif "service" in model_lower:
                parts.append("Services")
            elif "e-commerce" in model_lower or "ecommerce" in model_lower:
                parts.append("E-Commerce")
            elif "retail" in model_lower:
                parts.append("Retail")
        
        # Build description
        description = " ".join(parts)
        
        # If no business model, ensure it still reads naturally
        if not business_model and industry:
            titled_industry = self._preserve_acronyms(industry.title())
            description = f"A Leading Provider of {titled_industry} Solutions"
        elif not industry and not business_model:
            description = "A Leading Industry Provider"
        
        # Final truncation if too long
        if len(description) > MAX_CHARS:
            description = description[:MAX_CHARS].rsplit(" ", 1)[0]
        
        return description
    
    def _build_pe_description(self, industry: str, pe_sponsor: str) -> str:
        """
        Build an anonymous but descriptive PE firm description.
        
        Format: "A Growth-Focused {industry} Private Equity Firm"
        Example: "A Growth-Focused Healthcare Private Equity Firm"
        """
        industry_lower = (industry or "").lower()
        
        # Determine industry focus
        if any(term in industry_lower for term in ["health", "medical", "clinical", "pharma", "biotech"]):
            industry_focus = "Healthcare"
        elif any(term in industry_lower for term in ["tech", "software", "saas", "digital"]):
            industry_focus = "Technology"
        elif any(term in industry_lower for term in ["manufactur", "industrial", "defense"]):
            industry_focus = "Industrials"
        elif any(term in industry_lower for term in ["retail", "consumer", "e-commerce"]):
            industry_focus = "Consumer"
        elif any(term in industry_lower for term in ["financial", "insurance", "bank"]):
            industry_focus = "Financial Services"
        elif any(term in industry_lower for term in ["service", "business"]):
            industry_focus = "Business Services"
        else:
            industry_focus = "Middle-Market"
        
        return f"A Growth-Focused {industry_focus} Private Equity Firm"
    
    def _parse_value_metrics(
        self,
        value_blurb: str,
        financials: Dict[str, Any],
        categories_data: Optional[Dict[str, Any]]
    ) -> List[Dict[str, str]]:
        """
        Calculate 3 value metrics for the Value Delivered section.
        
        Metrics:
        1. Contract Length Savings = 3x annual savings
        2. Estimated Value Created = 13x annual savings
        3. Most meaningful operational improvement (best judgment from data)
        
        Each metric has:
        - value: Big text (e.g., "$3.54M")
        - description: Smaller text underneath (e.g., "contract length savings")
        """
        metrics = []
        
        # Get annual savings amount - try multiple possible locations
        annual_amount = 0
        
        # Try: financials.total_annual_savings.amount (most common)
        total_annual = financials.get("total_annual_savings", {})
        if isinstance(total_annual, dict):
            annual_amount = total_annual.get("amount", 0) or 0
        
        # Fallback: financials.annual_savings.amount
        if not annual_amount:
            annual_savings = financials.get("annual_savings", {})
            if isinstance(annual_savings, dict):
                annual_amount = annual_savings.get("amount", 0) or 0
            else:
                annual_amount = annual_savings or 0
        
        # Fallback: sum from categories if still no amount
        if not annual_amount and categories_data:
            categories = categories_data.get("categories", [])
            for cat in categories:
                savings = cat.get("savings_annual_run_rate", {})
                if isinstance(savings, dict):
                    annual_amount += savings.get("amount", 0) or 0
                elif savings:
                    annual_amount += float(savings) if savings else 0
        
        print(f"DEBUG: Found annual_amount = {annual_amount}")
        
        # Metric 1: Contract Length Savings (3x annual savings)
        if annual_amount:
            contract_savings = annual_amount * 3
            metrics.append({
                "value": self._format_currency(contract_savings),
                "description": "Contract Length Savings"
            })
        else:
            metrics.append({"value": "", "description": "Contract Length Savings"})
        
        # Metric 2: Estimated Value Created (13x annual savings)
        if annual_amount:
            value_created = annual_amount * 13
            metrics.append({
                "value": self._format_currency(value_created),
                "description": "Estimated Value Created"
            })
        else:
            metrics.append({"value": "", "description": "Estimated Value Created"})
        
        # Metric 3: Most meaningful operational improvement
        # Priority: specific quantifiable improvement > category count > generic
        metric_3 = self._get_best_operational_improvement(categories_data, financials, value_blurb)
        metrics.append(metric_3)
        
        return metrics[:3]
    
    def _get_best_operational_improvement(
        self,
        categories_data: Optional[Dict[str, Any]],
        financials: Dict[str, Any],
        value_blurb: str
    ) -> Dict[str, str]:
        """
        Determine the most meaningful operational improvement metric.
        
        Priority order:
        1. Highest savings percentage category (shows biggest impact)
        2. Number of categories with significant savings (>10%)
        3. Total number of categories addressed
        4. Generic fallback
        """
        if not categories_data:
            return {"value": "", "description": ""}
        
        categories = categories_data.get("categories", [])
        if not categories:
            return {"value": "", "description": ""}
        
        # Option 1: Find category with highest savings percentage
        best_category = None
        best_pct = 0
        
        for cat in categories:
            pct_val = cat.get("savings_percentage", 0)
            if isinstance(pct_val, str):
                pct_val = float(pct_val.replace("%", "").replace(",", "")) if pct_val else 0
            pct_val = float(pct_val) if pct_val else 0
            
            if pct_val > best_pct:
                best_pct = pct_val
                best_category = cat
        
        # If we have a standout category with >15% savings, highlight it
        if best_pct >= 15 and best_category:
            category_name = best_category.get("category_label", "")
            # Shorten category name if too long
            if len(category_name) > 25:
                category_name = category_name[:22] + "..."
            return {
                "value": f"{best_pct:.0f}%",
                "description": f"{category_name} Savings"
            }
        
        # Option 2: Count categories with meaningful savings (>10%)
        significant_categories = sum(
            1 for cat in categories 
            if self._get_category_pct(cat) >= 10
        )
        
        if significant_categories >= 3:
            return {
                "value": f"{significant_categories}",
                "description": "High-Impact Categories"
            }
        
        # Option 3: Total categories addressed
        if len(categories) >= 3:
            return {
                "value": f"{len(categories)}",
                "description": "Categories Optimized"
            }
        
        # Fallback
        return {"value": "", "description": ""}
    
    def _get_category_pct(self, cat: Dict[str, Any]) -> float:
        """Extract savings percentage from a category."""
        pct_val = cat.get("savings_percentage", 0)
        if isinstance(pct_val, str):
            pct_val = float(pct_val.replace("%", "").replace(",", "")) if pct_val else 0
        return float(pct_val) if pct_val else 0
    
    def _get_top_categories(
        self, 
        categories_data: Optional[Dict[str, Any]], 
        max_count: int = 7
    ) -> List[Dict[str, Any]]:
        """Get top categories by savings amount."""
        if not categories_data:
            return []
        
        categories = categories_data.get("categories", [])
        if not categories:
            return []
        
        # Sort by savings amount (descending)
        def get_savings(cat: Dict[str, Any]) -> float:
            savings = cat.get("savings_annual_run_rate", {})
            if isinstance(savings, dict):
                return savings.get("amount", 0) or 0
            return savings or 0
        
        sorted_cats = sorted(categories, key=get_savings, reverse=True)
        return sorted_cats[:max_count]
    
    def _format_currency(self, amount: float) -> str:
        """Format amount as currency string."""
        if not amount:
            return ""
        if amount >= 1_000_000:
            return f"${amount/1_000_000:.1f}M"
        elif amount >= 1_000:
            return f"${amount/1_000:.0f}K"
        else:
            return f"${amount:,.0f}"
    
    def _replace_shape_text(self, shape, new_text: str) -> None:
        """Replace all text in a shape while preserving formatting."""
        if not hasattr(shape, "text_frame"):
            return
        
        tf = shape.text_frame
        if tf.paragraphs:
            first_para = tf.paragraphs[0]
            
            if first_para.runs:
                first_run = first_para.runs[0]
                first_run.text = new_text
                for run in first_para.runs[1:]:
                    run.text = ""
            else:
                first_para.text = new_text
            
            # Clear other paragraphs
            for para in tf.paragraphs[1:]:
                para.clear()
    
    def _replace_shape_bullets(self, shape, bullets: List[str]) -> None:
        """Replace text with bullet points, preserving formatting."""
        if not hasattr(shape, "text_frame"):
            return
        
        tf = shape.text_frame
        
        if not tf.paragraphs:
            return
        
        first_para = tf.paragraphs[0]
        
        # Store font properties from first run if available
        font_size = None
        font_bold = None
        font_name = None
        
        if first_para.runs:
            first_run = first_para.runs[0]
            font_size = first_run.font.size
            font_bold = first_run.font.bold
            font_name = first_run.font.name
        
        # Build bullet text with newlines
        bullet_text = "\n".join(f"• {bullet}" for bullet in bullets)
        
        # Set text on first paragraph
        if first_para.runs:
            first_para.runs[0].text = bullet_text
            for run in first_para.runs[1:]:
                run.text = ""
        else:
            first_para.text = bullet_text
    
    def _update_slide_2(self, slide, client_name: str) -> None:
        """Update Slide 2 with client name."""
        for shape in slide.shapes:
            if hasattr(shape, "text") and "<Give it a Title>" in shape.text:
                self._replace_shape_text(shape, client_name)
                break
    
    def _constrain_text_width(self, shape, max_right_inches: float, padding_inches: float = 0.3) -> None:
        """
        Constrain a text shape's width so it doesn't extend past max_right_inches.
        
        Also enables word wrap to ensure text reflows within the new width.
        
        Args:
            shape: The text shape to constrain
            max_right_inches: Maximum right edge position in inches
            padding_inches: Padding from the edge
        """
        max_right_emu = int((max_right_inches - padding_inches) * 914400)
        shape_left = shape.left
        
        # Calculate max width
        max_width = max_right_emu - shape_left
        
        if max_width > 0:
            old_width = shape.width / 914400
            shape.width = int(max_width)
            
            # Enable word wrap on the text frame so text reflows
            if hasattr(shape, "text_frame"):
                shape.text_frame.word_wrap = True
            
            print(f"DEBUG: Constrained shape width from {old_width:.2f}in to {max_width / 914400:.2f}in (max_right={max_right_inches}in, word_wrap=True)")
    
    def _update_slide_3(
        self, 
        slide, 
        client_description: str,
        pe_description: str,
        challenge_text: str,
        approach_bullets: List[str]
    ) -> None:
        """
        Update Slide 3 - The Challenge.
        
        Shape mapping:
        [7] -> Client description
        [8] -> PE description (anonymous but descriptive)
        [3] -> Challenge text (from client_problem_anonymized)
        [10] -> Approach bullets (from approach_summary)
        
        Slide layout (13.33in wide):
        - Left section: 0 to ~6.5in (THE CLIENT + The Challenge + Our Approach)
        - Right section: ~6.7in to 13.33in (RELATIONSHIP VIA)
        """
        shapes = list(slide.shapes)
        
        # Fixed boundaries based on slide layout
        # Left section ends at the vertical divider - reduced to prevent overflow
        LEFT_SECTION_MAX_RIGHT = 5.9
        # Right section ends at slide edge minus margin  
        RIGHT_SECTION_MAX_RIGHT = 12.5
        
        for idx, shape in enumerate(shapes):
            if not hasattr(shape, "text"):
                continue
            
            text = shape.text
            
            # [7] Client description placeholder
            if "<Anonymized Descriptive Company Name>" in text:
                # Find the "THE CLIENT:" header to align with it
                header_pos = self._find_header_position(shapes, "THE CLIENT")
                self._replace_shape_text(shape, client_description)
                # Left align the text
                self._left_align_shape_text(shape)
                # Align left edge with header, but keep original vertical position
                # (template positioning is correct, just need width constraint)
                if header_pos:
                    shape.left = header_pos["left"]
                    # Don't change top - keep template's original vertical position
                # Constrain width to fit within left section
                self._constrain_text_width(shape, LEFT_SECTION_MAX_RIGHT)
            
            # [8] PE description placeholder - Title Case and left aligned
            elif "<Anonymized Descriptive PE Name>" in text:
                # Find the "RELATIONSHIP VIA:" header to align with it
                header_pos = self._find_header_position(shapes, "RELATIONSHIP VIA")
                # Apply Title Case to PE description, then restore acronyms
                pe_text = self._preserve_acronyms(pe_description.title()) if pe_description else ""
                self._replace_shape_text(shape, pe_text)
                # Left align the text
                self._left_align_shape_text(shape)
                # Align left edge with header, but keep original vertical position
                if header_pos:
                    shape.left = header_pos["left"]
                    # Don't change top - keep template's original vertical position
                # Constrain width to fit within right section
                self._constrain_text_width(shape, RIGHT_SECTION_MAX_RIGHT)
            
            # [3] Challenge text - the long paragraph (not the title)
            # Identify by: contains "client had grown" OR is shape index 3
            elif "The client had grown through rapid M&A" in text:
                # This is a challenge content area - check position to distinguish
                # Shape at top=3.2in is the challenge, shape at top=5.1in is approach
                if hasattr(shape, 'top'):
                    top_inches = shape.top / 914400  # Convert EMU to inches
                    if top_inches < 4.0:  # Challenge text
                        if challenge_text:
                            self._replace_shape_text(shape, challenge_text)
                    else:  # Approach text (top ~5.1in)
                        if approach_bullets:
                            # If single paragraph (from LLM summarization), use as-is
                            # If multiple items, join without bullet points
                            if len(approach_bullets) == 1:
                                approach_text = approach_bullets[0]
                            else:
                                approach_text = " ".join(approach_bullets[:4])
                            self._replace_shape_text(shape, approach_text)
    
    def _update_slide_4(
        self,
        slide,
        top_levers: List[str],
        impact_metrics: List[Dict[str, str]],
        differentiators: List[str]
    ) -> None:
        """
        Update Slide 4 - Key Levers / Value Delivered.
        
        Uses direct shape index matching based on template structure.
        Template shape indices (0-based):
        - [2] = Key Levers bullets
        - [4] = Metric 1 value (orange text)
        - [5] = Metric 1 description (white text)
        - [6] = Metric 2 value
        - [7] = Metric 2 description
        - [8] = Metric 3 value
        - [9] = Metric 3 description (may not exist in template)
        - [10] = "Our Differentiators" header
        - [11] = Differentiators bullets
        """
        shapes_list = list(slide.shapes)
        
        # Debug: Print all shapes
        print(f"DEBUG: Slide 4 has {len(shapes_list)} shapes")
        for idx, shape in enumerate(shapes_list):
            if hasattr(shape, "text") and shape.text.strip():
                left_in = shape.left / 914400
                top_in = shape.top / 914400
                text_preview = shape.text[:40].replace('\n', ' ')
                print(f"  [{idx}] L={left_in:.1f} T={top_in:.1f} '{text_preview}...'")
        
        # =========================================================================
        # Left Side: Key Levers (shape index 2)
        # =========================================================================
        if len(shapes_list) > 2 and top_levers:
            shape = shapes_list[2]
            if hasattr(shape, "text_frame"):
                # Clean and join levers - strip any existing bullet chars from source data
                cleaned_levers = [self._strip_bullet_chars(lever) for lever in top_levers[:5]]
                lever_text = "\n".join(cleaned_levers)
                self._replace_shape_text(shape, lever_text)
                # Apply orange square bullets
                self._apply_square_bullets(shape)
                print(f"DEBUG: Updated Key Levers (shape 2) with {len(cleaned_levers)} items")
        
        # =========================================================================
        # Left Side: Differentiators (shape index 11)
        # =========================================================================
        if len(shapes_list) > 11 and differentiators:
            shape = shapes_list[11]
            if hasattr(shape, "text_frame"):
                # Clean and truncate differentiators to prevent overflow
                # Only use 2 items max to ensure they fit in available space
                cleaned_diffs = []
                MAX_ITEM_CHARS = 170   # Limit each item length (increased from 150)
                
                for diff in differentiators[:2]:  # Max 2 items
                    clean = self._strip_bullet_chars(diff)
                    # Truncate long items
                    if len(clean) > MAX_ITEM_CHARS:
                        clean = clean[:MAX_ITEM_CHARS - 3].rsplit(' ', 1)[0] + "..."
                    cleaned_diffs.append(clean)
                
                diff_text = "\n".join(cleaned_diffs)
                self._replace_shape_text(shape, diff_text)
                # Apply orange square bullets
                self._apply_square_bullets(shape)
                print(f"DEBUG: Updated Differentiators (shape 11) with {len(cleaned_diffs)} items")
        
        # =========================================================================
        # Right Side: Value Delivered Metrics
        # Find shapes by text pattern matching since indices vary
        # =========================================================================
        
        # Find all right-side text shapes and identify by content
        value_shapes = []  # Shapes with $ or short numeric text (value shapes)
        desc_shapes = []   # Shapes with longer descriptive text
        
        for idx, shape in enumerate(shapes_list):
            if not hasattr(shape, "text"):
                continue
            left_in = shape.left / 914400
            text = shape.text.strip()
            
            # Right side shapes (Value Delivered section, x > 5.5 inches)
            if left_in > 5.5 and text:
                # Skip headers
                if text == "Value Delivered":
                    continue
                
                # Identify value vs description shapes
                # Value shapes: have $, or short with numbers, or percentage
                is_value = (
                    "$" in text or 
                    "%" in text or
                    (len(text) < 25 and any(c.isdigit() for c in text))
                )
                
                if is_value:
                    value_shapes.append({"idx": idx, "shape": shape, "text": text, "top": shape.top})
                    print(f"DEBUG: Found VALUE shape [{idx}] = '{text}'")
                else:
                    desc_shapes.append({"idx": idx, "shape": shape, "text": text, "top": shape.top})
                    print(f"DEBUG: Found DESC shape [{idx}] = '{text}'")
        
        # Sort by vertical position
        value_shapes.sort(key=lambda x: x["top"])
        desc_shapes.sort(key=lambda x: x["top"])
        
        print(f"DEBUG: Found {len(value_shapes)} value shapes, {len(desc_shapes)} desc shapes")
        
        # Calculate expected positions for consistent spacing
        # Template pattern: value at T, desc at T+0.5, next value at T+1.4
        # Value 1: 1.5in, Desc 1: 2.0in, Value 2: 2.9in, Desc 2: 3.4in
        # Expected Value 3: 4.3in (not 4.6in as in template)
        EXPECTED_VALUE_3_TOP = Inches(4.3)
        VALUE_DESC_OFFSET = Inches(0.5)  # Consistent offset between value and desc
        
        # Update metrics (pair by position - value then desc below it)
        for metric_idx, metric in enumerate(impact_metrics[:3]):
            value_text = metric.get("value", "")
            desc_text = metric.get("description", "")
            
            # Update value shape
            if metric_idx < len(value_shapes) and value_text:
                v_shape = value_shapes[metric_idx]["shape"]
                v_idx = value_shapes[metric_idx]["idx"]
                
                # For the 3rd metric, move the value shape up for consistent spacing
                if metric_idx == 2:
                    old_top = v_shape.top
                    v_shape.top = int(EXPECTED_VALUE_3_TOP)
                    print(f"DEBUG: Moved metric 3 value from T={old_top/914400:.2f}in to T={EXPECTED_VALUE_3_TOP/914400:.2f}in")
                
                self._replace_shape_text(v_shape, value_text)
                print(f"DEBUG: Set metric {metric_idx + 1} value (shape {v_idx}) = '{value_text}'")
            
            # Update description shape
            if metric_idx < len(desc_shapes) and desc_text:
                d_shape = desc_shapes[metric_idx]["shape"]
                d_idx = desc_shapes[metric_idx]["idx"]
                self._replace_shape_text(d_shape, desc_text)
                print(f"DEBUG: Set metric {metric_idx + 1} desc (shape {d_idx}) = '{desc_text}'")
            elif metric_idx >= len(desc_shapes) and desc_text and metric_idx < len(value_shapes):
                # No description shape exists for this metric - create one
                # Pass existing value/desc pair to calculate exact offset
                v_shape = value_shapes[metric_idx]["shape"]
                reference_value = value_shapes[0]["shape"] if value_shapes else None
                reference_desc = desc_shapes[0]["shape"] if desc_shapes else None
                self._create_metric_description(slide, v_shape, desc_text, metric_idx, reference_value, reference_desc)
                print(f"DEBUG: Created new desc shape for metric {metric_idx + 1} = '{desc_text}'")
            
            # Don't adjust spacing for existing template shapes - they're already positioned correctly
            # Only the newly created description shape needs positioning (handled in _create_metric_description)
    
    def _apply_metric_spacing(self, value_shape, desc_shape) -> None:
        """Apply consistent spacing between value and description shapes."""
        # Use fixed offset from value top instead of calculating from height
        # This ensures consistent visual spacing regardless of shape container size
        # Value text is about 0.5in tall, so place desc at value_top + 0.55in
        FIXED_OFFSET = Inches(0.55)
        
        try:
            new_desc_top = value_shape.top + FIXED_OFFSET
            desc_shape.top = int(new_desc_top)
            print(f"DEBUG: Set desc top to {new_desc_top / 914400:.2f}in (offset=0.55in from value)")
        except Exception as e:
            print(f"DEBUG: Spacing failed: {e}")
    
    def _create_metric_description(self, slide, value_shape, desc_text: str, metric_idx: int, reference_value=None, reference_desc=None) -> None:
        """
        Create a new description text box below a value shape.
        
        Used when the template doesn't have a description shape for a metric.
        Copies position offset and font properties from reference value/desc pair.
        """
        from pptx.util import Pt
        from pptx.dml.color import RGBColor
        from pptx.enum.text import PP_ALIGN
        
        # Use consistent 0.5in offset matching template pattern
        # Template: Value 1 (T=1.5) → Desc 1 (T=2.0) = 0.5in offset
        # Template: Value 2 (T=2.9) → Desc 2 (T=3.4) = 0.5in offset
        offset = Inches(0.5)
        
        # Use the value shape's left position (ensures alignment)
        left = value_shape.left
        
        # Match width of reference description, or use default
        if reference_desc:
            width = reference_desc.width
            height = reference_desc.height
        else:
            width = Inches(5.5)
            height = Inches(0.35)
        
        # Position below the value shape using fixed offset
        top = value_shape.top + offset
        
        # Debug: show calculated position
        print(f"DEBUG: New desc position - left={left / 914400:.2f}in, top={top / 914400:.2f}in (fixed offset=0.35in)")
        
        # Extract font properties from reference description if available
        font_name = None
        font_size = Pt(18)
        font_bold = False
        font_italic = False
        
        if reference_desc and hasattr(reference_desc, "text_frame"):
            try:
                ref_tf = reference_desc.text_frame
                if ref_tf.paragraphs and ref_tf.paragraphs[0].runs:
                    ref_run = ref_tf.paragraphs[0].runs[0]
                    font_name = ref_run.font.name
                    if ref_run.font.size:
                        font_size = ref_run.font.size
                    font_bold = ref_run.font.bold or False
                    font_italic = ref_run.font.italic or False
                    print(f"DEBUG: Copied font from reference: name={font_name}, size={font_size}, bold={font_bold}")
            except Exception as e:
                print(f"DEBUG: Could not read reference font: {e}")
        
        try:
            # Truncate text if too long to fit on one line
            max_chars = 35
            if len(desc_text) > max_chars:
                desc_text = desc_text[:max_chars-3].rsplit(' ', 1)[0] + "..."
            
            # Add text box
            textbox = slide.shapes.add_textbox(left, top, width, height)
            tf = textbox.text_frame
            tf.word_wrap = False  # Keep on single line
            
            # Set text
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.LEFT
            
            # Create run with text
            run = p.runs[0] if p.runs else p.add_run()
            run.text = desc_text
            
            # Apply font properties
            run.font.size = font_size
            run.font.color.rgb = RGBColor(255, 255, 255)  # White
            run.font.bold = font_bold
            run.font.italic = font_italic
            if font_name:
                run.font.name = font_name
            
            print(f"DEBUG: Created desc textbox at L={left/914400:.1f}in T={top/914400:.1f}in with font={font_name}")
        except Exception as e:
            print(f"DEBUG: Failed to create desc textbox: {e}")
    
    def _strip_bullet_chars(self, text: str) -> str:
        """Strip bullet characters and leading whitespace from text."""
        if not text:
            return ""
        # Strip common bullet characters: •, ·, -, *, ●, ○, ▪, ▸, ►
        cleaned = text.lstrip('•·-*●○▪▸► \t')
        return cleaned.strip()
    
    def _apply_square_bullets(self, shape) -> None:
        """Apply orange square bullet style to a text shape."""
        from pptx.dml.color import RGBColor
        from pptx.oxml.ns import qn
        from pptx.oxml import parse_xml
        from lxml import etree
        
        if not hasattr(shape, "text_frame"):
            return
        
        try:
            tf = shape.text_frame
            # Treya orange color
            orange = RGBColor(0xe8, 0x6c, 0x00)
            
            for para in tf.paragraphs:
                # Access the paragraph's XML element
                pPr = para._p.get_or_add_pPr()
                
                # Remove existing bullet settings
                for child in list(pPr):
                    if 'buChar' in child.tag or 'buFont' in child.tag or 'buClr' in child.tag or 'buAutoNum' in child.tag:
                        pPr.remove(child)
                
                # Set bullet font explicitly for cross-system compatibility
                buFont = etree.SubElement(pPr, qn('a:buFont'))
                buFont.set('typeface', 'Arial')
                buFont.set('panose', '020B0604020202020204')
                buFont.set('pitchFamily', '34')
                buFont.set('charset', '0')
                
                # Add small square bullet character
                buChar = etree.SubElement(pPr, qn('a:buChar'))
                buChar.set('char', '▪')  # Small square bullet
                
                # Set bullet size to 70% of text size for smaller appearance
                buSzPct = etree.SubElement(pPr, qn('a:buSzPct'))
                buSzPct.set('val', '70000')  # 70% size
                
                # Add bullet color (orange) - explicit sRGB ensures color is preserved
                buClr = etree.SubElement(pPr, qn('a:buClr'))
                srgbClr = etree.SubElement(buClr, qn('a:srgbClr'))
                srgbClr.set('val', 'E86C00')  # Treya orange
            
            print(f"DEBUG: Applied orange square bullets")
        except Exception as e:
            print(f"DEBUG: Could not apply square bullets: {e}")
    
    def _update_slide_5(self, slide, categories: List[Dict[str, Any]], prs: Presentation) -> None:
        """
        Update Slide 5 - Category outcomes table + bar chart.
        
        - Update table with category data (% Savings shows actual percentages)
        - Delete existing picture and create our own bar chart
        """
        # Find the table and picture
        table_shape = None
        picture_shape = None
        picture_idx = None
        
        for idx, shape in enumerate(slide.shapes):
            if hasattr(shape, "has_table") and shape.has_table:
                table_shape = shape
            # Picture is shape type 13
            if shape.shape_type == 13:  # MSO_SHAPE_TYPE.PICTURE
                picture_shape = shape
                picture_idx = idx
        
        # Update the table
        if table_shape:
            self._update_category_table(table_shape.table, categories)
            
            # Resize table to fill available vertical space
            self._resize_table_to_fit(table_shape, categories, prs)
        
        # Delete old picture and add bar chart
        if picture_shape and categories:
            # Match chart position and size to the table
            if table_shape:
                table_top = table_shape.top
                table_height = table_shape.height
                # Position chart to align with table vertically
                top = table_top
                chart_height_emu = table_height
            else:
                top = Inches(1.5)
                chart_height_emu = Inches(5.5)
            
            # Position chart to the right of table, extend to near slide edge
            left = Inches(8.1)   # Start position
            chart_width = Inches(5.0)  # Wider to match table presence
            chart_height = chart_height_emu
            
            # Remove old picture
            sp = picture_shape._element
            sp.getparent().remove(sp)
            
            # Create bar chart with proper sizing
            chart_path = self._create_bar_chart(categories)
            if chart_path and chart_path.exists():
                slide.shapes.add_picture(
                    str(chart_path),
                    left, top,
                    width=chart_width,
                    height=chart_height
                )
                # Clean up temp file
                chart_path.unlink()
    
    def _update_category_table(self, table, categories: List[Dict[str, Any]]) -> None:
        """
        Update table with category data.
        
        Columns: Category | Incumbent Vendors | Awarded Vendors | Key Lever(s)
        (% Savings column removed - shown in bar chart instead)
        """
        # First, delete the % Savings column (column 3) from the table
        # We need to remove the 4th column (index 3) from each row
        self._delete_table_column(table, 3)
        
        # Row 0 is header, rows 1-7 are data
        for row_idx, cat in enumerate(categories):
            if row_idx >= 7:  # Max 7 categories
                break
            
            data_row_idx = row_idx + 1
            if data_row_idx >= len(table.rows):
                break
            
            row = table.rows[data_row_idx]
            
            # Column 0: Category
            label = cat.get("category_label", "")
            self._set_cell_text(row.cells[0], label)
            
            # Column 1: Incumbent Vendors (vendors_before)
            vendors_before = cat.get("vendors_before", [])
            if isinstance(vendors_before, list):
                vendors_before_str = ", ".join(str(v) for v in vendors_before[:2])
            else:
                vendors_before_str = str(vendors_before) if vendors_before else ""
            self._set_cell_text(row.cells[1], vendors_before_str)
            
            # Column 2: Awarded Vendors (vendors_after)
            vendors_after = cat.get("vendors_after", [])
            if isinstance(vendors_after, list):
                vendors_after_str = ", ".join(str(v) for v in vendors_after[:2])
            else:
                vendors_after_str = str(vendors_after) if vendors_after else ""
            self._set_cell_text(row.cells[2], vendors_after_str)
            
            # Column 3: Key Lever(s) (was column 4 before % Savings removed)
            levers = cat.get("levers", [])
            if isinstance(levers, list):
                lever_str = ", ".join(str(l) for l in levers[:2])
            else:
                lever_str = str(levers) if levers else ""
            self._set_cell_text(row.cells[3], lever_str)
        
        # Delete extra rows if fewer than 7 categories
        num_categories = min(len(categories), 7)
        rows_to_keep = num_categories + 1  # +1 for header row
        
        # Remove extra rows from the end
        self._delete_extra_table_rows(table, rows_to_keep)
    
    def _set_cell_text(self, cell, text: str) -> None:
        """Set cell text while preserving formatting."""
        if cell.text_frame and cell.text_frame.paragraphs:
            para = cell.text_frame.paragraphs[0]
            if para.runs:
                para.runs[0].text = text
                for run in para.runs[1:]:
                    run.text = ""
            else:
                para.text = text
    
    def _center_shape_text(self, shape) -> None:
        """Center align all text in a shape."""
        from pptx.enum.text import PP_ALIGN
        
        if not hasattr(shape, "text_frame"):
            return
        
        try:
            for para in shape.text_frame.paragraphs:
                para.alignment = PP_ALIGN.CENTER
        except Exception as e:
            print(f"DEBUG: Could not center text: {e}")
    
    def _left_align_shape_text(self, shape) -> None:
        """Left align all text in a shape."""
        from pptx.enum.text import PP_ALIGN
        
        if not hasattr(shape, "text_frame"):
            return
        
        try:
            for para in shape.text_frame.paragraphs:
                para.alignment = PP_ALIGN.LEFT
        except Exception as e:
            print(f"DEBUG: Could not left align text: {e}")
    
    def _find_header_position(self, shapes, header_text: str):
        """Find the position of a header shape by its text content."""
        for shape in shapes:
            if hasattr(shape, "text") and header_text in shape.text:
                print(f"DEBUG: Found header '{header_text}' at left={shape.left / 914400:.2f}in, top={shape.top / 914400:.2f}in")
                return {"left": shape.left, "top": shape.top, "height": shape.height}
        return None
    
    def _widen_shape(self, shape, target_width) -> None:
        """Widen a shape to allow more text per line."""
        try:
            current_width = shape.width
            if target_width > current_width:
                # Keep shape centered by adjusting left position
                width_increase = target_width - current_width
                shape.left = max(0, shape.left - int(width_increase / 2))
                shape.width = int(target_width)
                print(f"DEBUG: Widened shape to {target_width / 914400:.1f}in")
        except Exception as e:
            print(f"DEBUG: Could not widen shape: {e}")
    
    def _delete_table_column(self, table, col_idx: int) -> None:
        """Delete a column from the table by removing cells from each row."""
        try:
            tbl = table._tbl
            for tr in tbl.tr_lst:
                cells = tr.tc_lst
                if col_idx < len(cells):
                    cell_to_remove = cells[col_idx]
                    tr.remove(cell_to_remove)
            
            # Update gridCol to remove the column width definition
            grid_cols = tbl.tblGrid.gridCol_lst
            if col_idx < len(grid_cols):
                grid_cols[col_idx].getparent().remove(grid_cols[col_idx])
        except Exception:
            # If deletion fails, just clear the column content instead
            for row in table.rows:
                if col_idx < len(row.cells):
                    self._set_cell_text(row.cells[col_idx], "")
    
    def _delete_extra_table_rows(self, table, rows_to_keep: int) -> None:
        """Delete extra rows from the table, keeping only the specified number."""
        try:
            tbl = table._tbl
            tr_list = tbl.tr_lst
            
            # Remove rows from the end until we have the right number
            while len(tr_list) > rows_to_keep:
                row_to_remove = tr_list[-1]  # Get last row
                tbl.remove(row_to_remove)
                tr_list = tbl.tr_lst  # Refresh the list
            
            print(f"DEBUG: Table now has {len(tbl.tr_lst)} rows (kept {rows_to_keep})")
        except Exception as e:
            print(f"DEBUG: Could not delete table rows: {e}")
    
    def _resize_table_to_fit(self, table_shape, categories: List[Dict[str, Any]], prs: Presentation) -> None:
        """
        Resize the table to fill available vertical space on the slide.
        
        - Keeps the table top position fixed
        - Expands table height to use available space
        - Distributes row heights evenly
        """
        try:
            table = table_shape.table
            num_rows = len(table.rows)
            
            if num_rows < 2:  # Need at least header + 1 data row
                return
            
            # Get slide dimensions
            slide_height = prs.slide_height
            
            # Define target area (leave margins)
            # Top margin: keep current table top
            # Bottom margin: ~0.75 inch from bottom
            table_top = table_shape.top
            bottom_margin = Inches(0.75)
            target_bottom = slide_height - bottom_margin
            
            # Calculate new table height
            new_height = target_bottom - table_top
            
            # Don't make table too tall - cap based on number of rows
            # Max ~0.8 inch per row to avoid overly stretched rows
            max_row_height = Inches(0.8)
            max_height = num_rows * max_row_height
            new_height = min(new_height, max_height)
            
            # Set new table height
            table_shape.height = int(new_height)
            
            # Distribute row heights evenly
            row_height = int(new_height / num_rows)
            for row in table.rows:
                row.height = row_height
            
            print(f"DEBUG: Resized table to height={new_height/914400:.2f}in with {num_rows} rows @ {row_height/914400:.2f}in each")
        except Exception as e:
            print(f"DEBUG: Could not resize table: {e}")
    
    def _create_bar_chart(self, categories: List[Dict[str, Any]]) -> Optional[Path]:
        """
        Create bar chart showing savings by category.
        
        Same style as original /powerpoint command's _create_bar_chart_compact.
        """
        try:
            import matplotlib.pyplot as plt
            import matplotlib
            matplotlib.use('Agg')
            import numpy as np
        except ImportError:
            return None
        
        # Extract data
        labels = []
        percentages = []
        
        for cat in categories:
            label = cat.get("category_label", "Unknown")
            labels.append(label)
            
            # Get savings percentage
            pct_val = cat.get("savings_percentage", 0)
            if isinstance(pct_val, (int, float)):
                pct_num = float(pct_val)
            elif isinstance(pct_val, str):
                pct_num = float(pct_val.replace("%", "").replace(",", "")) if pct_val else 0
            else:
                pct_num = 0
            
            # If no percentage, try to calculate
            if not pct_num:
                baseline = cat.get("baseline_spend", {})
                savings = cat.get("savings_annual_run_rate", {})
                baseline_amt = baseline.get("amount", 0) if isinstance(baseline, dict) else (baseline or 0)
                savings_amt = savings.get("amount", 0) if isinstance(savings, dict) else (savings or 0)
                if baseline_amt and savings_amt:
                    pct_num = (savings_amt / baseline_amt) * 100
            
            percentages.append(pct_num)
        
        if not percentages or all(p == 0 for p in percentages):
            return None
        
        # Chart styling - sized to fit slide space (4.8in x 5.0in)
        num_categories = len(labels)
        
        # Adjust font and bar sizing based on number of categories
        if num_categories <= 4:
            label_fontsize = 9
            bar_height = 0.6
        elif num_categories <= 6:
            label_fontsize = 8
            bar_height = 0.55
        else:
            label_fontsize = 7
            bar_height = 0.5
        
        # Figure size matches the slide chart area (5.0in wide, height matches table)
        fig, ax = plt.subplots(figsize=(5.0, 5.5), facecolor='#e8e4dc')
        ax.set_facecolor('#e8e4dc')
        
        # Sort by percentage (highest first)
        sorted_data = sorted(zip(labels, percentages), key=lambda x: x[1], reverse=True)
        labels_sorted = [x[0] for x in sorted_data]
        pcts_sorted = [x[1] for x in sorted_data]
        
        # Reverse for matplotlib (so highest is at top)
        labels_r = list(reversed(labels_sorted))
        pcts_r = list(reversed(pcts_sorted))
        
        y_pos = np.arange(len(labels_r))
        
        # Blue gradient matching table header color scheme
        # High savings = dark teal, Low savings = lighter blue
        max_pct = max(pcts_r) if pcts_r else 1
        colors = []
        
        # Color stops for blue gradient
        dark_blue = (0x1a, 0x4a, 0x5e)    # Dark teal (high savings) - matches table header
        mid_blue = (0x3d, 0x7a, 0x8c)     # Medium teal
        light_blue = (0x7a, 0xb3, 0xc2)   # Light teal/blue (low savings)
        
        for pct in pcts_r:
            ratio = pct / max_pct if max_pct > 0 else 0.5
            
            if ratio >= 0.5:
                # Blend from mid to dark (high savings)
                blend = (ratio - 0.5) * 2
                r = int(mid_blue[0] + (dark_blue[0] - mid_blue[0]) * blend)
                g = int(mid_blue[1] + (dark_blue[1] - mid_blue[1]) * blend)
                b = int(mid_blue[2] + (dark_blue[2] - mid_blue[2]) * blend)
            else:
                # Blend from light to mid (low savings)
                blend = ratio * 2
                r = int(light_blue[0] + (mid_blue[0] - light_blue[0]) * blend)
                g = int(light_blue[1] + (mid_blue[1] - light_blue[1]) * blend)
                b = int(light_blue[2] + (mid_blue[2] - light_blue[2]) * blend)
            
            colors.append(f'#{r:02x}{g:02x}{b:02x}')
        
        # Create horizontal bars
        bars = ax.barh(y_pos, pcts_r, color=colors, edgecolor='white', height=bar_height, linewidth=1.5)
        
        # Add value labels on bars
        for bar, pct in zip(bars, pcts_r):
            width = bar.get_width()
            if width > max_pct * 0.3:
                ax.text(
                    width - 0.5, bar.get_y() + bar.get_height()/2,
                    f'{pct:.0f}%',
                    va='center', ha='right',
                    fontsize=label_fontsize, fontweight='bold', color='white'
                )
            else:
                ax.text(
                    width + 0.3, bar.get_y() + bar.get_height()/2,
                    f'{pct:.0f}%',
                    va='center', ha='left',
                    fontsize=label_fontsize, fontweight='bold', color='#3d3d3d'
                )
        
        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels_r, fontsize=label_fontsize)
        ax.set_xlabel('Savings %', fontsize=10, fontweight='bold', color='#3d3d3d')
        # Center title over entire figure (not just axes)
        fig.suptitle('Savings by Category', fontsize=13, fontweight='bold', color='#3d3d3d', y=0.96)
        
        # Create space between title and chart by shrinking plot area
        fig.subplots_adjust(top=0.88)
        
        # Style the chart
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_color('#6c757d')
        ax.spines['left'].set_visible(False)
        ax.tick_params(left=False, colors='#3d3d3d')
        
        # Add subtle grid
        ax.xaxis.grid(True, linestyle='--', alpha=0.3, color='#6c757d')
        ax.set_axisbelow(True)
        
        # Set x-axis limit
        max_val = max(pcts_r) if pcts_r else 50
        ax.set_xlim(0, max_val * 1.2)
        
        # No legend - all bars are same color matching table header
        
        # Save to temp file
        import tempfile
        temp_dir = tempfile.gettempdir()
        output_path = Path(temp_dir) / "pptx_bar_chart.png"
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, facecolor='#e8e4dc', bbox_inches='tight')
        plt.close()
        
        return output_path
