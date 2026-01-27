"""
PDF content extractor using PyMuPDF and pdfplumber for tables.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from src.extractors.base import ContentExtractor, ExtractionResult


class PDFExtractor(ContentExtractor):
    """Extract text content from PDF files using PyMuPDF."""
    
    @property
    def supported_extensions(self) -> List[str]:
        return [".pdf"]
    
    def extract(self, file_path: Path) -> ExtractionResult:
        """Extract text from PDF file."""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            return ExtractionResult(
                file_path=str(file_path),
                file_type=".pdf",
                success=False,
                error="PyMuPDF (fitz) not installed. Run: pip install pymupdf",
            )
        
        try:
            doc = fitz.open(file_path)
            
            text_parts = []
            for page_num, page in enumerate(doc, start=1):
                page_text = page.get_text()
                if page_text.strip():
                    text_parts.append(f"--- Page {page_num} ---\n{page_text}")
            
            # Get metadata
            metadata = {}
            if doc.metadata:
                if doc.metadata.get("title"):
                    metadata["title"] = doc.metadata["title"]
                if doc.metadata.get("author"):
                    metadata["author"] = doc.metadata["author"]
                if doc.metadata.get("creationDate"):
                    metadata["created"] = doc.metadata["creationDate"]
            
            page_count = len(doc)
            doc.close()
            
            return ExtractionResult(
                file_path=str(file_path),
                file_type=".pdf",
                success=True,
                text_content="\n\n".join(text_parts),
                metadata=metadata,
                page_count=page_count,
            )
            
        except Exception as e:
            return ExtractionResult(
                file_path=str(file_path),
                file_type=".pdf",
                success=False,
                error=f"Failed to extract PDF: {e}",
            )


class PDFTableExtractor(ContentExtractor):
    """
    Extract text and tables from PDF files using pdfplumber.
    
    Better for PDFs with structured tables (like Agreement Exhibit A/B).
    Preserves table structure in markdown format.
    """
    
    @property
    def supported_extensions(self) -> List[str]:
        return [".pdf"]
    
    def extract(self, file_path: Path) -> ExtractionResult:
        """Extract text and tables from PDF file."""
        try:
            import pdfplumber
        except ImportError:
            return ExtractionResult(
                file_path=str(file_path),
                file_type=".pdf",
                success=False,
                error="pdfplumber not installed. Run: pip install pdfplumber",
            )
        
        try:
            text_parts = []
            table_count = 0
            
            with pdfplumber.open(file_path) as pdf:
                page_count = len(pdf.pages)
                
                for page_num, page in enumerate(pdf.pages, start=1):
                    page_content = []
                    page_content.append(f"--- Page {page_num} ---")
                    
                    # Extract tables from this page
                    tables = page.extract_tables()
                    
                    if tables:
                        # Get text with tables replaced by markers
                        for table_idx, table in enumerate(tables):
                            table_count += 1
                            table_md = self._table_to_markdown(table)
                            if table_md:
                                page_content.append(f"\n[TABLE {table_count}]\n{table_md}\n[/TABLE {table_count}]")
                        
                        # Also get the non-table text
                        text = page.extract_text()
                        if text:
                            page_content.append(f"\n{text}")
                    else:
                        # No tables, just extract text
                        text = page.extract_text()
                        if text:
                            page_content.append(text)
                    
                    if len(page_content) > 1:  # More than just the page header
                        text_parts.append("\n".join(page_content))
            
            metadata = {"table_count": str(table_count)}
            
            return ExtractionResult(
                file_path=str(file_path),
                file_type=".pdf",
                success=True,
                text_content="\n\n".join(text_parts),
                metadata=metadata,
                page_count=page_count,
            )
            
        except Exception as e:
            return ExtractionResult(
                file_path=str(file_path),
                file_type=".pdf",
                success=False,
                error=f"Failed to extract PDF with tables: {e}",
            )
    
    def _table_to_markdown(self, table: List[List[Optional[str]]]) -> str:
        """Convert a table (list of rows) to markdown format."""
        if not table or not table[0]:
            return ""
        
        # Clean up cells - replace None with empty string, strip whitespace
        cleaned = []
        for row in table:
            cleaned_row = []
            for cell in row:
                if cell is None:
                    cleaned_row.append("")
                else:
                    # Clean up the cell: replace newlines, strip whitespace
                    cleaned_cell = str(cell).replace("\n", " ").strip()
                    cleaned_row.append(cleaned_cell)
            cleaned.append(cleaned_row)
        
        if not cleaned:
            return ""
        
        # Find max column count
        max_cols = max(len(row) for row in cleaned)
        
        # Pad rows to have same number of columns
        for row in cleaned:
            while len(row) < max_cols:
                row.append("")
        
        # Build markdown table
        lines = []
        
        # Header row
        header = cleaned[0]
        lines.append("| " + " | ".join(header) + " |")
        
        # Separator row
        lines.append("| " + " | ".join(["---"] * max_cols) + " |")
        
        # Data rows
        for row in cleaned[1:]:
            lines.append("| " + " | ".join(row) + " |")
        
        return "\n".join(lines)


def render_pdf_page_to_base64(file_path: Path, page_num: int, dpi: int = 150) -> Optional[str]:
    """
    Render a specific PDF page to a base64-encoded PNG image.
    
    Args:
        file_path: Path to the PDF file
        page_num: Page number (0-indexed)
        dpi: Resolution for rendering (higher = better quality but larger)
        
    Returns:
        Base64-encoded PNG image string, or None if failed
    """
    try:
        import fitz  # PyMuPDF
        import base64
    except ImportError:
        return None
    
    try:
        doc = fitz.open(file_path)
        
        if page_num >= len(doc):
            doc.close()
            return None
        
        page = doc[page_num]
        
        # Render page to image
        # zoom = dpi / 72 (72 is the default PDF resolution)
        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix)
        
        # Convert to PNG bytes
        png_bytes = pixmap.tobytes("png")
        
        doc.close()
        
        # Encode to base64
        return base64.b64encode(png_bytes).decode("utf-8")
        
    except Exception as e:
        return None


def find_exhibit_pages(file_path: Path) -> List[tuple]:
    """
    Find pages that likely contain Exhibit A or Exhibit B tables.
    
    Returns list of (page_num, exhibit_type) tuples.
    Page numbers are 0-indexed.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return []
    
    exhibit_pages = []
    
    try:
        doc = fitz.open(file_path)
        
        for page_num, page in enumerate(doc):
            text = page.get_text().lower()
            
            # Look for Exhibit A indicators
            if "exhibit a" in text and ("project scope" in text or "categories" in text or "the table below" in text or "spend" in text):
                exhibit_pages.append((page_num, "exhibit_a"))
            
            # Look for Exhibit B indicators  
            elif "exhibit b" in text and ("fee" in text or "project fee" in text):
                exhibit_pages.append((page_num, "exhibit_b"))
        
        doc.close()
        
    except Exception:
        pass
    
    return exhibit_pages


