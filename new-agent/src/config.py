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
POWERPOINTS_DIR = PROJECT_ROOT / "powerpoints"


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
MAX_TOKENS = 50000  # Max output tokens (high to prevent truncation with o3 reasoning)
TEMPERATURE = 0.7  # Balanced creativity/consistency (not used by o3)


# ============================================================================
# Azure SQL Database Configuration
# ============================================================================
# Enable/disable Azure database integration
AZURE_SQL_ENABLED = os.environ.get("AZURE_SQL_ENABLED", "false").lower() == "true"

# Azure SQL connection parameters
# Option 1: Full connection string (preferred)
AZURE_SQL_CONNECTION_STRING = os.environ.get("AZURE_SQL_CONNECTION_STRING", "")

# Option 2: Individual parameters (used if connection string is empty)
AZURE_SQL_SERVER = os.environ.get("AZURE_SQL_SERVER", "")  # e.g., "myserver.database.windows.net"
AZURE_SQL_DATABASE = os.environ.get("AZURE_SQL_DATABASE", "")  # e.g., "treya_case_studies"
AZURE_SQL_USERNAME = os.environ.get("AZURE_SQL_USERNAME", "")
AZURE_SQL_PASSWORD = os.environ.get("AZURE_SQL_PASSWORD", "")

# Table name for case study extractions
AZURE_SQL_TABLE = os.environ.get("AZURE_SQL_TABLE", "case_study_extractions")


# ============================================================================
# SharePoint / Microsoft Graph API Configuration
# ============================================================================
# Azure AD App Registration for Graph API access
# Required: Register an app at https://portal.azure.com → Azure Active Directory → App registrations
# Add delegated permissions: Files.Read.All, Sites.Read.All
# Enable "Allow public client flows" for device code auth
SHAREPOINT_CLIENT_ID = os.environ.get("SHAREPOINT_CLIENT_ID", "")
SHAREPOINT_TENANT_ID = os.environ.get("SHAREPOINT_TENANT_ID", "treyapartners.onmicrosoft.com")

# SharePoint site details (parsed from your SharePoint URL)
SHAREPOINT_HOSTNAME = "treyapartners.sharepoint.com"
SHAREPOINT_SITE_PATH = "/sites/Projects"
SHAREPOINT_LIBRARY_NAME = "Projects"  # The document library name


def validate_config() -> list[str]:
    """Validate configuration and return list of errors."""
    errors = []
    
    if not OPENAI_API_KEY:
        errors.append("OPENAI_API_KEY environment variable is not set")
    elif not OPENAI_API_KEY.startswith("sk-"):
        errors.append("OPENAI_API_KEY should start with 'sk-'")
    
    return errors


def validate_azure_config() -> list[str]:
    """Validate Azure SQL configuration and return list of errors."""
    errors = []
    
    if not AZURE_SQL_ENABLED:
        return errors  # Azure is disabled, no validation needed
    
    # Check for connection string or individual params
    if AZURE_SQL_CONNECTION_STRING:
        # Connection string provided, good to go
        return errors
    
    # Check individual parameters
    if not AZURE_SQL_SERVER:
        errors.append("AZURE_SQL_SERVER environment variable is not set")
    if not AZURE_SQL_DATABASE:
        errors.append("AZURE_SQL_DATABASE environment variable is not set")
    if not AZURE_SQL_USERNAME:
        errors.append("AZURE_SQL_USERNAME environment variable is not set")
    if not AZURE_SQL_PASSWORD:
        errors.append("AZURE_SQL_PASSWORD environment variable is not set")
    
    return errors


def get_azure_connection_string() -> str:
    """Get the Azure SQL connection string (either direct or built from params)."""
    if AZURE_SQL_CONNECTION_STRING:
        return AZURE_SQL_CONNECTION_STRING
    
    # Build connection string from individual parameters
    # Using ODBC Driver 18 for SQL Server (latest)
    # tcp: prefix and port 1433 help with Azure SQL connectivity
    return (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER=tcp:{AZURE_SQL_SERVER},1433;"
        f"DATABASE={AZURE_SQL_DATABASE};"
        f"UID={AZURE_SQL_USERNAME};"
        f"PWD={AZURE_SQL_PASSWORD};"
        f"Encrypt=yes;"
        f"TrustServerCertificate=no;"
        f"Connection Timeout=60;"
        f"LoginTimeout=60;"
    )


def validate_sharepoint_config() -> list[str]:
    """Validate SharePoint configuration and return list of errors."""
    errors = []
    if not SHAREPOINT_CLIENT_ID:
        errors.append(
            "SHAREPOINT_CLIENT_ID environment variable is not set. "
            "Register an app at https://portal.azure.com → Azure AD → App registrations"
        )
    return errors


def ensure_directories() -> None:
    """Create required directories if they don't exist."""
    INPUTS_DIR.mkdir(exist_ok=True)
    OUTPUTS_DIR.mkdir(exist_ok=True)
