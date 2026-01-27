"""Prompts module."""

# Legacy loader (backwards compatible)
from .loader import (
    load_prompt,
    render_template,
    get_prompt as legacy_get_prompt,
    get_file_selection_prompt as legacy_get_file_selection_prompt,
    get_agreement_extraction_prompt as legacy_get_agreement_extraction_prompt,
    get_category_extraction_prompt as legacy_get_category_extraction_prompt,
    get_impact_extraction_prompt as legacy_get_impact_extraction_prompt,
    get_anchor_detection_prompt as legacy_get_anchor_detection_prompt,
)

# Enhanced loader with parameter validation and caching
from .enhanced_loader import (
    EnhancedPromptLoader,
    PromptConfig,
    PromptParameter,
    get_prompt_loader,
    get_prompt,
    get_anchor_detection_prompt,
    get_file_selection_prompt,
    get_agreement_extraction_prompt,
    get_category_extraction_prompt,
    get_impact_extraction_prompt,
)

# Context builder (legacy)
from .context import ContextBuilder

__all__ = [
    # Legacy
    "load_prompt",
    "render_template",
    "legacy_get_prompt",
    "ContextBuilder",
    # Enhanced
    "EnhancedPromptLoader",
    "PromptConfig",
    "PromptParameter",
    "get_prompt_loader",
    "get_prompt",
    "get_anchor_detection_prompt",
    "get_file_selection_prompt",
    "get_agreement_extraction_prompt",
    "get_category_extraction_prompt",
    "get_impact_extraction_prompt",
]