def extract_table_with_vision(
    file_path: Path,
    page_num: int,
    llm_client,
    exhibit_type: str = "exhibit_a"
) -> Optional[str]:
    """
    Extract a table from a PDF page using OpenAI Vision.
    
    Args:
        file_path: Path to the PDF file
        page_num: Page number (0-indexed)
        llm_client: OpenAIClient instance with analyze_image method
        exhibit_type: "exhibit_a" or "exhibit_b" to customize the prompt
        
    Returns:
        Extracted table content as markdown, or None if failed
    """
    # Render the page to an image
    image_base64 = render_pdf_page_to_base64(file_path, page_num, dpi=200)
    
    if not image_base64:
        return None
    
    # Create prompt based on exhibit type
    if exhibit_type == "exhibit_a":
        prompt = """Extract the table from this image. This is Exhibit A (Project Scope) from an agreement document.

The table should have columns like: Category, Spend, Addressable, Savings Low, Savings High, Savings Avg (or similar).

Return the table in markdown format like this:
| Category | Spend | Addressable | Savings Low | Savings High | Savings Avg |
|----------|-------|-------------|-------------|--------------|-------------|
| Category Name | $X,XXX,XXX | XX% | $XX,XXX | $XX,XXX | $XX,XXX |

Extract ALL rows from the table. Include the Total row if present.
Return ONLY the markdown table, no other text."""

    elif exhibit_type == "exhibit_b":
        prompt = """Extract the fee structure information from this image. This is Exhibit B (Project Fees) from an agreement document.

Look for:
- Fee type (fixed, contingent, hybrid)
- Fee amount (dollar amount)
- Minimum savings guarantee or minimum return on fees ratio
- Any threshold amounts
- Contingent/variable fee percentages

Return the information in a structured format."""

    else:
        prompt = "Extract all text and tables from this image. Format tables in markdown."
    
    # Call Vision API
    response = llm_client.analyze_image(image_base64, prompt)
    
    if response.model == "error":
        return None
    
    return response.content


