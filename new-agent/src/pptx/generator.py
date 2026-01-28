"""
PowerPoint Case Study Generator.

Generates styled PowerPoint presentations from case study extraction data.
Creates clean, professional slides with Treya Partners branding.

Color scheme: Orange, White, Gray (matching Treya brand)

Slides:
1. Title - Client name, industry, Treya logo
2. Challenge + Approach - Two-column layout
3. Results + Differentiators - Value delivered and unique factors
4. Categories Table - Detailed category breakdown
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Any

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

from src.pptx.logo_fetcher import LogoFetcher

# Chart colors matching Treya brand
CHART_ORANGE = '#e86c00'
CHART_DARK_GRAY = '#3d3d3d'
CHART_MEDIUM_GRAY = '#6c757d'
CHART_LIGHT_GRAY = '#f5f5f5'
CHART_COLORS = ['#e86c00', '#f59e4d', '#3d3d3d', '#6c757d', '#a0a0a0', '#d4a574', '#8b5a2b', '#cd853f']


class CaseStudyPPTXGenerator:
    """Legacy generator class for backward compatibility."""
    
    def __init__(self, template_path: Path):
        self.template_path = template_path
        if not template_path.exists():
            raise FileNotFoundError(f"Template not found: {template_path}")


class CaseStudyPPTXGeneratorV2:
    """
    Generator that creates a clean 4-slide case study presentation.
    
    Treya brand colors: Orange, White, Gray
    
    Slides:
    1. Title - Client name, industry, Treya logo
    2. Challenge + Approach
    3. Results + Differentiators
    4. Categories Table
    """
    
    # Treya brand colors (orange, white, gray theme)
    ORANGE = RGBColor(0xe8, 0x6c, 0x00)        # Treya orange - primary accent
    ORANGE_LIGHT = RGBColor(0xf5, 0x9e, 0x4d)  # Light orange
    DARK_GRAY = RGBColor(0x3d, 0x3d, 0x3d)     # Dark gray - headers/text
    MEDIUM_GRAY = RGBColor(0x6c, 0x75, 0x7d)   # Medium gray
    LIGHT_GRAY = RGBColor(0xf5, 0xf5, 0xf5)    # Light gray - backgrounds
    OFF_WHITE = RGBColor(0xe8, 0xe4, 0xdc)     # Light tan/beige - slide backgrounds (noticeable contrast with white)
    WHITE = RGBColor(0xff, 0xff, 0xff)
    BLACK = RGBColor(0x33, 0x33, 0x33)         # Soft black for body text
    
    # Slide dimensions (16:9 widescreen)
    SLIDE_WIDTH = Inches(13.333)
    SLIDE_HEIGHT = Inches(7.5)
    
    # Path to Treya logo (extracted from template)
    LOGO_PATH = Path(__file__).parent.parent.parent / "treya_logo.png"
    
    def __init__(self, template_path: Path):
        """Initialize with template path."""
        self.template_path = template_path
        self.logo_fetcher = LogoFetcher()
        
        if not template_path.exists():
            raise FileNotFoundError(f"Template not found: {template_path}")
    
    def generate_from_extraction(
        self,
        client_context: Dict[str, Any],
        case_study: Dict[str, Any],
        impact: Dict[str, Any],
        output_path: Path,
        categories_data: Optional[Dict[str, Any]] = None,
        client_logo_path: Optional[Path] = None,
    ) -> Path:
        """
        Generate PowerPoint from extraction results.
        
        Creates 4 slides:
        1. Title with client info and Treya logo
        2. Challenge + Approach
        3. Results + Differentiators
        4. Categories table
        
        Args:
            client_context: Client context data from Step 4
            case_study: Case study packaging data from Step 8
            impact: Impact data from Step 6
            categories_data: Categories data from Step 7 (optional)
            output_path: Where to save the output
            client_logo_path: Optional path to client logo image
            
        Returns:
            Path to the generated file
        """
        # Get case study packaging
        packaging = case_study.get("case_study_packaging", case_study)
        
        # Get client info for title slide
        client = client_context.get("client", {})
        client_name = client.get("client_name", "Client")
        industry = client.get("industry_primary", "")
        pe_sponsor = client.get("sponsor_pe_firm", "")
        company_website = client.get("company_website", "")
        
        # Auto-fetch client logo if not provided
        logo_fetch_status = None
        logo_debug_log = []
        if not client_logo_path and client_name:
            try:
                fetched_logo = self.logo_fetcher.fetch_logo(
                    company_name=client_name,
                    company_website=company_website
                )
                logo_debug_log = self.logo_fetcher.get_debug_log()
                
                if fetched_logo and fetched_logo.exists():
                    client_logo_path = fetched_logo
                    logo_fetch_status = f"✓ Client logo found: {fetched_logo.name}"
                else:
                    logo_fetch_status = f"⚠ Client logo not found for: {client_name}"
            except Exception as e:
                logo_fetch_status = f"✗ Logo fetch error: {e}"
        
        # Store logo status for external access
        self._last_logo_status = logo_fetch_status
        self._last_logo_debug = logo_debug_log
        
        # Create new presentation
        prs = Presentation()
        prs.slide_width = self.SLIDE_WIDTH
        prs.slide_height = self.SLIDE_HEIGHT
        
        # Get blank layout
        blank_layout = prs.slide_layouts[6]
        
        # Slide 1: Title
        self._create_title_slide(prs, blank_layout, client_name, industry, pe_sponsor, packaging, client_logo_path)
        
        # Slide 2: Challenge + Approach
        self._create_challenge_slide(prs, blank_layout, packaging)
        
        # Slide 3: Results + Differentiators
        self._create_results_slide(prs, blank_layout, packaging)
        
        # Slide 4: Categories Table
        if categories_data:
            self._create_categories_slide(prs, blank_layout, categories_data)
        
        # Slide 5: Charts/Analytics
        if categories_data:
            self._create_charts_slide(prs, blank_layout, categories_data, impact)
        
        # Save to output path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        prs.save(str(output_path))
        
        return output_path
    
    def _add_treya_logo(self, slide, left: float = 10.5, top: float = 6.7, width: float = 2.5) -> None:
        """Add Treya Partners logo to a slide."""
        if self.LOGO_PATH.exists():
            try:
                slide.shapes.add_picture(
                    str(self.LOGO_PATH),
                    Inches(left), Inches(top),
                    width=Inches(width)
                )
            except Exception:
                # If logo fails, add text fallback
                self._add_treya_text_logo(slide, left, top)
        else:
            self._add_treya_text_logo(slide, left, top)
    
    def _add_treya_text_logo(self, slide, left: float, top: float) -> None:
        """Add text-based Treya branding as fallback."""
        logo_box = slide.shapes.add_textbox(
            Inches(left), Inches(top),
            Inches(2.5), Inches(0.4)
        )
        tf = logo_box.text_frame
        p = tf.paragraphs[0]
        p.text = "TREYA PARTNERS"
        p.font.size = Pt(12)
        p.font.bold = True
        p.font.color.rgb = self.ORANGE
        p.alignment = PP_ALIGN.RIGHT
    
    def _add_slide_background(self, slide) -> None:
        """Add off-white background to a slide."""
        bg_shape = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0), Inches(0),
            self.SLIDE_WIDTH, self.SLIDE_HEIGHT
        )
        bg_shape.fill.solid()
        bg_shape.fill.fore_color.rgb = self.OFF_WHITE
        bg_shape.line.fill.background()
        # Send to back
        spTree = slide.shapes._spTree
        sp = bg_shape._element
        spTree.remove(sp)
        spTree.insert(2, sp)  # Insert after slide properties
    
    def _add_footer_bar(self, slide, page_num: int, total_pages: int = 4) -> None:
        """Add professional footer bar with page numbers."""
        # Subtle footer line
        footer_line = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0.5), Inches(7.15),
            Inches(12.33), Inches(0.02)
        )
        footer_line.fill.solid()
        footer_line.fill.fore_color.rgb = RGBColor(0xd0, 0xd0, 0xd0)  # Light gray line
        footer_line.line.fill.background()
        
        # Page number
        page_box = slide.shapes.add_textbox(
            Inches(0.5), Inches(7.2),
            Inches(1), Inches(0.3)
        )
        tf = page_box.text_frame
        p = tf.paragraphs[0]
        p.text = f"{page_num}"
        p.font.size = Pt(10)
        p.font.color.rgb = self.MEDIUM_GRAY
        p.alignment = PP_ALIGN.LEFT
    
    def _add_corner_accent(self, slide, corner: str = "top_right") -> None:
        """Add decorative corner accent."""
        if corner == "top_right":
            # Small orange triangle accent in top right
            accent = slide.shapes.add_shape(
                MSO_SHAPE.RIGHT_TRIANGLE,
                Inches(12.5), Inches(0),
                Inches(0.833), Inches(0.5)
            )
            accent.fill.solid()
            accent.fill.fore_color.rgb = self.ORANGE
            accent.line.fill.background()
            # Rotate to point correctly
            accent.rotation = 90
        elif corner == "bottom_left":
            # Small orange accent bar in bottom left
            accent = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                Inches(0), Inches(7.3),
                Inches(0.15), Inches(0.2)
            )
            accent.fill.solid()
            accent.fill.fore_color.rgb = self.ORANGE
            accent.line.fill.background()
    
    def _add_header_with_depth(self, slide, title: str, subtitle: str = None) -> None:
        """Add professional header bar with depth and styling."""
        # Main header bar
        header_bar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0), Inches(0),
            self.SLIDE_WIDTH, Inches(1.2)
        )
        header_bar.fill.solid()
        header_bar.fill.fore_color.rgb = self.DARK_GRAY
        header_bar.line.fill.background()
        
        # Subtle shadow effect (darker bar below)
        shadow = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0), Inches(1.2),
            self.SLIDE_WIDTH, Inches(0.05)
        )
        shadow.fill.solid()
        shadow.fill.fore_color.rgb = RGBColor(0x2a, 0x2a, 0x2a)  # Darker gray shadow
        shadow.line.fill.background()
        
        # Orange accent line
        accent_line = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0), Inches(1.25),
            self.SLIDE_WIDTH, Inches(0.06)
        )
        accent_line.fill.solid()
        accent_line.fill.fore_color.rgb = self.ORANGE
        accent_line.line.fill.background()
        
        # Title text
        title_box = slide.shapes.add_textbox(
            Inches(0.6), Inches(0.35),
            Inches(10), Inches(0.7)
        )
        tf = title_box.text_frame
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(32)
        p.font.bold = True
        p.font.color.rgb = self.WHITE
        
        # Small orange accent before title
        title_accent = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0.3), Inches(0.4),
            Inches(0.15), Inches(0.55)
        )
        title_accent.fill.solid()
        title_accent.fill.fore_color.rgb = self.ORANGE
        title_accent.line.fill.background()
    
    def _create_title_slide(
        self, 
        prs: Presentation, 
        layout, 
        client_name: str,
        industry: str,
        pe_sponsor: str,
        packaging: Dict[str, Any],
        client_logo_path: Optional[Path] = None
    ) -> None:
        """Create the title slide with client info and branding."""
        slide = prs.slides.add_slide(layout)
        
        # Off-white background
        self._add_slide_background(slide)
        
        # Orange accent bar at top
        accent_bar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0), Inches(0),
            self.SLIDE_WIDTH, Inches(0.12)
        )
        accent_bar.fill.solid()
        accent_bar.fill.fore_color.rgb = self.ORANGE
        accent_bar.line.fill.background()
        
        # Gray sidebar on left
        sidebar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0), Inches(0.12),
            Inches(0.4), Inches(7.38)
        )
        sidebar.fill.solid()
        sidebar.fill.fore_color.rgb = self.LIGHT_GRAY
        sidebar.line.fill.background()
        
        # Decorative corner accent - top right
        corner_accent = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(12.5), Inches(0.12),
            Inches(0.833), Inches(0.08)
        )
        corner_accent.fill.solid()
        corner_accent.fill.fore_color.rgb = self.DARK_GRAY
        corner_accent.line.fill.background()
        
        # "CASE STUDY" label - top left with orange accent
        label_bg = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0.7), Inches(0.8),
            Inches(2), Inches(0.45)
        )
        label_bg.fill.solid()
        label_bg.fill.fore_color.rgb = self.ORANGE
        label_bg.line.fill.background()
        
        label_box = slide.shapes.add_textbox(
            Inches(0.8), Inches(0.88),
            Inches(1.8), Inches(0.35)
        )
        tf = label_box.text_frame
        p = tf.paragraphs[0]
        p.text = "CASE STUDY"
        p.font.size = Pt(14)
        p.font.bold = True
        p.font.color.rgb = self.WHITE
        
        # Client name - main title (with word wrap)
        title_box = slide.shapes.add_textbox(
            Inches(0.7), Inches(2.0),
            Inches(8), Inches(1.8)
        )
        tf = title_box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = client_name
        p.font.size = Pt(48)
        p.font.bold = True
        p.font.color.rgb = self.DARK_GRAY
        
        # Industry description - subtitle (with word wrap)
        if industry:
            industry_desc = f"A Leading {industry} Provider"
        else:
            industry_desc = "Strategic Sourcing Engagement"
        
        subtitle_box = slide.shapes.add_textbox(
            Inches(0.7), Inches(3.8),
            Inches(8), Inches(0.8)
        )
        tf = subtitle_box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = industry_desc
        p.font.size = Pt(22)
        p.font.color.rgb = self.ORANGE
        
        # PE Sponsor (with word wrap for long text)
        if pe_sponsor:
            pe_box = slide.shapes.add_textbox(
                Inches(0.7), Inches(4.6),
                Inches(8), Inches(0.8)
            )
            tf = pe_box.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            # Anonymize PE sponsor name
            p.text = f"Private Equity Sponsor"
            p.font.size = Pt(14)
            p.font.color.rgb = self.MEDIUM_GRAY
        
        # Headline from case study (with word wrap)
        headline = packaging.get("headline", "")
        if headline:
            headline_box = slide.shapes.add_textbox(
                Inches(0.7), Inches(5.5),
                Inches(8), Inches(1.2)
            )
            tf = headline_box.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.text = headline
            p.font.size = Pt(16)
            p.font.italic = True
            p.font.color.rgb = self.DARK_GRAY
        
        # Client logo (if provided)
        if client_logo_path and client_logo_path.exists():
            try:
                slide.shapes.add_picture(
                    str(client_logo_path),
                    Inches(9.5), Inches(2.5),
                    width=Inches(3)
                )
            except Exception:
                pass
        
        # Footer with page number
        self._add_footer_bar(slide, page_num=1)
        
        # Treya Partners logo - bottom right (consistent position on all slides)
        self._add_treya_logo(slide, left=10.3, top=6.85, width=2.7)
    
    def _create_challenge_slide(self, prs: Presentation, layout, packaging: Dict[str, Any]) -> None:
        """Create the Challenge + Approach slide with two-column layout."""
        slide = prs.slides.add_slide(layout)
        
        # Off-white background
        self._add_slide_background(slide)
        
        # Get content
        problem = packaging.get("client_problem_anonymized") or packaging.get("client_problem_statement", "")
        approach = packaging.get("approach_summary", [])
        
        # Professional header with depth
        self._add_header_with_depth(slide, "The Challenge & Our Approach")
        
        # Footer with page number
        self._add_footer_bar(slide, page_num=2)
        
        # Corner accent
        self._add_corner_accent(slide, "bottom_left")
        
        # Left column: THE CHALLENGE
        challenge_header = slide.shapes.add_textbox(
            Inches(0.5), Inches(1.55),
            Inches(5.8), Inches(0.5)
        )
        tf = challenge_header.text_frame
        p = tf.paragraphs[0]
        p.text = "THE CHALLENGE"
        p.font.size = Pt(14)
        p.font.bold = True
        p.font.color.rgb = self.ORANGE
        
        # Orange underline
        challenge_line = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0.5), Inches(2.0),
            Inches(1.8), Inches(0.04)
        )
        challenge_line.fill.solid()
        challenge_line.fill.fore_color.rgb = self.ORANGE
        challenge_line.line.fill.background()
        
        # Challenge text (with word wrap)
        challenge_box = slide.shapes.add_textbox(
            Inches(0.5), Inches(2.25),
            Inches(5.8), Inches(4.6)
        )
        tf = challenge_box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = problem if problem else "The client faced procurement challenges requiring strategic sourcing expertise."
        p.font.size = Pt(13)
        p.font.color.rgb = self.BLACK
        p.line_spacing = 1.4
        
        # Vertical divider
        divider = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(6.5), Inches(1.5),
            Inches(0.02), Inches(5.5)
        )
        divider.fill.solid()
        divider.fill.fore_color.rgb = self.LIGHT_GRAY
        divider.line.fill.background()
        
        # Right column: OUR APPROACH
        approach_header = slide.shapes.add_textbox(
            Inches(6.9), Inches(1.55),
            Inches(5.8), Inches(0.5)
        )
        tf = approach_header.text_frame
        p = tf.paragraphs[0]
        p.text = "OUR APPROACH"
        p.font.size = Pt(14)
        p.font.bold = True
        p.font.color.rgb = self.ORANGE
        
        approach_line = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(6.9), Inches(2.0),
            Inches(1.8), Inches(0.04)
        )
        approach_line.fill.solid()
        approach_line.fill.fore_color.rgb = self.ORANGE
        approach_line.line.fill.background()
        
        # Approach bullets (with word wrap)
        approach_box = slide.shapes.add_textbox(
            Inches(6.9), Inches(2.25),
            Inches(6), Inches(4.6)
        )
        tf = approach_box.text_frame
        tf.word_wrap = True
        
        if approach:
            for i, bullet in enumerate(approach[:6]):
                if i == 0:
                    p = tf.paragraphs[0]
                else:
                    p = tf.add_paragraph()
                p.text = f"• {bullet}"
                p.font.size = Pt(12)
                p.font.color.rgb = self.BLACK
                p.line_spacing = 1.3
                p.space_after = Pt(10)
        else:
            p = tf.paragraphs[0]
            p.text = "• Strategic sourcing and category optimization"
            p.font.size = Pt(12)
            p.font.color.rgb = self.BLACK
        
        # Treya logo - bottom right (consistent position on all slides)
        self._add_treya_logo(slide, left=10.3, top=6.85, width=2.7)
    
    def _create_results_slide(self, prs: Presentation, layout, packaging: Dict[str, Any]) -> None:
        """Create the Results + Differentiators slide."""
        slide = prs.slides.add_slide(layout)
        
        # Off-white background
        self._add_slide_background(slide)
        
        # Get content
        value_blurb = packaging.get("value_delivered_blurb", "")
        top_levers = packaging.get("top_levers", [])
        unique = packaging.get("where_we_were_unique", [])
        
        # Professional header with depth
        self._add_header_with_depth(slide, "Results & What Made Us Unique")
        
        # Footer with page number
        self._add_footer_bar(slide, page_num=3)
        
        # Corner accent
        self._add_corner_accent(slide, "bottom_left")
        
        # VALUE DELIVERED section
        value_header = slide.shapes.add_textbox(
            Inches(0.5), Inches(1.55),
            Inches(12), Inches(0.5)
        )
        tf = value_header.text_frame
        p = tf.paragraphs[0]
        p.text = "VALUE DELIVERED"
        p.font.size = Pt(14)
        p.font.bold = True
        p.font.color.rgb = self.ORANGE
        
        # Orange underline
        value_line = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0.5), Inches(2.0),
            Inches(2), Inches(0.04)
        )
        value_line.fill.solid()
        value_line.fill.fore_color.rgb = self.ORANGE
        value_line.line.fill.background()
        
        # Value blurb - highlighted box
        value_bg = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE,
            Inches(0.5), Inches(2.15),
            Inches(12.3), Inches(1.0)
        )
        value_bg.fill.solid()
        value_bg.fill.fore_color.rgb = self.LIGHT_GRAY
        value_bg.line.fill.background()
        
        value_box = slide.shapes.add_textbox(
            Inches(0.7), Inches(2.25),
            Inches(11.9), Inches(0.9)
        )
        tf = value_box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = value_blurb if value_blurb else "Delivered significant cost savings and operational improvements across multiple categories."
        p.font.size = Pt(14)
        p.font.color.rgb = self.BLACK
        
        # Left column: TOP LEVERS
        levers_header = slide.shapes.add_textbox(
            Inches(0.5), Inches(3.45),
            Inches(5.8), Inches(0.5)
        )
        tf = levers_header.text_frame
        p = tf.paragraphs[0]
        p.text = "TOP LEVERS"
        p.font.size = Pt(14)
        p.font.bold = True
        p.font.color.rgb = self.ORANGE
        
        levers_line = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0.5), Inches(3.9),
            Inches(1.5), Inches(0.04)
        )
        levers_line.fill.solid()
        levers_line.fill.fore_color.rgb = self.ORANGE
        levers_line.line.fill.background()
        
        levers_box = slide.shapes.add_textbox(
            Inches(0.5), Inches(4.05),
            Inches(5.8), Inches(2.8)
        )
        tf = levers_box.text_frame
        tf.word_wrap = True
        
        if top_levers:
            for i, lever in enumerate(top_levers[:5]):
                if i == 0:
                    p = tf.paragraphs[0]
                else:
                    p = tf.add_paragraph()
                p.text = f"• {lever}"
                p.font.size = Pt(11)
                p.font.color.rgb = self.BLACK
                p.space_after = Pt(6)
        
        # Right column: WHAT MADE US UNIQUE
        unique_header = slide.shapes.add_textbox(
            Inches(6.9), Inches(3.45),
            Inches(5.8), Inches(0.5)
        )
        tf = unique_header.text_frame
        p = tf.paragraphs[0]
        p.text = "WHAT MADE US UNIQUE"
        p.font.size = Pt(14)
        p.font.bold = True
        p.font.color.rgb = self.ORANGE
        
        unique_line = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(6.9), Inches(3.9),
            Inches(2.5), Inches(0.04)
        )
        unique_line.fill.solid()
        unique_line.fill.fore_color.rgb = self.ORANGE
        unique_line.line.fill.background()
        
        unique_box = slide.shapes.add_textbox(
            Inches(6.9), Inches(4.05),
            Inches(6), Inches(2.8)
        )
        tf = unique_box.text_frame
        tf.word_wrap = True
        
        if unique:
            for i, item in enumerate(unique[:5]):
                if i == 0:
                    p = tf.paragraphs[0]
                else:
                    p = tf.add_paragraph()
                p.text = f"• {item}"
                p.font.size = Pt(11)
                p.font.color.rgb = self.BLACK
                p.space_after = Pt(6)
        
        # Treya logo - bottom right (consistent position on all slides)
        self._add_treya_logo(slide, left=10.3, top=6.85, width=2.7)
    
    def _create_categories_slide(self, prs: Presentation, layout, categories_data: Dict[str, Any]) -> None:
        """Create the Categories table slide."""
        slide = prs.slides.add_slide(layout)
        
        # Off-white background
        self._add_slide_background(slide)
        
        # Get categories list
        categories = categories_data.get("categories", [])
        
        # Professional header with depth
        self._add_header_with_depth(slide, "Category Results")
        
        # Footer with page number
        self._add_footer_bar(slide, page_num=4)
        
        # Corner accent
        self._add_corner_accent(slide, "bottom_left")
        
        if not categories:
            no_data_box = slide.shapes.add_textbox(
                Inches(0.5), Inches(2.5),
                Inches(12), Inches(1)
            )
            tf = no_data_box.text_frame
            p = tf.paragraphs[0]
            p.text = "Category details not available"
            p.font.size = Pt(16)
            p.font.color.rgb = self.MEDIUM_GRAY
            p.alignment = PP_ALIGN.CENTER
            return
        
        # Create table with 7 columns (added Vendors Before and After)
        num_rows = min(len(categories) + 1, 9)  # Header + max 8 categories (fewer rows due to more columns)
        num_cols = 7
        
        table = slide.shapes.add_table(
            num_rows, num_cols,
            Inches(0.3), Inches(1.55),
            Inches(12.7), Inches(4.5)  # Adjusted for new header
        ).table
        
        # Set column widths
        table.columns[0].width = Inches(2.0)   # Category
        table.columns[1].width = Inches(1.8)   # Vendors Before
        table.columns[2].width = Inches(1.8)   # Vendors After
        table.columns[3].width = Inches(1.3)   # Baseline
        table.columns[4].width = Inches(1.3)   # Savings
        table.columns[5].width = Inches(0.9)   # %
        table.columns[6].width = Inches(3.8)   # Key Lever
        
        # Header row styling
        headers = ["Category", "Vendors Before", "Vendors After", "Baseline", "Savings", "%", "Key Lever(s)"]
        for col_idx, header in enumerate(headers):
            cell = table.cell(0, col_idx)
            cell.text = header
            cell.fill.solid()
            cell.fill.fore_color.rgb = self.ORANGE
            
            para = cell.text_frame.paragraphs[0]
            para.font.size = Pt(11)
            para.font.bold = True
            para.font.color.rgb = self.WHITE
            para.alignment = PP_ALIGN.CENTER
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        
        # Data rows
        for row_idx, cat in enumerate(categories[:num_rows - 1]):
            label = cat.get("category_label", "Unknown")
            
            # Get vendors before
            vendors_before = cat.get("vendors_before", [])
            if isinstance(vendors_before, list):
                vendors_before_str = ", ".join(vendors_before[:2]) if vendors_before else ""
            else:
                vendors_before_str = str(vendors_before) if vendors_before else ""
            
            # Get vendors after
            vendors_after = cat.get("vendors_after", [])
            if isinstance(vendors_after, list):
                vendors_after_str = ", ".join(vendors_after[:2]) if vendors_after else ""
            else:
                vendors_after_str = str(vendors_after) if vendors_after else ""
            
            # Handle baseline spend
            baseline = cat.get("baseline_spend", {})
            if isinstance(baseline, dict):
                baseline_amt = baseline.get("amount", 0)
            else:
                baseline_amt = baseline or 0
            
            # Handle savings
            savings = cat.get("savings_annual_run_rate", {})
            if isinstance(savings, dict):
                savings_amt = savings.get("amount", 0)
            else:
                savings_amt = savings or 0
            
            savings_pct = cat.get("savings_percentage", 0) or 0
            
            # Get levers
            levers = cat.get("levers", [])
            if isinstance(levers, list):
                lever_str = ", ".join(levers[:2]) if levers else ""
            else:
                lever_str = str(levers) if levers else ""
            
            # Format amounts
            if baseline_amt >= 1000000:
                baseline_str = f"${baseline_amt/1000000:.1f}M"
            elif baseline_amt >= 1000:
                baseline_str = f"${baseline_amt/1000:.0f}K"
            else:
                baseline_str = f"${baseline_amt:,.0f}" if baseline_amt else ""
            
            if savings_amt >= 1000000:
                savings_str = f"${savings_amt/1000000:.1f}M"
            elif savings_amt >= 1000:
                savings_str = f"${savings_amt/1000:.0f}K"
            else:
                savings_str = f"${savings_amt:,.0f}" if savings_amt else ""
            
            pct_str = f"{savings_pct:.1f}%" if savings_pct else ""
            
            # Fill cells (now 7 columns)
            row_data = [label, vendors_before_str, vendors_after_str, baseline_str, savings_str, pct_str, lever_str]
            for col_idx, value in enumerate(row_data):
                cell = table.cell(row_idx + 1, col_idx)
                cell.text = str(value)
                
                para = cell.text_frame.paragraphs[0]
                para.font.size = Pt(10)  # Readable font size
                para.font.color.rgb = self.BLACK
                
                # Right-align numbers
                if col_idx in [3, 4, 5]:  # Baseline, Savings, %
                    para.alignment = PP_ALIGN.RIGHT
                else:
                    para.alignment = PP_ALIGN.LEFT
                
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                
                # Alternate row colors
                if row_idx % 2 == 0:
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = self.LIGHT_GRAY
                else:
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = self.WHITE
        
        # Treya logo - bottom right (consistent position on all slides)
        self._add_treya_logo(slide, left=10.3, top=6.85, width=2.7)
    
    def _create_charts_slide(
        self, 
        prs: Presentation, 
        layout, 
        categories_data: Dict[str, Any],
        impact_data: Dict[str, Any]
    ) -> None:
        """Create a slide with simplified table (2/3) and bar chart (1/3)."""
        try:
            import matplotlib.pyplot as plt
            import matplotlib
            matplotlib.use('Agg')  # Non-interactive backend
        except ImportError:
            return  # Skip if matplotlib not available
        
        slide = prs.slides.add_slide(layout)
        
        # Off-white background
        self._add_slide_background(slide)
        
        # Professional header with depth
        self._add_header_with_depth(slide, "Savings Analysis")
        
        # Footer with page number
        self._add_footer_bar(slide, page_num=5)
        
        # Corner accent
        self._add_corner_accent(slide, "bottom_left")
        
        categories = categories_data.get("categories", [])
        
        if not categories:
            return
        
        # Extract data for bar chart
        labels = []
        savings_pcts = []
        
        for cat in categories[:8]:  # Max 8 categories for readability
            label = cat.get("category_label", "Unknown")
            # Keep full labels - chart will handle display
            labels.append(label)
            
            # Parse savings percentage (can be float or string like "15%")
            pct_val = cat.get("savings_percentage", 0)
            if isinstance(pct_val, (int, float)):
                pct_num = float(pct_val)
            elif isinstance(pct_val, str):
                pct_num = float(pct_val.replace("%", "").replace(",", "")) if pct_val else 0
            else:
                pct_num = 0
            savings_pcts.append(pct_num)
        
        # Create simplified table (2/3 of slide - left side)
        # Columns: Category, Vendors Before, Vendors After, Baseline, Key Lever(s)
        # (removed: Savings, %)
        self._create_simplified_table(slide, categories)
        
        # Create bar chart (right side - larger)
        with tempfile.TemporaryDirectory() as tmpdir:
            bar_path = Path(tmpdir) / "bar_chart.png"
            self._create_bar_chart_compact(labels, savings_pcts, bar_path)
            
            if bar_path.exists():
                slide.shapes.add_picture(
                    str(bar_path),
                    Inches(8.5), Inches(1.5),
                    width=Inches(4.7)
                )
        
        # Treya logo - bottom right (consistent position on all slides)
        self._add_treya_logo(slide, left=10.3, top=6.85, width=2.7)
    
    def _create_simplified_table(self, slide, categories: list) -> None:
        """Create simplified categories table - adaptive font sizing, fixed table size."""
        num_categories = len(categories)
        num_rows = min(num_categories + 1, 12)  # Header + max 11 categories
        num_cols = 5  # Category, Vendors Before, Vendors After, Baseline, Key Lever
        
        # Adaptive font size based on number of categories (table size stays constant)
        if num_categories <= 5:
            data_font_size = Pt(9)
            header_font_size = Pt(10)
        elif num_categories <= 8:
            data_font_size = Pt(8)
            header_font_size = Pt(9)
        else:
            data_font_size = Pt(7)
            header_font_size = Pt(8)
        
        # Table takes 2/3 of slide width - FIXED SIZE regardless of content
        table = slide.shapes.add_table(
            num_rows, num_cols,
            Inches(0.3), Inches(1.55),
            Inches(8.3), Inches(5.0)  # Fixed height
        ).table
        
        # Set column widths
        table.columns[0].width = Inches(1.8)   # Category
        table.columns[1].width = Inches(1.5)   # Vendors Before
        table.columns[2].width = Inches(1.5)   # Vendors After
        table.columns[3].width = Inches(1.2)   # Baseline
        table.columns[4].width = Inches(2.3)   # Key Lever
        
        # Header row styling
        headers = ["Category", "Vendors Before", "Vendors After", "Baseline", "Key Lever(s)"]
        for col_idx, header in enumerate(headers):
            cell = table.cell(0, col_idx)
            cell.text = header
            cell.fill.solid()
            cell.fill.fore_color.rgb = self.ORANGE
            
            para = cell.text_frame.paragraphs[0]
            para.font.size = header_font_size
            para.font.bold = True
            para.font.color.rgb = self.WHITE
            para.alignment = PP_ALIGN.CENTER
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        
        # Data rows
        for row_idx, cat in enumerate(categories[:num_rows - 1]):
            label = cat.get("category_label", "Unknown")
            
            # Get vendors before - show full text
            vendors_before = cat.get("vendors_before", cat.get("incumbent_vendors", []))
            if isinstance(vendors_before, list) and vendors_before:
                vendors_before_str = ", ".join(str(v) for v in vendors_before[:2])
            elif vendors_before:
                vendors_before_str = str(vendors_before)
            else:
                vendors_before_str = ""
            
            # Get vendors after - show full text
            vendors_after = cat.get("vendors_after", cat.get("selected_vendor", []))
            if isinstance(vendors_after, list) and vendors_after:
                vendors_after_str = ", ".join(str(v) for v in vendors_after[:2])
            elif vendors_after:
                vendors_after_str = str(vendors_after)
            else:
                vendors_after_str = ""
            
            # Get baseline
            baseline = cat.get("baseline_spend", cat.get("baseline", ""))
            if isinstance(baseline, dict):
                baseline = f"${baseline.get('amount', 0):,.0f}"
            elif baseline:
                baseline = str(baseline)
            else:
                baseline = ""
            
            # Get key lever(s) - try multiple field names
            lever = cat.get("levers") or cat.get("key_lever") or cat.get("lever") or cat.get("primary_lever") or []
            if isinstance(lever, list) and lever:
                lever = ", ".join(str(l) for l in lever[:2])
            elif lever:
                lever = str(lever)
            else:
                lever = ""
            
            row_data = [label, vendors_before_str, vendors_after_str, baseline, lever]
            
            for col_idx, value in enumerate(row_data):
                cell = table.cell(row_idx + 1, col_idx)
                # Show empty string instead of "-" for missing data
                cell.text = value if value else ""
                
                para = cell.text_frame.paragraphs[0]
                para.font.size = data_font_size
                para.font.color.rgb = self.BLACK
                
                # Right-align baseline column
                if col_idx == 3:
                    para.alignment = PP_ALIGN.RIGHT
                else:
                    para.alignment = PP_ALIGN.LEFT
                
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                
                # Alternate row colors
                if row_idx % 2 == 0:
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = self.LIGHT_GRAY
                else:
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = self.WHITE
    
    def _create_bar_chart_compact(self, labels: list, percentages: list, output_path: Path) -> None:
        """Create an enhanced horizontal bar chart with color gradient and legend."""
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors
        import numpy as np
        
        num_categories = len(labels)
        
        # Adaptive font size based on number of categories
        if num_categories <= 4:
            label_fontsize = 10
            bar_height = 0.7
            fig_height = 5
        elif num_categories <= 6:
            label_fontsize = 9
            bar_height = 0.65
            fig_height = 5.5
        elif num_categories <= 8:
            label_fontsize = 8
            bar_height = 0.6
            fig_height = 6
        else:
            label_fontsize = 7
            bar_height = 0.55
            fig_height = 6.5
        
        # Larger figure for better visibility
        fig, ax = plt.subplots(figsize=(6.5, fig_height), facecolor='#e8e4dc')
        ax.set_facecolor('#e8e4dc')
        
        # Sort by percentage (highest first) for better visual
        sorted_data = sorted(zip(labels, percentages), key=lambda x: x[1], reverse=True)
        labels_sorted = [x[0] for x in sorted_data]
        pcts_sorted = [x[1] for x in sorted_data]
        
        # Reverse for matplotlib (so highest is at top)
        labels_r = list(reversed(labels_sorted))
        pcts_r = list(reversed(pcts_sorted))
        
        y_pos = np.arange(len(labels_r))
        
        # Color gradient based on savings percentage (darker = higher savings)
        max_pct = max(pcts_r) if pcts_r else 1
        colors = []
        for pct in pcts_r:
            # Gradient from light orange to dark orange based on percentage
            intensity = pct / max_pct if max_pct > 0 else 0.5
            # Interpolate between light orange (#f5a54d) and dark orange (#c45500)
            r = int(0xf5 - (0xf5 - 0xc4) * intensity)
            g = int(0xa5 - (0xa5 - 0x55) * intensity)
            b = int(0x4d - (0x4d - 0x00) * intensity)
            colors.append(f'#{r:02x}{g:02x}{b:02x}')
        
        # Create horizontal bars with gradient colors
        bars = ax.barh(y_pos, pcts_r, color=colors, edgecolor='white', height=bar_height, linewidth=1.5)
        
        # Add value labels on bars
        for bar, pct in zip(bars, pcts_r):
            width = bar.get_width()
            # Place label inside bar if bar is wide enough, otherwise outside
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
        ax.set_title('Savings by Category', fontsize=13, fontweight='bold', color='#3d3d3d', pad=12)
        
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
        
        # Add color legend (key)
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor='#c45500', edgecolor='white', label='High Savings'),
            Patch(facecolor='#e86c00', edgecolor='white', label='Medium Savings'),
            Patch(facecolor='#f5a54d', edgecolor='white', label='Lower Savings'),
        ]
        ax.legend(handles=legend_elements, loc='lower right', fontsize=8, 
                  framealpha=0.9, facecolor='#e8e4dc', edgecolor='#6c757d')
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, facecolor='#e8e4dc', bbox_inches='tight')
        plt.close()
    
    def _parse_currency(self, value: str) -> float:
        """Parse a currency string to float."""
        if not value:
            return 0.0
        # Remove currency symbols and commas
        clean = value.replace("$", "").replace(",", "").replace(" ", "")
        # Handle K/M suffixes
        multiplier = 1
        if clean.endswith("K") or clean.endswith("k"):
            multiplier = 1000
            clean = clean[:-1]
        elif clean.endswith("M") or clean.endswith("m"):
            multiplier = 1000000
            clean = clean[:-1]
        try:
            return float(clean) * multiplier
        except ValueError:
            return 0.0
    
    def _create_pie_chart(self, labels: list, values: list, output_path: Path) -> None:
        """Create a pie chart showing savings distribution."""
        import matplotlib.pyplot as plt
        
        # Filter out zero values
        filtered_data = [(l, v) for l, v in zip(labels, values) if v > 0]
        if not filtered_data:
            return
        
        labels_f, values_f = zip(*filtered_data)
        
        fig, ax = plt.subplots(figsize=(6.5, 5), facecolor='#e8e4dc')
        ax.set_facecolor('#e8e4dc')
        
        # Create pie chart
        colors = CHART_COLORS[:len(values_f)]
        wedges, texts, autotexts = ax.pie(
            values_f,
            labels=None,
            autopct='%1.0f%%',
            colors=colors,
            startangle=90,
            pctdistance=0.75,
            explode=[0.02] * len(values_f)
        )
        
        # Style the percentage labels
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontsize(9)
            autotext.set_fontweight('bold')
        
        # Add legend
        ax.legend(
            wedges, labels_f,
            title="Categories",
            loc="center left",
            bbox_to_anchor=(1, 0, 0.5, 1),
            fontsize=8
        )
        
        ax.set_title("Savings by Category", fontsize=14, fontweight='bold', color='#3d3d3d', pad=10)
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, facecolor='#e8e4dc', bbox_inches='tight')
        plt.close()
    
    def _create_bar_chart(self, labels: list, percentages: list, output_path: Path) -> None:
        """Create a horizontal bar chart showing savings percentages."""
        import matplotlib.pyplot as plt
        import numpy as np
        
        fig, ax = plt.subplots(figsize=(6.5, 5), facecolor='#e8e4dc')
        ax.set_facecolor('#e8e4dc')
        
        # Reverse for top-to-bottom display
        labels_r = list(reversed(labels))
        pcts_r = list(reversed(percentages))
        
        y_pos = np.arange(len(labels_r))
        
        # Create horizontal bars
        bars = ax.barh(y_pos, pcts_r, color=CHART_ORANGE, edgecolor='white', height=0.6)
        
        # Add value labels on bars
        for bar, pct in zip(bars, pcts_r):
            width = bar.get_width()
            ax.text(
                width + 1, bar.get_y() + bar.get_height()/2,
                f'{pct:.0f}%',
                va='center', ha='left',
                fontsize=9, fontweight='bold', color='#3d3d3d'
            )
        
        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels_r, fontsize=9)
        ax.set_xlabel('Savings %', fontsize=10, color='#3d3d3d')
        ax.set_title('Savings Percentage by Category', fontsize=14, fontweight='bold', color='#3d3d3d', pad=10)
        
        # Style the chart
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_color('#6c757d')
        ax.spines['left'].set_color('#6c757d')
        ax.tick_params(colors='#3d3d3d')
        
        # Set x-axis limit to give room for labels
        max_val = max(pcts_r) if pcts_r else 50
        ax.set_xlim(0, max_val * 1.3)
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, facecolor='#e8e4dc', bbox_inches='tight')
        plt.close()
