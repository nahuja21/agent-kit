"""Configuration via environment variables."""

import os
from pathlib import Path


# ============================================================================
# API Configuration
# ============================================================================
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Model Selection
# Options: "gpt-4o", "gpt-4.5-preview", "o1", "o3", "o3-mini"
MODEL = "o3"  # Using o3 for better reasoning and accuracy

# Reasoning effort for o3 models (low, medium, high)
REASONING_EFFORT = "medium"


# ============================================================================
# Path Configuration
# ============================================================================
PROJECT_ROOT = Path(__file__).parent.parent
INPUTS_DIR = PROJECT_ROOT / "inputs"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"


# ============================================================================
# Scanner Configuration
# ============================================================================
# File extensions to recognize (comprehensive list)
RECOGNIZED_EXTENSIONS = {
    # Documents
    ".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt",
    # Presentations
    ".ppt", ".pptx", ".odp",
    # Spreadsheets
    ".xls", ".xlsx", ".csv", ".ods",
    # Images (for future OCR)
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp",
    # Data formats
    ".json", ".xml", ".yaml", ".yml",
    # Email
    ".eml", ".msg",
    # Archives (to note, not extract)
    ".zip", ".rar", ".7z",
    # Other
    ".html", ".htm", ".md",
}

# Folders to ignore during scanning
IGNORED_FOLDERS = {
    "Archive",  # Per user requirement - old files that confuse LLM
    "__pycache__",
    ".git",
    ".DS_Store",
    "node_modules",
}


# ============================================================================
# LLM Configuration
# ============================================================================
MAX_TOKENS = 16000  # Max output tokens (increased for o3)
TEMPERATURE = 0.7  # Balanced creativity/consistency (not used by o3)


# ============================================================================
# Feature Flags
# ============================================================================
# Multi-phase project detection and extraction
# When True: Detects Phase 1/Phase 2 folders and extracts separately
# When False: Treats everything as single project (original behavior)
ENABLE_MULTI_PHASE = False  # Set to True to enable multi-phase extraction


def validate_config() -> list[str]:
    """Validate configuration and return list of errors."""
    errors = []
    
    if not OPENAI_API_KEY:
        errors.append("OPENAI_API_KEY environment variable is not set")
    elif not OPENAI_API_KEY.startswith("sk-"):
        errors.append("OPENAI_API_KEY should start with 'sk-'")
    
    return errors


def ensure_directories() -> None:
    """Create required directories if they don't exist."""
    INPUTS_DIR.mkdir(exist_ok=True)
    OUTPUTS_DIR.mkdir(exist_ok=True)
