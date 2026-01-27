"""
Directory Scanner with Phased Extraction.

This module scans project directories and extracts information in phases.
Each phase can be enhanced independently as the project evolves.

PHASES:
- Phase 1: Structure & Hierarchy (current) - File tree, folder structure
- Phase 2: Metadata (placeholder) - File sizes, dates, types
- Phase 3: Content Extraction (placeholder) - Actual file contents
- Phase 4: Deep Analysis (placeholder) - OCR, table extraction, etc.
"""

from __future__ import annotations

import os
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.config import RECOGNIZED_EXTENSIONS, IGNORED_FOLDERS


# Phase detection patterns
PHASE_PATTERNS = [
    r"phase\s*(\d+)",      # "Phase 1", "Phase 2", "phase1"
    r"ph\s*(\d+)",         # "Ph 1", "Ph2"
]

# Wave patterns (these are WITHIN a phase, not separate phases)
WAVE_PATTERNS = [
    r"wave\s*(\d+)",       # "Wave 1", "Wave 2"
]


@dataclass
class PhaseInfo:
    """Information about a detected project phase."""
    phase_number: int
    phase_name: str  # e.g., "Phase 1", "Phase 2"
    
    # Folders that belong to this phase
    folders: List[str] = field(default_factory=list)
    
    # Files that belong to this phase  
    files: List[str] = field(default_factory=list)
    
    # Waves within this phase (e.g., "Wave 1", "Wave 2")
    waves: List[str] = field(default_factory=list)
    
    # Key anchor files for this phase (Agreement, Exhibit, etc.)
    agreement_path: Optional[str] = None
    exhibit_paths: List[str] = field(default_factory=list)
    categories_folder: Optional[str] = None
    project_updates_folder: Optional[str] = None
    closeout_folder: Optional[str] = None


@dataclass
class FileInfo:
    """Information about a single file."""
    name: str
    path: Path
    extension: str
    size_bytes: int = 0
    modified_date: Optional[datetime] = None
    # Phase 3+: content preview, extracted text, etc.
    content_preview: Optional[str] = None


@dataclass
class FolderInfo:
    """Information about a folder and its contents."""
    name: str
    path: Path
    files: List[FileInfo] = field(default_factory=list)
    subfolders: List[FolderInfo] = field(default_factory=list)
    depth: int = 0


