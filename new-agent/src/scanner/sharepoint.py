"""
SharePoint Scanner using Microsoft Graph API.

Authenticates via MSAL device code flow and lists files from a
SharePoint document library. Designed to produce the same ScanResult
structure as the local DirectoryScanner so the rest of the pipeline
can consume it transparently.

SETUP:
1. Register an app at https://portal.azure.com → Azure AD → App registrations
2. Under "Authentication", enable "Allow public client flows" (for device code)
3. Under "API Permissions", add Microsoft Graph → Delegated:
     - Files.Read.All
     - Sites.Read.All
4. Set env var: SHAREPOINT_CLIENT_ID=<your-app-client-id>
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import msal
import requests

from src.config import (
    SHAREPOINT_CLIENT_ID,
    SHAREPOINT_TENANT_ID,
    SHAREPOINT_HOSTNAME,
    SHAREPOINT_SITE_PATH,
    SHAREPOINT_LIBRARY_NAME,
)

# Microsoft Graph API base
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Scopes required for reading SharePoint files
SCOPES = ["Files.Read.All", "Sites.Read.All"]


@dataclass
class SharePointItem:
    """A file or folder from SharePoint."""
    name: str
    item_id: str
    is_folder: bool
    size_bytes: int = 0
    modified_date: Optional[datetime] = None
    web_url: Optional[str] = None
    download_url: Optional[str] = None
    # For folders: child count
    child_count: int = 0
    # For files: mime type
    mime_type: Optional[str] = None


@dataclass
class SharePointListResult:
    """Result of listing items from a SharePoint drive."""
    site_name: str
    library_name: str
    drive_id: str
    items: List[SharePointItem] = field(default_factory=list)
    total_count: int = 0


class SharePointClient:
    """
    Client for accessing SharePoint files via Microsoft Graph API.
    
    Uses MSAL device code flow for authentication (user signs in via browser).
    Caches tokens so subsequent calls don't require re-authentication.
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        hostname: Optional[str] = None,
        site_path: Optional[str] = None,
        library_name: Optional[str] = None,
    ):
        self.client_id = client_id or SHAREPOINT_CLIENT_ID
        self.tenant_id = tenant_id or SHAREPOINT_TENANT_ID
        self.hostname = hostname or SHAREPOINT_HOSTNAME
        self.site_path = site_path or SHAREPOINT_SITE_PATH
        self.library_name = library_name or SHAREPOINT_LIBRARY_NAME

        # MSAL public client app (for device code flow)
        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        self._msal_app = msal.PublicClientApplication(
            self.client_id,
            authority=authority,
        )
        self._access_token: Optional[str] = None

        # Cached IDs
        self._site_id: Optional[str] = None
        self._drive_id: Optional[str] = None

    # =========================================================================
    # Authentication
    # =========================================================================
    def authenticate(self, device_code_callback=None) -> str:
        """
        Authenticate using device code flow.
        
        Args:
            device_code_callback: Optional callback that receives the device code
                message to display. If None, prints to stdout.
        
        Returns:
            Access token string.
        
        Raises:
            RuntimeError: If authentication fails.
        """
        # Try to get token from cache first (silent auth)
        accounts = self._msal_app.get_accounts()
        if accounts:
            result = self._msal_app.acquire_token_silent(SCOPES, account=accounts[0])
            if result and "access_token" in result:
                self._access_token = result["access_token"]
                return self._access_token

        # No cached token — start device code flow
        flow = self._msal_app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            error = flow.get("error_description", flow.get("error", "Unknown error"))
            raise RuntimeError(f"Failed to start device code flow: {error}")

        # Show the device code message to the user
        message = flow.get("message", "")
        if device_code_callback:
            device_code_callback(message)
        else:
            print(message)

        # Block until user completes auth in browser
        result = self._msal_app.acquire_token_by_device_flow(flow)

        if "access_token" not in result:
            error = result.get("error_description", result.get("error", "Unknown error"))
            raise RuntimeError(f"Authentication failed: {error}")

        self._access_token = result["access_token"]
        return self._access_token

    def _headers(self) -> Dict[str, str]:
        """Get authorization headers."""
        if not self._access_token:
            raise RuntimeError("Not authenticated. Call authenticate() first.")
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    # =========================================================================
    # Graph API Helpers
    # =========================================================================
    def _graph_get(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make a GET request to Microsoft Graph API."""
        url = f"{GRAPH_BASE}{endpoint}"
        resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
        
        if resp.status_code == 401:
            # Token expired — clear and re-raise
            self._access_token = None
            raise RuntimeError("Access token expired. Please re-authenticate.")
        
        if resp.status_code != 200:
            raise RuntimeError(
                f"Graph API error {resp.status_code}: {resp.text[:500]}"
            )
        
        return resp.json()

    # =========================================================================
    # Site & Drive Resolution
    # =========================================================================
    def get_site_id(self) -> str:
        """Resolve the SharePoint site ID from hostname + site path."""
        if self._site_id:
            return self._site_id

        # GET /sites/{hostname}:{site_path}
        endpoint = f"/sites/{self.hostname}:{self.site_path}"
        data = self._graph_get(endpoint)
        self._site_id = data["id"]
        return self._site_id

    def get_drive_id(self) -> str:
        """Find the drive ID for the target document library."""
        if self._drive_id:
            return self._drive_id

        site_id = self.get_site_id()
        endpoint = f"/sites/{site_id}/drives"
        data = self._graph_get(endpoint)

        # Find the drive matching our library name
        for drive in data.get("value", []):
            if drive.get("name", "").lower() == self.library_name.lower():
                self._drive_id = drive["id"]
                return self._drive_id

        # If exact match fails, try partial match
        for drive in data.get("value", []):
            if self.library_name.lower() in drive.get("name", "").lower():
                self._drive_id = drive["id"]
                return self._drive_id

        available = [d.get("name", "?") for d in data.get("value", [])]
        raise RuntimeError(
            f"Document library '{self.library_name}' not found. "
            f"Available libraries: {available}"
        )

    # =========================================================================
    # File Listing
    # =========================================================================
    def list_items(
        self,
        folder_path: Optional[str] = None,
        limit: int = 10,
    ) -> SharePointListResult:
        """
        List files and folders in the SharePoint document library.
        
        Args:
            folder_path: Optional path within the library (e.g. "ClientA/Agreement").
                         If None, lists the root of the library.
            limit: Maximum number of items to return.
        
        Returns:
            SharePointListResult with items.
        """
        drive_id = self.get_drive_id()

        # Build endpoint
        if folder_path:
            # Folder path within the drive
            clean_path = folder_path.strip("/")
            endpoint = f"/drives/{drive_id}/root:/{clean_path}:/children"
        else:
            # Root of the drive
            endpoint = f"/drives/{drive_id}/root/children"

        params = {
            "$top": str(limit),
            "$orderby": "name asc",
            "$select": "id,name,size,lastModifiedDateTime,webUrl,folder,file,@microsoft.graph.downloadUrl",
        }

        data = self._graph_get(endpoint, params=params)

        # Parse items
        items: List[SharePointItem] = []
        for raw in data.get("value", []):
            is_folder = "folder" in raw
            modified = None
            if raw.get("lastModifiedDateTime"):
                try:
                    modified = datetime.fromisoformat(
                        raw["lastModifiedDateTime"].replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    pass

            item = SharePointItem(
                name=raw.get("name", ""),
                item_id=raw.get("id", ""),
                is_folder=is_folder,
                size_bytes=raw.get("size", 0),
                modified_date=modified,
                web_url=raw.get("webUrl"),
                download_url=raw.get("@microsoft.graph.downloadUrl"),
                child_count=raw.get("folder", {}).get("childCount", 0) if is_folder else 0,
                mime_type=raw.get("file", {}).get("mimeType") if not is_folder else None,
            )
            items.append(item)

        return SharePointListResult(
            site_name=self.hostname,
            library_name=self.library_name,
            drive_id=drive_id,
            items=items,
            total_count=len(items),
        )

    def download_file(self, item: SharePointItem, dest_path: Path) -> Path:
        """
        Download a SharePoint file to a local path.
        
        Args:
            item: The SharePointItem to download.
            dest_path: Local directory to save the file into.
        
        Returns:
            Path to the downloaded file.
        """
        if item.is_folder:
            raise ValueError(f"Cannot download a folder: {item.name}")

        # Use the download URL if available, otherwise construct one
        if item.download_url:
            url = item.download_url
        else:
            drive_id = self.get_drive_id()
            url_endpoint = f"{GRAPH_BASE}/drives/{drive_id}/items/{item.item_id}/content"
            url = url_endpoint

        resp = requests.get(url, headers=self._headers(), stream=True, timeout=120)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to download {item.name}: HTTP {resp.status_code}")

        dest_path.mkdir(parents=True, exist_ok=True)
        file_path = dest_path / item.name

        with open(file_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        return file_path
