"""
Base classes for content extraction.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class ExtractionResult:
    """Result of extracting content from a file."""
    file_path: str
    file_type: str
    success: bool
    text_content: str = ""
    metadata: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None
    page_count: Optional[int] = None
    
    def truncated(self, max_chars: int = 10000) -> str:
        """Get truncated content for LLM context."""
        if len(self.text_content) <= max_chars:
            return self.text_content
        return self.text_content[:max_chars] + f"\n\n[... truncated, {len(self.text_content) - max_chars} more characters ...]"


class ContentExtractor(ABC):
    """Abstract base class for content extractors."""
    
    @property
    @abstractmethod
    def supported_extensions(self) -> List[str]:
        """Return list of supported file extensions (lowercase, with dot)."""
        pass
    
    @abstractmethod
    def extract(self, file_path: Path) -> ExtractionResult:
        """
        Extract text content from a file.
        
        Args:
            file_path: Path to the file
            
        Returns:
            ExtractionResult with extracted content or error
        """
        pass
    
    def can_handle(self, file_path: Path) -> bool:
        """Check if this extractor can handle the given file."""
        return file_path.suffix.lower() in self.supported_extensions


def get_extractor_for_file(file_path: Path) -> Optional[ContentExtractor]:
    """
    Get the appropriate extractor for a file.
    
    Returns None if no extractor is available for this file type.
    """
    from src.extractors.pdf import PDFExtractor
    from src.extractors.pptx import PPTXExtractor
    from src.extractors.docx import DOCXExtractor
    from src.extractors.xlsx import XLSXExtractor
    
    extractors: List[ContentExtractor] = [
        PDFExtractor(),
        PPTXExtractor(),
        DOCXExtractor(),
        XLSXExtractor(),
    ]
    
    for extractor in extractors:
        if extractor.can_handle(file_path):
            return extractor
    
    return None


def extract_file_content(file_path: Path, max_chars: int = 15000) -> ExtractionResult:
    """
    Convenience function to extract content from any supported file.
    
    Args:
        file_path: Path to the file
        max_chars: Maximum characters to include (for truncation)
        
    Returns:
        ExtractionResult (may be truncated)
    """
    extractor = get_extractor_for_file(file_path)
    
    if extractor is None:
        # Try to read as plain text for .txt, .csv, .json, etc.
        if file_path.suffix.lower() in [".txt", ".csv", ".json", ".md", ".yaml", ".yml"]:
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
                if len(text) > max_chars:
                    text = text[:max_chars] + f"\n\n[... truncated ...]"
                return ExtractionResult(
                    file_path=str(file_path),
                    file_type=file_path.suffix.lower(),
                    success=True,
                    text_content=text,
                )
            except Exception as e:
                return ExtractionResult(
                    file_path=str(file_path),
                    file_type=file_path.suffix.lower(),
                    success=False,
                    error=str(e),
                )
        
        return ExtractionResult(
            file_path=str(file_path),
            file_type=file_path.suffix.lower(),
            success=False,
            error=f"No extractor available for {file_path.suffix}",
        )
    
    result = extractor.extract(file_path)
    
    # Truncate if needed
    if result.success and len(result.text_content) > max_chars:
        result.text_content = result.truncated(max_chars)
    
    return result