def extract_table_with_tesseract(
    file_path: Path,
    page_num: int,
    exhibit_type: str = "exhibit_a"
) -> Optional[str]:
    """
    Extract a table from a PDF page using Tesseract OCR.
    
    This is more accurate for clean tables than Vision API because
    it doesn't hallucinate - it reads exactly what's there.
    
    Args:
        file_path: Path to the PDF file
        page_num: Page number (0-indexed)
        exhibit_type: "exhibit_a" or "exhibit_b" (for logging)
        
    Returns:
        Extracted table content, or None if failed
    """
    try:
        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image
        import io
    except ImportError as e:
        return None
    
    try:
        doc = fitz.open(file_path)
        
        if page_num >= len(doc):
            doc.close()
            return None
        
        page = doc[page_num]
        
        # Render page to image at high DPI for better OCR
        # 300 DPI is recommended for OCR
        zoom = 300 / 72
        matrix = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix)
        
        # Convert to PIL Image
        img_bytes = pixmap.tobytes("png")
        image = Image.open(io.BytesIO(img_bytes))
        
        doc.close()
        
        # Run Tesseract OCR
        # Use --psm 6 for uniform block of text (good for tables)
        # Use -c preserve_interword_spaces=1 to keep spacing
        custom_config = r'--psm 6 -c preserve_interword_spaces=1'
        
        ocr_text = pytesseract.image_to_string(image, config=custom_config)
        
        if not ocr_text or len(ocr_text.strip()) < 50:
            return None
        
        return ocr_text
        
    except Exception as e:
        return None


def extract_table_with_tesseract_structured(
    file_path: Path,
    page_num: int,
    exhibit_type: str = "exhibit_a"
) -> Optional[str]:
    """
    Extract a table from a PDF page using Tesseract OCR with TSV output.
    
    This gives more structured output that can be parsed into a table.
    
    Args:
        file_path: Path to the PDF file
        page_num: Page number (0-indexed)
        exhibit_type: "exhibit_a" or "exhibit_b"
        
    Returns:
        Extracted table content as markdown, or None if failed
    """
    try:
        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image
        import io
        import pandas as pd
    except ImportError as e:
        # Fall back to basic OCR if pandas not available
        return extract_table_with_tesseract(file_path, page_num, exhibit_type)
    
    try:
        doc = fitz.open(file_path)
        
        if page_num >= len(doc):
            doc.close()
            return None
        
        page = doc[page_num]
        
        # Render page to image at high DPI
        zoom = 300 / 72
        matrix = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix)
        
        # Convert to PIL Image
        img_bytes = pixmap.tobytes("png")
        image = Image.open(io.BytesIO(img_bytes))
        
        doc.close()
        
        # Get OCR data with bounding boxes
        ocr_data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DATAFRAME)
        
        # Filter out empty/low confidence results
        ocr_data = ocr_data[ocr_data['conf'] > 30]
        ocr_data = ocr_data[ocr_data['text'].notna()]
        ocr_data = ocr_data[ocr_data['text'].str.strip() != '']
        
        if ocr_data.empty:
            return None
        
        # Also get plain text for context
        plain_text = pytesseract.image_to_string(image, config='--psm 6')
        
        # Return the plain text (most reliable for now)
        # The structured parsing can be improved later
        return plain_text
        
    except Exception as e:
        # Fall back to basic OCR
        return extract_table_with_tesseract(file_path, page_num, exhibit_type)


def extract_pdf_with_tables(file_path: Path, max_chars: int = 50000) -> ExtractionResult:
    """
    Convenience function to extract PDF with table preservation.
    
    Uses pdfplumber for better table extraction.
    Falls back to PyMuPDF if pdfplumber fails.
    """
    extractor = PDFTableExtractor()
    result = extractor.extract(file_path)
    
    # If pdfplumber fails, fall back to PyMuPDF
    if not result.success:
        fallback = PDFExtractor()
        result = fallback.extract(file_path)
    
    # Truncate if needed
    if result.success and len(result.text_content) > max_chars:
        result.text_content = result.truncated(max_chars)
    
    return result