@dataclass
class ScanResult:
    """Complete scan result for a project."""
    project_name: str
    root_path: Path
    root_folder: FolderInfo
    total_files: int = 0
    total_folders: int = 0
    file_type_counts: Dict[str, int] = field(default_factory=dict)
    scan_timestamp: datetime = field(default_factory=datetime.now)
    # Cache of all file paths for validation
    _all_file_paths: Optional[List[str]] = field(default=None, repr=False)
    
    # Phase detection results
    phases: List[PhaseInfo] = field(default_factory=list)
    is_multi_phase: bool = False
    
    def get_all_file_paths(self) -> List[str]:
        """
        Get a list of all file paths (relative to project root).
        
        Used to validate LLM file selections - prevents hallucinated paths.
        """
        if self._all_file_paths is not None:
            return self._all_file_paths
        
        paths: List[str] = []
        self._collect_paths(self.root_folder, "", paths)
        self._all_file_paths = paths
        return paths
    
    def _collect_paths(self, folder: FolderInfo, prefix: str, paths: List[str]) -> None:
        """Recursively collect all file paths."""
        for f in folder.files:
            rel_path = f"{prefix}{f.name}" if prefix else f.name
            paths.append(rel_path)
        for sf in folder.subfolders:
            new_prefix = f"{prefix}{sf.name}/" if prefix else f"{sf.name}/"
            self._collect_paths(sf, new_prefix, paths)
    
    def validate_file_paths(self, selected_paths: List[str]) -> Tuple[List[str], List[str]]:
        """
        Validate a list of file paths against actual files.
        
        Returns:
            Tuple of (valid_paths, invalid_paths)
        """
        all_paths = set(self.get_all_file_paths())
        valid = []
        invalid = []
        
        for path in selected_paths:
            # Normalize path (remove leading ./ or /)
            normalized = path.lstrip("./")
            if normalized in all_paths:
                valid.append(normalized)
            else:
                # Try case-insensitive match
                lower_path = normalized.lower()
                matched = False
                for ap in all_paths:
                    if ap.lower() == lower_path:
                        valid.append(ap)
                        matched = True
                        break
                if not matched:
                    invalid.append(path)
        
        return valid, invalid
    
    def to_tree_string(self) -> str:
        """Convert scan result to a tree-like string representation."""
        lines = [
            f"📁 {self.project_name}/",
            f"   Scanned: {self.scan_timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            f"   Total: {self.total_files} files in {self.total_folders} folders",
            "",
            "Structure:",
            "─" * 50,
        ]
        
        self._build_tree(self.root_folder, lines, prefix="")
        
        # Add file type summary
        if self.file_type_counts:
            lines.append("")
            lines.append("File Types:")
            lines.append("─" * 50)
            for ext, count in sorted(self.file_type_counts.items(), key=lambda x: -x[1]):
                lines.append(f"  {ext}: {count} file(s)")
        
        return "\n".join(lines)
    
    def _build_tree(self, folder: FolderInfo, lines: List[str], prefix: str) -> None:
        """Recursively build tree representation."""
        # Sort subfolders and files
        subfolders = sorted(folder.subfolders, key=lambda x: x.name.lower())
        files = sorted(folder.files, key=lambda x: x.name.lower())
        
        items = [(True, sf) for sf in subfolders] + [(False, f) for f in files]
        
        for i, (is_folder, item) in enumerate(items):
            is_last = i == len(items) - 1
            connector = "└── " if is_last else "├── "
            
            if is_folder:
                folder_item: FolderInfo = item  # type: ignore
                lines.append(f"{prefix}{connector}📁 {folder_item.name}/")
                extension = "    " if is_last else "│   "
                self._build_tree(folder_item, lines, prefix + extension)
            else:
                file_item: FileInfo = item  # type: ignore
                icon = self._get_file_icon(file_item.extension)
                size_str = self._format_size(file_item.size_bytes)
                lines.append(f"{prefix}{connector}{icon} {file_item.name} ({size_str})")
    
    def _get_file_icon(self, extension: str) -> str:
        """Get appropriate icon for file type."""
        icons = {
            ".pdf": "📄",
            ".doc": "📝", ".docx": "📝",
            ".ppt": "📊", ".pptx": "📊",
            ".xls": "📈", ".xlsx": "📈", ".csv": "📈",
            ".png": "🖼️", ".jpg": "🖼️", ".jpeg": "🖼️",
            ".txt": "📃",
            ".zip": "🗜️", ".rar": "🗜️",
            ".eml": "📧", ".msg": "📧",
        }
        return icons.get(extension.lower(), "📎")
    
    def _format_size(self, size_bytes: int) -> str:
        """Format file size in human-readable form."""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


