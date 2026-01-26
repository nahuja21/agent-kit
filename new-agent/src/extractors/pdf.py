"""
PDF content extractor using PyMuPDF.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

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
