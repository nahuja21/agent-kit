"""
PowerPoint generation module.

Generates styled case study presentations from extracted data.
Includes automatic client logo fetching from the web.
"""

from src.pptx.generator import CaseStudyPPTXGenerator, CaseStudyPPTXGeneratorV2
from src.pptx.logo_fetcher import LogoFetcher

__all__ = ["CaseStudyPPTXGenerator", "CaseStudyPPTXGeneratorV2", "LogoFetcher"]