class DirectoryScanner:
    """
    Scans project directories with phased extraction.
    
    Usage:
        scanner = DirectoryScanner()
        result = scanner.scan("/path/to/project")
        print(result.to_tree_string())
    """
    
    def __init__(self):
        """Initialize the scanner."""
        self.recognized_extensions = RECOGNIZED_EXTENSIONS
        self.ignored_folders = IGNORED_FOLDERS
    
    def scan(self, project_path: Path) -> ScanResult:
        """
        Scan a project directory and return structured result.
        
        This is the main entry point. It orchestrates all phases.
        
        Args:
            project_path: Path to the project folder
            
        Returns:
            ScanResult with complete project structure
        """
        if not project_path.exists():
            raise FileNotFoundError(f"Project path does not exist: {project_path}")
        
        if not project_path.is_dir():
            raise ValueError(f"Project path is not a directory: {project_path}")
        
        # Initialize result
        result = ScanResult(
            project_name=project_path.name,
            root_path=project_path,
            root_folder=FolderInfo(name=project_path.name, path=project_path, depth=0),
        )
        
        # Run phases
        self._phase1_structure(project_path, result.root_folder, result)
        self._phase2_metadata(result)  # Placeholder
        
        # Detect project phases (Phase 1, Phase 2, etc.)
        self._detect_project_phases(result)
        
        # self._phase3_content(result)  # Future
        # self._phase4_deep_analysis(result)  # Future
        
        return result
    
    # =========================================================================
    # PHASE 1: Structure & Hierarchy
    # =========================================================================
    def _phase1_structure(
        self, 
        current_path: Path, 
        current_folder: FolderInfo, 
        result: ScanResult
    ) -> None:
        """
        Phase 1: Capture directory structure and file hierarchy.
        
        This phase walks the directory tree and builds the folder/file structure.
        It collects basic file info (name, extension, size).
        
        MODIFY THIS PHASE to change how the structure is captured.
        """
        try:
            entries = list(current_path.iterdir())
        except PermissionError:
            return
        
        for entry in entries:
            # Skip ignored folders
            if entry.is_dir() and entry.name in self.ignored_folders:
                continue
            
            # Skip hidden files/folders
            if entry.name.startswith("."):
                continue
            
            if entry.is_dir():
                # Create subfolder info
                subfolder = FolderInfo(
                    name=entry.name,
                    path=entry,
                    depth=current_folder.depth + 1,
                )
                current_folder.subfolders.append(subfolder)
                result.total_folders += 1
                
                # Recurse into subfolder
                self._phase1_structure(entry, subfolder, result)
                
            elif entry.is_file():
                # Get file info
                extension = entry.suffix.lower()
                
                try:
                    stat = entry.stat()
                    size = stat.st_size
                    modified = datetime.fromtimestamp(stat.st_mtime)
                except (OSError, PermissionError):
                    size = 0
                    modified = None
                
                file_info = FileInfo(
                    name=entry.name,
                    path=entry,
                    extension=extension,
                    size_bytes=size,
                    modified_date=modified,
                )
                current_folder.files.append(file_info)
                result.total_files += 1
                
                # Track file type counts
                ext_key = extension if extension else "(no extension)"
                result.file_type_counts[ext_key] = result.file_type_counts.get(ext_key, 0) + 1
    
    # =========================================================================
    # PROJECT PHASE DETECTION
    # =========================================================================
    def _detect_project_phases(self, result: ScanResult) -> None:
        """
        Detect if this is a multi-phase project.
        
        Looks for:
        - Folders named "Phase 1", "Phase 2", etc.
        - Files with "Phase 1", "Phase 2" in names
        - Multiple Agreements or Exhibits with phase labels
        
        Note: "Waves" (Wave 1, Wave 2) are WITHIN a phase, not separate phases.
        """
        all_paths = result.get_all_file_paths()
        phases_found: Dict[int, PhaseInfo] = {}
        
        # Helper to extract phase number from a string
        def extract_phase_number(text: str) -> Optional[int]:
            text_lower = text.lower()
            for pattern in PHASE_PATTERNS:
                match = re.search(pattern, text_lower)
                if match:
                    return int(match.group(1))
            return None
        
        # Helper to extract wave info
        def extract_wave(text: str) -> Optional[str]:
            text_lower = text.lower()
            for pattern in WAVE_PATTERNS:
                match = re.search(pattern, text_lower)
                if match:
                    return f"Wave {match.group(1)}"
            return None
        
        # Scan all paths for phase indicators
        for path in all_paths:
            path_parts = path.split("/")
            
            # Check each path component for phase indicator
            for part in path_parts:
                phase_num = extract_phase_number(part)
                if phase_num is not None:
                    if phase_num not in phases_found:
                        phases_found[phase_num] = PhaseInfo(
                            phase_number=phase_num,
                            phase_name=f"Phase {phase_num}",
                        )
                    
                    # Add file to this phase
                    phases_found[phase_num].files.append(path)
                    
                    # Check for waves within this phase
                    wave = extract_wave(path)
                    if wave and wave not in phases_found[phase_num].waves:
                        phases_found[phase_num].waves.append(wave)
                    
                    # Track folder if it's the first component with phase
                    folder_path = "/".join(path_parts[:path_parts.index(part) + 1])
                    if folder_path not in phases_found[phase_num].folders:
                        phases_found[phase_num].folders.append(folder_path)
                    
                    break  # Only count once per file
        
        # Also check folder names in the directory structure
        self._scan_folders_for_phases(result.root_folder, "", phases_found)
        
        # If we found multiple phases, mark as multi-phase
        if len(phases_found) > 1:
            result.is_multi_phase = True
            result.phases = [phases_found[k] for k in sorted(phases_found.keys())]
        elif len(phases_found) == 1:
            # Single phase explicitly labeled
            result.is_multi_phase = False
            result.phases = [phases_found[list(phases_found.keys())[0]]]
        else:
            # No phases found - treat entire project as single implicit phase
            result.is_multi_phase = False
            # Don't add a phase - let the rest of the code handle it as before
    
    def _scan_folders_for_phases(
        self, 
        folder: FolderInfo, 
        path_prefix: str, 
        phases_found: Dict[int, PhaseInfo]
    ) -> None:
        """Recursively scan folders for phase indicators."""
        for subfolder in folder.subfolders:
            folder_path = f"{path_prefix}{subfolder.name}" if path_prefix else subfolder.name
            
            # Check folder name for phase
            phase_num = None
            for pattern in PHASE_PATTERNS:
                match = re.search(pattern, subfolder.name.lower())
                if match:
                    phase_num = int(match.group(1))
                    break
            
            if phase_num is not None:
                if phase_num not in phases_found:
                    phases_found[phase_num] = PhaseInfo(
                        phase_number=phase_num,
                        phase_name=f"Phase {phase_num}",
                    )
                
                if folder_path not in phases_found[phase_num].folders:
                    phases_found[phase_num].folders.append(folder_path)
                
                # Check for key folders within this phase folder
                folder_name_lower = subfolder.name.lower()
                for inner_folder in subfolder.subfolders:
                    inner_name_lower = inner_folder.name.lower()
                    inner_path = f"{folder_path}/{inner_folder.name}"
                    
                    if "agreement" in inner_name_lower:
                        phases_found[phase_num].agreement_path = inner_path
                    elif "categor" in inner_name_lower:
                        phases_found[phase_num].categories_folder = inner_path
                    elif "update" in inner_name_lower:
                        phases_found[phase_num].project_updates_folder = inner_path
                    elif "close" in inner_name_lower or "closeout" in inner_name_lower:
                        phases_found[phase_num].closeout_folder = inner_path
            
            # Recurse
            self._scan_folders_for_phases(subfolder, folder_path + "/", phases_found)
    
    # =========================================================================
    # PHASE 2: Metadata (Placeholder)
    # =========================================================================
    def _phase2_metadata(self, result: ScanResult) -> None:
        """
        Phase 2: Enhanced metadata extraction.
        
        FUTURE ENHANCEMENTS:
        - PDF page counts
        - PPTX slide counts
        - Excel sheet names
        - Document authors/creation dates
        - Image dimensions
        
        Currently: Basic metadata captured in Phase 1 (size, modified date)
        """
        pass  # Placeholder for future implementation
    
    # =========================================================================
    # PHASE 3: Content Extraction (Placeholder)
    # =========================================================================
    def _phase3_content(self, result: ScanResult) -> None:
        """
        Phase 3: Extract actual content from files.
        
        FUTURE ENHANCEMENTS:
        - PDF text extraction (PyMuPDF/pdfplumber)
        - PPTX text and notes extraction (python-pptx)
        - DOCX text extraction (python-docx)
        - Excel data extraction (openpyxl)
        - CSV/JSON parsing
        
        This phase would populate FileInfo.content_preview
        """
        pass  # Placeholder for future implementation
    
    # =========================================================================
    # PHASE 4: Deep Analysis (Placeholder)
    # =========================================================================
    def _phase4_deep_analysis(self, result: ScanResult) -> None:
        """
        Phase 4: Advanced content analysis.
        
        FUTURE ENHANCEMENTS:
        - OCR for scanned documents (pytesseract)
        - Table extraction from PDFs
        - Image analysis
        - Named entity recognition
        - Key phrase extraction
        
        This is the most advanced phase for complex documents.
        """
        pass  # Placeholder for future implementation


