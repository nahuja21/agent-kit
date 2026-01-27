"""LLM client module."""

# Legacy client (backwards compatible)
from .client import OpenAIClient, LLMResponse

# Enhanced client with structured output and debug logging
from .enhanced_client import (
    EnhancedOpenAIClient,
    LLMResponse as EnhancedLLMResponse,
    create_client,
)

__all__ = [
    # Legacy
    "OpenAIClient",
    "LLMResponse",
    # Enhanced
    "EnhancedOpenAIClient",
    "EnhancedLLMResponse",
    "create_client",
]