def find_project_in_inputs(inputs_dir: Path) -> Tuple[Optional[Path], bool]:
    """
    Find a single project folder or zip file in the inputs directory.
    
    Returns:
        Tuple of (path, is_zip) where:
        - path: Path to folder or zip file, or None if empty
        - is_zip: True if path is a zip file that needs extraction
    """
    if not inputs_dir.exists():
        return None, False
    
    # First, look for existing folders (prefer already-extracted)
    for entry in inputs_dir.iterdir():
        if entry.is_dir() and not entry.name.startswith("."):
            return entry, False
    
    # If no folder found, look for zip files
    for entry in inputs_dir.iterdir():
        if entry.is_file() and entry.suffix.lower() == ".zip":
            return entry, True
    
    return None, False


def extract_zip_project(zip_path: Path, extract_to: Optional[Path] = None) -> Path:
    """
    Extract a zip file to a folder.
    
    Args:
        zip_path: Path to the zip file
        extract_to: Optional destination folder. If None, extracts to same directory as zip.
        
    Returns:
        Path to the extracted project folder
    """
    if extract_to is None:
        extract_to = zip_path.parent
    
    # Get the project name from zip filename
    project_name = zip_path.stem
    project_folder = extract_to / project_name
    
    # Extract the zip
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        # Get all members
        members = zip_ref.namelist()
        
        # Check if zip has a root folder or files at root
        has_root_folder = all(m.startswith(members[0].split('/')[0] + '/') for m in members if m)
        
        if has_root_folder:
            # Extract directly - zip already has a root folder
            zip_ref.extractall(extract_to)
            # The extracted folder name is the first path component
            root_folder_name = members[0].split('/')[0]
            project_folder = extract_to / root_folder_name
        else:
            # Create project folder and extract into it
            project_folder.mkdir(exist_ok=True)
            zip_ref.extractall(project_folder)
    
    return project_folder
