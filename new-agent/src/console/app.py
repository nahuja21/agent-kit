"""
Console Application with Rich styling.

This provides an interactive console interface similar to agent-kit
but simplified for the project summary use case.
"""

from __future__ import annotations

import asyncio
import json
import os
import readline
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.config import (
    INPUTS_DIR,
    OUTPUTS_DIR,
    MODEL,
    validate_config,
    validate_azure_config,
    ensure_directories,
    AZURE_SQL_ENABLED,
    AZURE_SQL_TABLE,
    get_azure_connection_string,
)
from src.scanner import DirectoryScanner, find_project_in_inputs, extract_zip_project
from src.llm import OpenAIClient
from src.prompts import ContextBuilder
from src.prompts.context import get_file_selection_prompt, get_schema_extraction_prompt, FILE_SELECTION_COUNT
from src.prompts.loader import get_anchor_detection_prompt, get_project_scope_prompt, get_client_context_prompt, get_engagement_background_prompt, get_impact_prompt, get_categories_prompt, get_case_study_generation_prompt, get_supplier_battlecards_prompt
from src.extractors.pdf import extract_pdf_with_tables, find_exhibit_pages, extract_table_with_vision, extract_table_with_tesseract
from src.extractors.base import extract_file_content
from src.models.schema import CaseStudy
from src.database import AzureSQLWriter
import re


def extract_json_from_response(content: str) -> dict:
    """
    Robustly extract JSON from LLM response that may contain markdown or text.
    
    Handles:
    - JSON wrapped in ```json ... ``` or ``` ... ```
    - JSON with text before/after
    - Trailing commas in arrays/objects
    - Multiple JSON objects (returns first complete one)
    - Various markdown code fence formats
    """
    if not content:
        raise ValueError("Empty content")
    
    content = content.strip()
    
    # Strategy 1: Try direct parse first
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    
    # Strategy 2: Remove markdown code fences (multiple patterns)
    # Handle various formats: ```json, ``` json, ```JSON, etc.
    code_block_patterns = [
        r'```json\s*\n(.*?)\n\s*```',  # ```json\n...\n```
        r'```JSON\s*\n(.*?)\n\s*```',  # ```JSON\n...\n```
        r'```\s*\n(.*?)\n\s*```',       # ```\n...\n```
        r'```json\s*(.*?)\s*```',       # ```json...``` (no newlines)
        r'```\s*(.*?)\s*```',           # ```...``` (no newlines)
        r'`json\s*\n(.*?)\n\s*`',       # Single backtick variants
    ]
    
    for pattern in code_block_patterns:
        matches = re.findall(pattern, content, re.DOTALL | re.IGNORECASE)
        if matches:
            for match in matches:
                match_stripped = match.strip()
                if not match_stripped:
                    continue
                try:
                    return json.loads(match_stripped)
                except json.JSONDecodeError:
                    # Try fixing trailing commas
                    fixed = re.sub(r',\s*([}\]])', r'\1', match_stripped)
                    try:
                        return json.loads(fixed)
                    except json.JSONDecodeError:
                        continue
    
    # Strategy 3: Find JSON object by looking for { ... } pattern
    # Find the first { that starts a "categories" or similar key pattern
    # First try to find a JSON object that looks like our expected output
    for start_pattern in ['"categories"', '"battlecards"', '"client"', '"impact"']:
        pattern_pos = content.find(start_pattern)
        if pattern_pos != -1:
            # Find the opening { before this pattern
            brace_start = content.rfind('{', 0, pattern_pos)
            if brace_start != -1:
                result = _try_extract_json_from_position(content, brace_start)
                if result:
                    return result
    
    # Fallback: Find the first { and match to its closing }
    brace_start = content.find('{')
    if brace_start != -1:
        result = _try_extract_json_from_position(content, brace_start)
        if result:
            return result
    
    # Strategy 4: Try removing common prefix text patterns
    # LLM sometimes says "Here's the JSON:" before the actual JSON
    lines = content.split('\n')
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('{') or stripped == '{':
            remaining = '\n'.join(lines[i:])
            try:
                return json.loads(remaining)
            except json.JSONDecodeError:
                fixed = re.sub(r',\s*([}\]])', r'\1', remaining)
                try:
                    return json.loads(fixed)
                except json.JSONDecodeError:
                    # Don't break, try next line that starts with {
                    continue
    
    # Strategy 5: Try to find JSON between the last ``` pair
    last_fence_end = content.rfind('```')
    if last_fence_end != -1:
        before_last = content[:last_fence_end]
        second_last_fence = before_last.rfind('```')
        if second_last_fence != -1:
            between = content[second_last_fence + 3:last_fence_end].strip()
            # Remove 'json' prefix if present
            if between.lower().startswith('json'):
                between = between[4:].strip()
            if between:
                try:
                    return json.loads(between)
                except json.JSONDecodeError:
                    fixed = re.sub(r',\s*([}\]])', r'\1', between)
                    try:
                        return json.loads(fixed)
                    except json.JSONDecodeError:
                        pass
    
    # If all strategies fail, raise with helpful message
    raise json.JSONDecodeError(
        f"Could not extract valid JSON from response (length: {len(content)} chars)",
        content[:200] + "..." if len(content) > 200 else content,
        0
    )


def _try_extract_json_from_position(content: str, brace_start: int) -> dict | None:
    """Try to extract a complete JSON object starting at brace_start."""
    depth = 0
    in_string = False
    escape = False
    
    for i, char in enumerate(content[brace_start:], brace_start):
        if escape:
            escape = False
            continue
        if char == '\\':
            escape = True
            continue
        if char == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                json_str = content[brace_start:i+1]
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    # Try fixing trailing commas
                    fixed = re.sub(r',\s*([}\]])', r'\1', json_str)
                    try:
                        return json.loads(fixed)
                    except json.JSONDecodeError:
                        return None
    return None


class ConsoleApp:
    """Interactive console application for project analysis."""
    
    def __init__(self):
        """Initialize the console application."""
        self.console = Console()
        self.exit_requested = False
        self.scanner = DirectoryScanner()
        self.context_builder = ContextBuilder()
        self.llm_client: Optional[OpenAIClient] = None
        
        # Command registry: {command: (handler, description)}
        self._commands: Dict[str, Tuple[Callable, str]] = {}
        self._register_commands()
        self._setup_readline()
    
    def _register_commands(self) -> None:
        """Register available commands."""
        self._commands["/file"] = (self._handle_file, "Scan project folder and analyze with AI (simple analysis)")
        self._commands["/extract"] = (self._handle_extract, "Extract structured case study data (two-pass extraction)")
        self._commands["/agent"] = (self._handle_agent, "Smart extraction with anchor file detection (new pipeline)")
        self._commands["/help"] = (self._handle_help, "Show available commands")
        self._commands["/quit"] = (self._handle_quit, "Exit the console")
        self._commands["/exit"] = (self._handle_quit, "Exit the console")
        self._commands["/status"] = (self._handle_status, "Show current configuration status")
    
    def _setup_readline(self) -> None:
        """Set up readline for tab completion."""
        try:
            readline.set_completer(self._completer)
            if readline.__doc__ and "libedit" in readline.__doc__:
                readline.parse_and_bind("bind ^I rl_complete")
            else:
                readline.parse_and_bind("tab: complete")
            readline.set_completer_delims(" \t\n")
        except (ImportError, AttributeError):
            pass
    
    def _completer(self, text: str, state: int) -> Optional[str]:
        """Tab completion for commands."""
        if text.startswith("/"):
            matches = [cmd + " " for cmd in self._commands.keys() if cmd.startswith(text)]
            return matches[state] if state < len(matches) else None
        return None
    
    def _print_banner(self) -> None:
        """Print welcome banner."""
        banner_text = Text()
        banner_text.append("🔍 ", style="bold")
        banner_text.append("Project Summary Agent", style="bold cyan")
        banner_text.append("\n")
        banner_text.append("Treya Partners Project Analysis Tool", style="dim")
        
        self.console.print(Panel(
            banner_text,
            border_style="cyan",
            padding=(1, 2),
        ))
        
        self.console.print(f"[dim]Model: {MODEL} | Inputs: {INPUTS_DIR.name}/ | Outputs: {OUTPUTS_DIR.name}/[/dim]\n")
    
    def _print_help(self) -> None:
        """Print help table."""
        table = Table(title="Available Commands", border_style="cyan")
        table.add_column("Command", style="cyan", width=15)
        table.add_column("Description", style="dim")
        
        for cmd, (_, desc) in sorted(self._commands.items()):
            table.add_row(cmd, desc)
        
        self.console.print(table)
        self.console.print()
    
    async def _handle_help(self, args: List[str]) -> None:
        """Handle /help command."""
        self._print_help()
    
    async def _handle_quit(self, args: List[str]) -> None:
        """Handle /quit command."""
        self.exit_requested = True
        self.console.print("[yellow]👋 Goodbye![/yellow]")
    
    async def _handle_status(self, args: List[str]) -> None:
        """Handle /status command."""
        errors = validate_config()
        
        table = Table(title="Configuration Status", border_style="cyan")
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="white")
        table.add_column("Status", style="white")
        
        # API Key
        api_key_status = "✅" if not any("API_KEY" in e for e in errors) else "❌"
        api_key_display = "sk-..." if os.environ.get("OPENAI_API_KEY", "").startswith("sk-") else "(not set)"
        table.add_row("OpenAI API Key", api_key_display, api_key_status)
        
        # Model
        table.add_row("Model", MODEL, "✅")
        
        # Directories
        inputs_status = "✅" if INPUTS_DIR.exists() else "⚠️ (will create)"
        outputs_status = "✅" if OUTPUTS_DIR.exists() else "⚠️ (will create)"
        table.add_row("Inputs Directory", str(INPUTS_DIR), inputs_status)
        table.add_row("Outputs Directory", str(OUTPUTS_DIR), outputs_status)
        
        # Project folder or zip
        project, is_zip = find_project_in_inputs(INPUTS_DIR)
        if project:
            if is_zip:
                project_status = f"🗜️ {project.name} (zip - will extract)"
                table.add_row("Project", project.name, project_status)
            else:
                project_status = f"✅ {project.name}"
                table.add_row("Project Folder", project.name, project_status)
        else:
            table.add_row("Project Folder", "(empty)", "⚠️ (no project found)")
        
        # Azure SQL Database
        if AZURE_SQL_ENABLED:
            azure_errors = validate_azure_config()
            azure_status = "✅" if not azure_errors else "❌"
            table.add_row("Azure SQL", "Enabled", azure_status)
            table.add_row("Azure SQL Table", AZURE_SQL_TABLE, "")
        else:
            table.add_row("Azure SQL", "Disabled", "⚪ (set AZURE_SQL_ENABLED=true)")
        
        self.console.print(table)
        
        if errors:
            self.console.print("\n[red]Configuration Errors:[/red]")
            for error in errors:
                self.console.print(f"  [red]•[/red] {error}")
        
        # Azure SQL errors
        if AZURE_SQL_ENABLED:
            azure_errors = validate_azure_config()
            if azure_errors:
                self.console.print("\n[red]Azure SQL Configuration Errors:[/red]")
                for error in azure_errors:
                    self.console.print(f"  [red]•[/red] {error}")
        
        self.console.print()
    
    async def _handle_file(self, args: List[str]) -> None:
        """
        Handle /file command - scan project and analyze with AI.
        
        This is the simple analysis command (original behavior).
        """
        # Validate configuration
        errors = validate_config()
        if errors:
            self.console.print("[red]Configuration errors:[/red]")
            for error in errors:
                self.console.print(f"  [red]•[/red] {error}")
            return
        
        # Ensure directories exist
        ensure_directories()
        
        # Find project folder or zip file
        project_path, is_zip = find_project_in_inputs(INPUTS_DIR)
        if not project_path:
            self.console.print(f"[red]No project folder or zip file found in {INPUTS_DIR}/[/red]")
            self.console.print(f"[dim]Please add a project folder or .zip file to {INPUTS_DIR}/ and try again.[/dim]")
            return
        
        # Handle zip extraction
        if is_zip:
            self.console.print(f"\n[cyan]🗜️ Found zip file:[/cyan] {project_path.name}")
            with self.console.status("[cyan]Extracting zip file...[/cyan]"):
                try:
                    project_path = extract_zip_project(project_path)
                    self.console.print(f"[green]✓[/green] Extracted to: {project_path.name}/")
                except Exception as e:
                    self.console.print(f"[red]Failed to extract zip: {e}[/red]")
                    return
        else:
            self.console.print(f"\n[cyan]📁 Found project:[/cyan] {project_path.name}")
        
        self.console.print()
        
        # =====================================================================
        # PHASE 1: Scan Directory Structure
        # =====================================================================
        with self.console.status("[cyan]Scanning directory structure...[/cyan]"):
            try:
                scan_result = self.scanner.scan(project_path)
            except Exception as e:
                self.console.print(f"[red]Failed to scan directory: {e}[/red]")
                return
        
        # Display scan results
        self.console.print(Panel(
            scan_result.to_tree_string(),
            title="[cyan]Directory Structure[/cyan]",
            border_style="cyan",
        ))
        
        # =====================================================================
        # PHASE 2: Build Context & Send to OpenAI
        # =====================================================================
        self.console.print("\n[cyan]🤖 Sending to OpenAI for analysis...[/cyan]")
        
        # Build prompts
        system_prompt = self.context_builder.build_full_context()
        user_content = f"""# Project Analysis Request

## Project: {scan_result.project_name}

## Directory Structure:
```
{scan_result.to_tree_string()}
```

Please analyze this project folder structure and provide insights based on the 
background knowledge about Treya Partners projects.
"""
        
        # Initialize LLM client if needed
        if not self.llm_client:
            self.llm_client = OpenAIClient()
        
        # Call OpenAI
        with self.console.status(f"[cyan]Analyzing with {MODEL}...[/cyan]"):
            try:
                response = self.llm_client.analyze(system_prompt, user_content)
            except Exception as e:
                self.console.print(f"[red]Failed to analyze with OpenAI: {e}[/red]")
                return
        
        # =====================================================================
        # PHASE 3: Display Results
        # =====================================================================
        
        # Show reasoning if available
        if response.reasoning:
            self.console.print(Panel(
                response.reasoning,
                title="[yellow]🧠 Reasoning[/yellow]",
                border_style="yellow",
            ))
        
        # Show main output
        self.console.print(Panel(
            Markdown(response.content),
            title="[green]📊 Analysis Output[/green]",
            border_style="green",
        ))
        
        # Show token usage
        self.console.print(f"\n[dim]Tokens: {response.input_tokens} in / {response.output_tokens} out / {response.total_tokens} total[/dim]")
        
        # =====================================================================
        # PHASE 4: Save Output
        # =====================================================================
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = OUTPUTS_DIR / f"{scan_result.project_name}_{timestamp}.txt"
        
        output_content = f"""# Project Analysis: {scan_result.project_name}
Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
Model: {response.model}
Tokens: {response.input_tokens} in / {response.output_tokens} out / {response.total_tokens} total

================================================================================
DIRECTORY STRUCTURE
================================================================================

{scan_result.to_tree_string()}

================================================================================
REASONING
================================================================================

{response.reasoning or "(No reasoning output for this model)"}

================================================================================
ANALYSIS OUTPUT
================================================================================

{response.content}
"""
        
        try:
            output_file.write_text(output_content, encoding="utf-8")
            self.console.print(f"\n[green]✓[/green] Saved to: {output_file}")
        except Exception as e:
            self.console.print(f"[yellow]⚠️ Could not save output: {e}[/yellow]")
        
        self.console.print()

    # =========================================================================
    # /extract Command - Two-Pass Structured Extraction
    # =========================================================================
    async def _handle_extract(self, args: List[str]) -> None:
        """
        Handle /extract command - structured case study extraction.
        
        This is the two-pass extraction:
        1. Pass 1: LLM selects important files from directory tree
        2. Pass 2: Extract content from files, LLM fills the schema
        """
        # Validate configuration
        errors = validate_config()
        if errors:
            self.console.print("[red]Configuration errors:[/red]")
            for error in errors:
                self.console.print(f"  [red]•[/red] {error}")
            return
        
        # Ensure directories exist
        ensure_directories()
        
        # Find project folder or zip file
        project_path, is_zip = find_project_in_inputs(INPUTS_DIR)
        if not project_path:
            self.console.print(f"[red]No project folder or zip file found in {INPUTS_DIR}/[/red]")
            self.console.print(f"[dim]Please add a project folder or .zip file to {INPUTS_DIR}/ and try again.[/dim]")
            return
        
        # Handle zip extraction
        if is_zip:
            self.console.print(f"\n[cyan]🗜️ Found zip file:[/cyan] {project_path.name}")
            with self.console.status("[cyan]Extracting zip file...[/cyan]"):
                try:
                    project_path = extract_zip_project(project_path)
                    self.console.print(f"[green]✓[/green] Extracted to: {project_path.name}/")
                except Exception as e:
                    self.console.print(f"[red]Failed to extract zip: {e}[/red]")
                    return
        else:
            self.console.print(f"\n[cyan]📁 Found project:[/cyan] {project_path.name}")
        
        self.console.print()
        
        # Initialize LLM client if needed
        if not self.llm_client:
            self.llm_client = OpenAIClient()
        
        # =====================================================================
        # STEP 1: Scan Directory Structure
        # =====================================================================
        self.console.print(Panel(
            "[bold]Step 1/4:[/bold] Scanning directory structure",
            border_style="cyan",
        ))
        
        with self.console.status("[cyan]Scanning...[/cyan]"):
            try:
                scan_result = self.scanner.scan(project_path)
            except Exception as e:
                self.console.print(f"[red]Failed to scan directory: {e}[/red]")
                return
        
        self.console.print(f"[green]✓[/green] Found {scan_result.total_files} files in {scan_result.total_folders} folders")
        
        # =====================================================================
        # STEP 2: Pass 1 - LLM Selects Files
        # =====================================================================
        self.console.print(Panel(
            f"[bold]Step 2/4:[/bold] LLM selecting top {FILE_SELECTION_COUNT} files to analyze",
            border_style="cyan",
        ))
        
        file_selection_prompt = get_file_selection_prompt(scan_result.to_tree_string())
        
        with self.console.status(f"[cyan]Asking {MODEL} to select files...[/cyan]"):
            try:
                selection_response = self.llm_client.analyze(
                    system_prompt="You are a document analyst. Return only valid JSON.",
                    user_content=file_selection_prompt,
                )
            except Exception as e:
                self.console.print(f"[red]Failed to get file selection: {e}[/red]")
                return
        
        # Parse the selected files (new format includes categories_found)
        categories_found: List[str] = []
        try:
            # Extract JSON from response (handle markdown code blocks)
            content = selection_response.content.strip()
            if content.startswith("```"):
                # Remove markdown code block
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])
            
            parsed = json.loads(content)
            
            # Handle new format with categories_found and selected_files
            if isinstance(parsed, dict):
                categories_found = parsed.get("categories_found", [])
                raw_selected = parsed.get("selected_files", [])
                
                # Display categories found
                if categories_found:
                    self.console.print(f"[green]✓[/green] LLM identified {len(categories_found)} categories:")
                    for cat in categories_found:
                        self.console.print(f"  [cyan]• {cat}[/cyan]")
            else:
                # Fallback for old format (just array of files)
                raw_selected = parsed
                
        except json.JSONDecodeError as e:
            self.console.print(f"[red]Failed to parse file selection: {e}[/red]")
            self.console.print(f"[dim]Response was: {selection_response.content[:500]}...[/dim]")
            return
        
        # Validate file paths against actual files (prevents hallucinations)
        selected_files, invalid_files = scan_result.validate_file_paths(raw_selected)
        
        self.console.print(f"\n[green]✓[/green] LLM selected {len(selected_files)} valid files:")
        for f in selected_files[:10]:  # Show first 10
            self.console.print(f"  [dim]• {f}[/dim]")
        if len(selected_files) > 10:
            self.console.print(f"  [dim]... and {len(selected_files) - 10} more[/dim]")
        
        if invalid_files:
            self.console.print(f"[yellow]⚠️ {len(invalid_files)} paths were invalid (hallucinated):[/yellow]")
            for f in invalid_files[:3]:
                self.console.print(f"  [dim]• {f}[/dim]")
            if len(invalid_files) > 3:
                self.console.print(f"  [dim]... and {len(invalid_files) - 3} more[/dim]")
        
        # =====================================================================
        # STEP 3: Extract Content from Selected Files
        # =====================================================================
        self.console.print(Panel(
            "[bold]Step 3/4:[/bold] Extracting content from selected files",
            border_style="cyan",
        ))
        
        extracted_contents: List[str] = []
        extraction_errors: List[str] = []
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
        ) as progress:
            task = progress.add_task("[cyan]Extracting...", total=len(selected_files))
            
            for file_rel_path in selected_files:
                file_path = project_path / file_rel_path
                progress.update(task, description=f"[cyan]Extracting: {file_path.name}")
                
                if not file_path.exists():
                    extraction_errors.append(f"File not found: {file_rel_path}")
                    progress.advance(task)
                    continue
                
                # Give Agreement and Case Study files more characters (they contain key data)
                # Default: 20k chars, Agreement/Case Study: 40k chars
                if "agreement" in file_rel_path.lower() or "case study" in file_rel_path.lower():
                    max_chars = 40000  # Full agreements are ~25k, need room for all exhibits
                else:
                    max_chars = 20000  # Increased from 15k
                
                result = extract_file_content(file_path, max_chars=max_chars)
                
                if result.success:
                    header = f"\n{'='*60}\nFILE: {file_rel_path}\n{'='*60}\n"
                    extracted_contents.append(header + result.text_content)
                else:
                    extraction_errors.append(f"{file_rel_path}: {result.error}")
                
                progress.advance(task)
        
        success_count = len(selected_files) - len(extraction_errors)
        self.console.print(f"[green]✓[/green] Extracted content from {success_count}/{len(selected_files)} files")
        
        if extraction_errors:
            self.console.print(f"[yellow]⚠️ {len(extraction_errors)} files had errors:[/yellow]")
            for err in extraction_errors[:5]:
                self.console.print(f"  [dim]• {err}[/dim]")
            if len(extraction_errors) > 5:
                self.console.print(f"  [dim]... and {len(extraction_errors) - 5} more[/dim]")
        
        # Combine all extracted content
        combined_content = "\n".join(extracted_contents)
        self.console.print(f"[dim]Total extracted: {len(combined_content):,} characters[/dim]")
        
        # =====================================================================
        # STEP 3.5: Web Search for Company Info (Revenue)
        # =====================================================================
        self.console.print(Panel(
            f"[bold]Step 3.5/4:[/bold] Searching web for {scan_result.project_name} company info",
            border_style="cyan",
        ))
        
        web_search_info = ""
        try:
            with self.console.status("[cyan]Searching web for company revenue...[/cyan]"):
                web_response = self.llm_client.web_search(
                    f"{scan_result.project_name} company revenue employees locations healthcare"
                )
                web_search_info = web_response.content
                self.console.print(f"[green]✓[/green] Found web info: {len(web_search_info)} chars")
                self.console.print(f"[dim]Preview: {web_search_info[:200]}...[/dim]")
        except Exception as e:
            self.console.print(f"[yellow]⚠️ Web search failed: {e}[/yellow]")
            web_search_info = f"[Web search unavailable - manually lookup {scan_result.project_name} revenue]"
        
        # Add web search results to the combined content
        if web_search_info:
            combined_content = f"""## Web Search Results for {scan_result.project_name}
(Use this for Revenue and company size if not in documents)
---
{web_search_info}
---

## Document Contents
{combined_content}"""
        
        # =====================================================================
        # STEP 4: Pass 2 - LLM Fills Schema
        # =====================================================================
        self.console.print(Panel(
            "[bold]Step 4/4:[/bold] LLM extracting structured case study data",
            border_style="cyan",
        ))
        
        # Get the schema as JSON for the prompt
        schema_json = CaseStudy.model_json_schema()
        schema_json_str = json.dumps(schema_json, indent=2)
        
        extraction_prompt = get_schema_extraction_prompt(
            file_contents=combined_content,
            schema_json=schema_json_str,
            client_name_hint=scan_result.project_name,
        )
        
        with self.console.status(f"[cyan]Extracting with {MODEL}...[/cyan]"):
            try:
                extraction_response = self.llm_client.analyze(
                    system_prompt="You are a structured data extraction expert. Return only valid JSON matching the provided schema.",
                    user_content=extraction_prompt,
                )
            except Exception as e:
                self.console.print(f"[red]Failed to extract: {e}[/red]")
                return
        
        # Parse the case study JSON
        try:
            content = extraction_response.content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])
            case_study_data = json.loads(content)
            
            # Pre-process to fix common LLM output issues
            case_study_data = self._fix_extraction_data(case_study_data)
            
            # Validate with Pydantic
            case_study = CaseStudy.model_validate(case_study_data)
            
        except json.JSONDecodeError as e:
            self.console.print(f"[yellow]⚠️ JSON parse error: {e}[/yellow]")
            self.console.print("[dim]Saving raw response instead...[/dim]")
            case_study = None
            case_study_data = {"raw_response": extraction_response.content}
        except Exception as e:
            self.console.print(f"[yellow]⚠️ Schema validation warning: {e}[/yellow]")
            case_study = None
        
        # =====================================================================
        # Display Results
        # =====================================================================
        self.console.print("\n")
        self.console.print(Panel(
            "[bold green]Extraction Complete![/bold green]",
            border_style="green",
        ))
        
        # Display summary if we have a valid case study
        if case_study:
            self._display_case_study_summary(case_study)
        
        # Show token usage
        total_input = selection_response.input_tokens + extraction_response.input_tokens
        total_output = selection_response.output_tokens + extraction_response.output_tokens
        self.console.print(f"\n[dim]Total Tokens: {total_input:,} in / {total_output:,} out[/dim]")
        
        # =====================================================================
        # Save Outputs
        # =====================================================================
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Save JSON
        json_file = OUTPUTS_DIR / f"{scan_result.project_name}_{timestamp}_case_study.json"
        try:
            if case_study:
                json_output = case_study.model_dump_json(indent=2, exclude_none=True)
            else:
                json_output = json.dumps(case_study_data, indent=2)
            
            json_file.write_text(json_output, encoding="utf-8")
            self.console.print(f"[green]✓[/green] JSON saved: {json_file.name}")
        except Exception as e:
            self.console.print(f"[yellow]⚠️ Could not save JSON: {e}[/yellow]")
        
        # Save text summary
        txt_file = OUTPUTS_DIR / f"{scan_result.project_name}_{timestamp}_extract.txt"
        try:
            txt_content = self._generate_text_summary(
                scan_result=scan_result,
                selected_files=selected_files,
                case_study=case_study,
                case_study_data=case_study_data,
                total_input_tokens=total_input,
                total_output_tokens=total_output,
            )
            txt_file.write_text(txt_content, encoding="utf-8")
            self.console.print(f"[green]✓[/green] Text saved: {txt_file.name}")
        except Exception as e:
            self.console.print(f"[yellow]⚠️ Could not save text: {e}[/yellow]")
        
        # Save LLM reasoning (both passes)
        reasoning_file = OUTPUTS_DIR / f"{scan_result.project_name}_{timestamp}_reasoning.txt"
        try:
            reasoning_content = self._generate_reasoning_log(
                scan_result=scan_result,
                file_selection_prompt=file_selection_prompt,
                selection_response=selection_response,
                extraction_prompt=extraction_prompt,
                extraction_response=extraction_response,
            )
            reasoning_file.write_text(reasoning_content, encoding="utf-8")
            self.console.print(f"[green]✓[/green] Reasoning saved: {reasoning_file.name}")
        except Exception as e:
            self.console.print(f"[yellow]⚠️ Could not save reasoning: {e}[/yellow]")
        
        self.console.print()

    # =========================================================================
    # /agent Command - New Smart Extraction Pipeline
    # =========================================================================
    async def _handle_agent(self, args: List[str]) -> None:
        """
        Handle /agent command - smart extraction with anchor file detection.
        
        This is the new pipeline:
        1. Step 1: Scan directory structure (same as /extract)
        2. Step 2: LLM detects anchor files/folders (Agreement, Assessment, etc.)
        3. Step 3: (Future) Extract content from anchor files
        """
        # Validate configuration
        errors = validate_config()
        if errors:
            self.console.print("[red]Configuration errors:[/red]")
            for error in errors:
                self.console.print(f"  [red]•[/red] {error}")
            return
        
        # Ensure directories exist
        ensure_directories()
        
        # Find project folder or zip file
        project_path, is_zip = find_project_in_inputs(INPUTS_DIR)
        if not project_path:
            self.console.print(f"[red]No project folder or zip file found in {INPUTS_DIR}/[/red]")
            self.console.print(f"[dim]Please add a project folder or .zip file to {INPUTS_DIR}/ and try again.[/dim]")
            return
        
        # Handle zip extraction
        if is_zip:
            self.console.print(f"\n[cyan]🗜️ Found zip file:[/cyan] {project_path.name}")
            with self.console.status("[cyan]Extracting zip file...[/cyan]"):
                try:
                    project_path = extract_zip_project(project_path)
                    self.console.print(f"[green]✓[/green] Extracted to: {project_path.name}/")
                except Exception as e:
                    self.console.print(f"[red]Failed to extract zip: {e}[/red]")
                    return
        else:
            self.console.print(f"\n[cyan]📁 Found project:[/cyan] {project_path.name}")
        
        self.console.print()
        
        # Initialize LLM client if needed
        if not self.llm_client:
            self.llm_client = OpenAIClient()
        
        # Determine total steps (10 if Azure enabled, 9 if not)
        total_steps = 10 if AZURE_SQL_ENABLED else 9
        
        # =====================================================================
        # STEP 1: Scan Directory Structure
        # =====================================================================
        self.console.print(Panel(
            f"[bold]Step 1/{total_steps}:[/bold] Scanning directory structure",
            border_style="cyan",
        ))
        
        with self.console.status("[cyan]Scanning...[/cyan]"):
            try:
                scan_result = self.scanner.scan(project_path)
            except Exception as e:
                self.console.print(f"[red]Failed to scan directory: {e}[/red]")
                return
        
        self.console.print(f"[green]✓[/green] Found {scan_result.total_files} files in {scan_result.total_folders} folders")
        
        # =====================================================================
        # STEP 2: Anchor File/Folder Detection
        # =====================================================================
        self.console.print(Panel(
            f"[bold]Step 2/{total_steps}:[/bold] Detecting anchor files and folders",
            border_style="cyan",
        ))
        
        system_prompt, user_prompt = get_anchor_detection_prompt(scan_result.to_tree_string())
        
        with self.console.status(f"[cyan]Asking {MODEL} to find anchor files...[/cyan]"):
            try:
                anchor_response = self.llm_client.analyze(
                    system_prompt=system_prompt,
                    user_content=user_prompt,
                )
            except Exception as e:
                self.console.print(f"[red]Failed to detect anchor files: {e}[/red]")
                return
        
        # Parse anchor detection response
        try:
            anchor_data = extract_json_from_response(anchor_response.content)
        except (json.JSONDecodeError, ValueError) as e:
            self.console.print(f"[red]Failed to parse anchor detection: {e}[/red]")
            self.console.print(f"[dim]Response was: {anchor_response.content[:500]}...[/dim]")
            return
        
        # Validate paths against actual files
        anchor_data = self._validate_anchor_paths(anchor_data, scan_result)
        
        # Display anchor detection results
        self._display_anchor_results(anchor_data)
        
        # Show token usage
        self.console.print(f"\n[dim]Tokens: {anchor_response.input_tokens:,} in / {anchor_response.output_tokens:,} out[/dim]")
        
        # =====================================================================
        # STEP 3: Project Scope Extraction (from Agreement)
        # =====================================================================
        self.console.print(Panel(
            f"[bold]Step 3/{total_steps}:[/bold] Extracting Project Scope from Agreement",
            border_style="cyan",
        ))
        
        # Check if Agreement was found
        agreement_info = anchor_data.get("agreement", {})
        if not agreement_info.get("found"):
            self.console.print("[red]❌ No Agreement folder found - cannot extract project scope[/red]")
            self.console.print("[dim]Project scope, fees, and initial categories require the Agreement document.[/dim]")
            
            # Store what we have
            self._last_anchor_data = anchor_data
            self._last_scan_result = scan_result
            self._last_project_path = project_path
            self._last_project_scope = None
            self.console.print()
            return
        
        agreement_path = agreement_info.get("path", "")
        agreement_folder = project_path / agreement_path
        
        self.console.print(f"[green]✓[/green] Found Agreement at: {agreement_path}")
        
        # Find PDF files in the Agreement folder
        pdf_files = []
        if agreement_folder.is_dir():
            # Recursively find all PDFs
            pdf_files = list(agreement_folder.rglob("*.pdf"))
        elif agreement_folder.is_file() and agreement_folder.suffix.lower() == ".pdf":
            pdf_files = [agreement_folder]
        
        if not pdf_files:
            self.console.print("[yellow]⚠️ No PDF files found in Agreement folder[/yellow]")
            self._last_anchor_data = anchor_data
            self._last_scan_result = scan_result
            self._last_project_path = project_path
            self._last_project_scope = None
            self.console.print()
            return
        
        self.console.print(f"[dim]Found {len(pdf_files)} PDF file(s) in Agreement folder[/dim]")
        
        # Extract content from Agreement PDFs (with table preservation)
        agreement_contents = []
        for pdf_file in pdf_files:
            self.console.print(f"  [dim]• Extracting: {pdf_file.name}[/dim]")
            result = extract_pdf_with_tables(pdf_file, max_chars=60000)
            
            if result.success:
                # Include file path for context
                relative_path = pdf_file.relative_to(project_path)
                header = f"\n{'='*60}\nFILE: {relative_path}\n{'='*60}\n"
                agreement_contents.append(header + result.text_content)
                table_count = result.metadata.get("table_count", "0")
                self.console.print(f"    [green]✓[/green] Extracted ({len(result.text_content):,} chars, {table_count} tables)")
            else:
                self.console.print(f"    [yellow]⚠️[/yellow] Failed: {result.error}")
        
        if not agreement_contents:
            self.console.print("[red]❌ Failed to extract content from any Agreement PDF[/red]")
            self._last_anchor_data = anchor_data
            self._last_scan_result = scan_result
            self._last_project_path = project_path
            self._last_project_scope = None
            self.console.print()
            return
        
        # Combine all Agreement content
        combined_agreement = "\n\n".join(agreement_contents)
        self.console.print(f"\n[dim]Total Agreement content: {len(combined_agreement):,} characters[/dim]")
        
        # =====================================================================
        # STEP 3b: Tesseract OCR for Exhibit Tables (image-based tables)
        # =====================================================================
        self.console.print("\n[cyan]📷 Checking for image-based tables (Exhibit A/B)...[/cyan]")
        
        ocr_extractions = []
        for pdf_file in pdf_files:
            # Find pages with Exhibit A or Exhibit B
            exhibit_pages = find_exhibit_pages(pdf_file)
            
            if exhibit_pages:
                self.console.print(f"  [dim]Found {len(exhibit_pages)} exhibit page(s) in {pdf_file.name}[/dim]")
                
                for page_num, exhibit_type in exhibit_pages:
                    exhibit_label = "Exhibit A" if exhibit_type == "exhibit_a" else "Exhibit B"
                    self.console.print(f"    [cyan]📷 OCR'ing {exhibit_label} (page {page_num + 1}) with Tesseract...[/cyan]")
                    
                    try:
                        # Use Tesseract for accurate OCR (no hallucination)
                        table_content = extract_table_with_tesseract(
                            pdf_file, page_num, exhibit_type
                        )
                        
                        if table_content and len(table_content.strip()) > 50:
                            ocr_extractions.append(
                                f"\n{'='*60}\n"
                                f"TESSERACT OCR: {exhibit_label} (Page {page_num + 1})\n"
                                f"{'='*60}\n"
                                f"{table_content}"
                            )
                            self.console.print(f"    [green]✓[/green] Extracted {exhibit_label} table ({len(table_content):,} chars)")
                        else:
                            self.console.print(f"    [yellow]⚠️[/yellow] Could not extract {exhibit_label} table")
                    except Exception as e:
                        self.console.print(f"    [yellow]⚠️[/yellow] Tesseract OCR error: {e}")
        
        # Add OCR extractions to combined content
        if ocr_extractions:
            combined_agreement += "\n\n" + "\n\n".join(ocr_extractions)
            self.console.print(f"[green]✓[/green] Added {len(ocr_extractions)} OCR'd table(s) to extraction")
        else:
            self.console.print("[dim]No image-based tables found (tables may be text-based)[/dim]")
        
        self.console.print(f"\n[dim]Final Agreement content: {len(combined_agreement):,} characters[/dim]")
        
        # Send to LLM for project scope extraction
        system_prompt, user_prompt = get_project_scope_prompt(combined_agreement)
        
        with self.console.status(f"[cyan]Extracting project scope with {MODEL}...[/cyan]"):
            try:
                scope_response = self.llm_client.analyze(
                    system_prompt=system_prompt,
                    user_content=user_prompt,
                )
            except Exception as e:
                self.console.print(f"[red]Failed to extract project scope: {e}[/red]")
                self._last_anchor_data = anchor_data
                self._last_scan_result = scan_result
                self._last_project_path = project_path
                self._last_project_scope = None
                self.console.print()
                return
        
        # Parse the response
        try:
            project_scope_data = extract_json_from_response(scope_response.content)
        except (json.JSONDecodeError, ValueError) as e:
            self.console.print(f"[red]Failed to parse project scope response: {e}[/red]")
            self.console.print(f"[dim]Response was: {scope_response.content[:500]}...[/dim]")
            project_scope_data = {"raw_response": scope_response.content, "parse_error": str(e)}
        
        # Display extraction results
        self._display_project_scope_results(project_scope_data)
        
        # Show token usage
        self.console.print(f"\n[dim]Tokens: {scope_response.input_tokens:,} in / {scope_response.output_tokens:,} out[/dim]")
        
        # Store results for later steps
        self._last_anchor_data = anchor_data
        self._last_scan_result = scan_result
        self._last_project_path = project_path
        self._last_project_scope = project_scope_data
        
        # =====================================================================
        # STEP 4: Client Context Extraction
        # =====================================================================
        self.console.print(Panel(
            f"[bold]Step 4/{total_steps}:[/bold] Extracting Client Context",
            border_style="cyan",
        ))
        
        # Gather content from multiple sources: Assessment, Case Study, Agreement, Kick-off
        client_context_sources = []
        client_context_contents = []
        
        # 1. Assessment folder
        assessment_info = anchor_data.get("assessment", {})
        if assessment_info.get("found"):
            assessment_path = project_path / assessment_info.get("path", "")
            self.console.print(f"[dim]• Reading Assessment: {assessment_info.get('path')}[/dim]")
            assessment_content = self._extract_folder_content(assessment_path, project_path, max_chars=30000)
            if assessment_content:
                client_context_contents.append(assessment_content)
                client_context_sources.append(f"Assessment: {assessment_info.get('path')}")
        
        # 2. Case Study
        case_study_info = anchor_data.get("case_study", {})
        if case_study_info.get("found"):
            case_study_path = project_path / case_study_info.get("path", "")
            self.console.print(f"[dim]• Reading Case Study: {case_study_info.get('path')}[/dim]")
            if case_study_path.is_file():
                result = extract_file_content(case_study_path, max_chars=25000)
                if result.success:
                    relative_path = case_study_path.relative_to(project_path)
                    header = f"\n{'='*60}\nFILE: {relative_path}\n{'='*60}\n"
                    client_context_contents.append(header + result.text_content)
                    client_context_sources.append(f"Case Study: {case_study_info.get('path')}")
            else:
                cs_content = self._extract_folder_content(case_study_path, project_path, max_chars=25000)
                if cs_content:
                    client_context_contents.append(cs_content)
                    client_context_sources.append(f"Case Study: {case_study_info.get('path')}")
        
        # 3. Kick-off
        kickoff_info = anchor_data.get("kickoff", {})
        if kickoff_info.get("found"):
            kickoff_path = project_path / kickoff_info.get("path", "")
            self.console.print(f"[dim]• Reading Kick-off: {kickoff_info.get('path')}[/dim]")
            if kickoff_path.is_file():
                result = extract_file_content(kickoff_path, max_chars=20000)
                if result.success:
                    relative_path = kickoff_path.relative_to(project_path)
                    header = f"\n{'='*60}\nFILE: {relative_path}\n{'='*60}\n"
                    client_context_contents.append(header + result.text_content)
                    client_context_sources.append(f"Kick-off: {kickoff_info.get('path')}")
            else:
                ko_content = self._extract_folder_content(kickoff_path, project_path, max_chars=20000)
                if ko_content:
                    client_context_contents.append(ko_content)
                    client_context_sources.append(f"Kick-off: {kickoff_info.get('path')}")
        
        # 4. Include some Agreement content for client context (already extracted)
        if agreement_contents:
            # Take first 15k chars of agreement for client context
            agreement_snippet = combined_agreement[:15000]
            client_context_contents.append(
                f"\n{'='*60}\nAGREEMENT (Excerpt)\n{'='*60}\n" + agreement_snippet
            )
            client_context_sources.append("Agreement (excerpt)")
        
        combined_client_content = "\n\n".join(client_context_contents)
        self.console.print(f"[dim]Total client context content: {len(combined_client_content):,} characters from {len(client_context_sources)} sources[/dim]")
        
        # 5. Web search for company information (multiple searches for accuracy)
        self.console.print(f"\n[cyan]🌐 Multi-source web search for {scan_result.project_name}...[/cyan]")
        self.console.print("[dim]Running multiple searches to cross-validate information...[/dim]")
        
        web_search_results = []
        search_queries = [
            (f"{scan_result.project_name} company revenue annual sales", "Revenue"),
            (f"{scan_result.project_name} number of employees headcount", "Employees"),
            (f"{scan_result.project_name} locations offices sites facilities", "Locations"),
            (f"{scan_result.project_name} private equity investor backed owner", "PE/Ownership"),
            (f"{scan_result.project_name} company overview industry business", "Company Overview"),
        ]
        
        for query, label in search_queries:
            try:
                with self.console.status(f"[cyan]Searching: {label}...[/cyan]"):
                    response = self.llm_client.web_search(query)
                    if response.content:
                        web_search_results.append(f"\n### Web Search: {label}\nQuery: {query}\n\n{response.content}")
                        self.console.print(f"  [green]✓[/green] {label}: {len(response.content)} chars")
            except Exception as e:
                self.console.print(f"  [yellow]⚠️[/yellow] {label} search failed: {e}")
        
        # Combine all web search results
        if web_search_results:
            web_search_info = "\n\n".join(web_search_results)
            web_search_info = f"""# Web Search Results (Multiple Sources)

IMPORTANT: Cross-validate information across sources. If sources disagree, note the discrepancy and prefer:
1. Official company sources (website, press releases)
2. Reputable business databases (LinkedIn, Crunchbase, PitchBook)
3. News articles from established outlets
4. If values differ significantly, report the range and note uncertainty

{web_search_info}

---
END OF WEB SEARCH RESULTS
When extracting, cite which source provided each data point."""
            self.console.print(f"[green]✓[/green] Total web search content: {len(web_search_info):,} chars from {len(web_search_results)} searches")
        else:
            web_search_info = f"[Web search unavailable - manually lookup {scan_result.project_name}]"
            self.console.print("[yellow]⚠️ All web searches failed[/yellow]")
        
        # 6. Call LLM for client context extraction
        if combined_client_content or web_search_info:
            system_prompt, user_prompt = get_client_context_prompt(
                client_name_hint=scan_result.project_name,
                web_search_results=web_search_info or "(No web search results)",
                document_contents=combined_client_content or "(No document content extracted)",
            )
            
            with self.console.status(f"[cyan]Extracting client context with {MODEL}...[/cyan]"):
                try:
                    client_context_response = self.llm_client.analyze(
                        system_prompt=system_prompt,
                        user_content=user_prompt,
                    )
                except Exception as e:
                    self.console.print(f"[red]Failed to extract client context: {e}[/red]")
                    client_context_data = {"error": str(e)}
                    client_context_response = None
            
            # Parse the response
            if client_context_response:
                try:
                    client_context_data = extract_json_from_response(client_context_response.content)
                except (json.JSONDecodeError, ValueError) as e:
                    self.console.print(f"[red]Failed to parse client context response: {e}[/red]")
                    client_context_data = {"raw_response": client_context_response.content, "parse_error": str(e)}
            
            # Display client context results
            self._display_client_context_results(client_context_data)
            
            # Show token usage
            if client_context_response:
                self.console.print(f"\n[dim]Tokens: {client_context_response.input_tokens:,} in / {client_context_response.output_tokens:,} out[/dim]")
        else:
            self.console.print("[yellow]⚠️ No content available for client context extraction[/yellow]")
            client_context_data = {"error": "No content available"}
        
        # Store client context
        self._last_client_context = client_context_data
        
        # Get client name from extraction (for Step 5)
        extracted_client_name = client_context_data.get("client", {}).get("client_name", scan_result.project_name)
        
        # =====================================================================
        # STEP 5: Engagement Background Extraction
        # =====================================================================
        self.console.print(Panel(
            f"[bold]Step 5/{total_steps}:[/bold] Extracting Engagement Background",
            border_style="cyan",
        ))
        
        # Reuse the same document content from Step 4 (already gathered)
        # Add Project Updates if available
        project_updates_info = anchor_data.get("project_updates", {})
        if project_updates_info.get("found"):
            update_paths = project_updates_info.get("paths", [])
            self.console.print(f"[dim]• Adding {len(update_paths)} Project Update(s) for constraints/challenges[/dim]")
            
            # Read up to 3 most recent project updates
            for update_path in update_paths[:3]:
                update_file = project_path / update_path
                if update_file.exists() and update_file.is_file():
                    result = extract_file_content(update_file, max_chars=10000)
                    if result.success:
                        header = f"\n{'='*60}\nFILE: {update_path}\n{'='*60}\n"
                        client_context_contents.append(header + result.text_content)
                        client_context_sources.append(f"Project Update: {update_path}")
        
        # Rebuild combined content with updates
        combined_engagement_content = "\n\n".join(client_context_contents)
        self.console.print(f"[dim]Total engagement background content: {len(combined_engagement_content):,} characters from {len(client_context_sources)} sources[/dim]")
        
        # Call LLM for engagement background extraction
        if combined_engagement_content:
            system_prompt, user_prompt = get_engagement_background_prompt(
                client_name=extracted_client_name,
                document_contents=combined_engagement_content,
            )
            
            with self.console.status(f"[cyan]Extracting engagement background with {MODEL}...[/cyan]"):
                try:
                    engagement_response = self.llm_client.analyze(
                        system_prompt=system_prompt,
                        user_content=user_prompt,
                    )
                except Exception as e:
                    self.console.print(f"[red]Failed to extract engagement background: {e}[/red]")
                    engagement_background_data = {"error": str(e)}
                    engagement_response = None
            
            # Parse the response
            if engagement_response:
                try:
                    engagement_background_data = extract_json_from_response(engagement_response.content)
                except (json.JSONDecodeError, ValueError) as e:
                    self.console.print(f"[red]Failed to parse engagement background response: {e}[/red]")
                    engagement_background_data = {"raw_response": engagement_response.content, "parse_error": str(e)}
            
            # Display engagement background results
            self._display_engagement_background_results(engagement_background_data)
            
            # Show token usage
            if engagement_response:
                self.console.print(f"\n[dim]Tokens: {engagement_response.input_tokens:,} in / {engagement_response.output_tokens:,} out[/dim]")
        else:
            self.console.print("[yellow]⚠️ No content available for engagement background extraction[/yellow]")
            engagement_background_data = {"error": "No content available"}
        
        # Store engagement background
        self._last_engagement_background = engagement_background_data
        
        # =====================================================================
        # STEP 6: Impact Extraction
        # =====================================================================
        self.console.print(Panel(
            f"[bold]Step 6/{total_steps}:[/bold] Extracting Impact & Results",
            border_style="cyan",
        ))
        
        # Gather content from Case Study, Project Updates, and Project Close Out
        impact_contents = []
        impact_sources = []
        
        # 1. Case Study (primary source for impact)
        case_study_info = anchor_data.get("case_study", {})
        if case_study_info.get("found"):
            case_study_path = project_path / case_study_info.get("path", "")
            self.console.print(f"[dim]• Reading Case Study: {case_study_info.get('path')}[/dim]")
            if case_study_path.is_file():
                result = extract_file_content(case_study_path, max_chars=40000)
                if result.success:
                    relative_path = case_study_path.relative_to(project_path)
                    header = f"\n{'='*60}\nFILE: {relative_path}\n{'='*60}\n"
                    impact_contents.append(header + result.text_content)
                    impact_sources.append(f"Case Study: {case_study_info.get('path')}")
            else:
                cs_content = self._extract_folder_content(case_study_path, project_path, max_chars=40000)
                if cs_content:
                    impact_contents.append(cs_content)
                    impact_sources.append(f"Case Study: {case_study_info.get('path')}")
        
        # 2. Project Close Out (often has final results)
        close_out_info = anchor_data.get("project_close_out", {})
        if close_out_info.get("found"):
            close_out_path = project_path / close_out_info.get("path", "")
            self.console.print(f"[dim]• Reading Project Close Out: {close_out_info.get('path')}[/dim]")
            if close_out_path.is_file():
                result = extract_file_content(close_out_path, max_chars=30000)
                if result.success:
                    relative_path = close_out_path.relative_to(project_path)
                    header = f"\n{'='*60}\nFILE: {relative_path}\n{'='*60}\n"
                    impact_contents.append(header + result.text_content)
                    impact_sources.append(f"Project Close Out: {close_out_info.get('path')}")
            else:
                co_content = self._extract_folder_content(close_out_path, project_path, max_chars=30000)
                if co_content:
                    impact_contents.append(co_content)
                    impact_sources.append(f"Project Close Out: {close_out_info.get('path')}")
        
        # 3. Project Updates (for additional context, use most recent ones)
        project_updates_info = anchor_data.get("project_updates", {})
        if project_updates_info.get("found"):
            update_paths = project_updates_info.get("paths", [])
            self.console.print(f"[dim]• Reading {min(len(update_paths), 3)} most recent Project Update(s)[/dim]")
            
            for update_path in update_paths[:3]:
                update_file = project_path / update_path
                if update_file.exists() and update_file.is_file():
                    result = extract_file_content(update_file, max_chars=15000)
                    if result.success:
                        header = f"\n{'='*60}\nFILE: {update_path}\n{'='*60}\n"
                        impact_contents.append(header + result.text_content)
                        impact_sources.append(f"Project Update: {update_path}")
        
        combined_impact_content = "\n\n".join(impact_contents)
        self.console.print(f"[dim]Total impact content: {len(combined_impact_content):,} characters from {len(impact_sources)} sources[/dim]")
        
        # Get context from previous steps for comparison
        exhibit_a = project_scope_data.get("exhibit_a", {})
        initial_categories = ", ".join(exhibit_a.get("initial_categories", []))
        addressable_spend = exhibit_a.get("total_addressable_spend", 0) or 0
        savings_low = exhibit_a.get("savings_estimate_low", 0) or 0
        savings_high = exhibit_a.get("savings_estimate_high", 0) or 0
        
        # Call LLM for impact extraction
        if combined_impact_content:
            system_prompt, user_prompt = get_impact_prompt(
                client_name=extracted_client_name,
                document_contents=combined_impact_content,
                initial_categories=initial_categories,
                addressable_spend=addressable_spend,
                savings_low=savings_low,
                savings_high=savings_high,
            )
            
            with self.console.status(f"[cyan]Extracting impact with {MODEL}...[/cyan]"):
                try:
                    impact_response = self.llm_client.analyze(
                        system_prompt=system_prompt,
                        user_content=user_prompt,
                    )
                except Exception as e:
                    self.console.print(f"[red]Failed to extract impact: {e}[/red]")
                    impact_data = {"error": str(e)}
                    impact_response = None
            
            # Parse the response
            if impact_response:
                try:
                    impact_data = extract_json_from_response(impact_response.content)
                except (json.JSONDecodeError, ValueError) as e:
                    self.console.print(f"[red]Failed to parse impact response: {e}[/red]")
                    impact_data = {"raw_response": impact_response.content, "parse_error": str(e)}
            
            # Display impact results
            self._display_impact_results(impact_data)
            
            # Show token usage
            if impact_response:
                self.console.print(f"\n[dim]Tokens: {impact_response.input_tokens:,} in / {impact_response.output_tokens:,} out[/dim]")
        else:
            self.console.print("[yellow]⚠️ No Case Study, Project Updates, or Close Out found for impact extraction[/yellow]")
            self.console.print("[dim]Impact data requires completed project documentation.[/dim]")
            impact_data = {"error": "No impact sources available"}
        
        # Store impact data
        self._last_impact = impact_data
        
        # =====================================================================
        # STEP 7: Categories Extraction (Detailed)
        # =====================================================================
        self.console.print(Panel(
            f"[bold]Step 7/{total_steps}:[/bold] Extracting Detailed Category Information",
            border_style="cyan",
        ))
        
        # Get category list from Impact results
        category_list_from_impact = impact_data.get("impact", {}).get("category_results", [])
        
        # Fallback: Get from last 3 project updates if Impact doesn't have categories
        if not category_list_from_impact:
            self.console.print("[yellow]⚠️ No category list from Impact, checking Project Updates...[/yellow]")
            # We already have project updates content from Impact step
            # The LLM will need to find categories from that content
            category_list_str = "(No category list available - extract from Project Updates content)"
        else:
            # Format category list for prompt
            category_list_items = []
            for cat in category_list_from_impact:
                name = cat.get("category_name", "Unknown")
                savings = cat.get("annual_savings", 0)
                status = cat.get("status", "unknown")
                notes = cat.get("status_notes", "")
                category_list_items.append(f"- {name}: ${savings:,.0f} [{status}] {notes}")
            category_list_str = "\n".join(category_list_items)
            self.console.print(f"[green]✓[/green] Found {len(category_list_from_impact)} categories from Impact")
        
        # Get Exhibit A data from Project Scope
        exhibit_a_data = project_scope_data.get("exhibit_a", {})
        if exhibit_a_data:
            exhibit_a_str = json.dumps(exhibit_a_data, indent=2)
            self.console.print(f"[green]✓[/green] Exhibit A data available (baseline spend)")
        else:
            exhibit_a_str = "(No Exhibit A data available)"
            self.console.print("[yellow]⚠️ No Exhibit A data available[/yellow]")
        
        # Find and read category folders
        self.console.print("\n[cyan]📁 Reading category folders...[/cyan]")
        category_folder_contents = []
        categories_folder = project_path / "Categories"
        
        # Check for alternate folder names
        if not categories_folder.exists():
            categories_folder = project_path / "Category"
        if not categories_folder.exists():
            # Try to find any folder with "categor" in the name
            for folder in project_path.iterdir():
                if folder.is_dir() and "categor" in folder.name.lower():
                    categories_folder = folder
                    break
        
        if categories_folder.exists() and categories_folder.is_dir():
            # Get all category subfolders
            category_subfolders = [f for f in categories_folder.iterdir() if f.is_dir()]
            self.console.print(f"[dim]Found {len(category_subfolders)} category folders[/dim]")
            
            for cat_folder in category_subfolders[:15]:  # Limit to 15 categories
                self.console.print(f"  [dim]• Reading: {cat_folder.name}[/dim]")
                cat_content = self._extract_folder_content(cat_folder, project_path, max_chars=15000)
                if cat_content:
                    category_folder_contents.append(
                        f"\n{'='*60}\nCATEGORY FOLDER: {cat_folder.name}\n{'='*60}\n{cat_content}"
                    )
        else:
            self.console.print("[dim]No Categories folder found[/dim]")
        
        # Also check for Wave 2 categories
        wave2_categories = project_path / "Wave 2" / "Categories"
        if wave2_categories.exists():
            self.console.print(f"[dim]Found Wave 2 categories folder[/dim]")
            for cat_folder in wave2_categories.iterdir():
                if cat_folder.is_dir():
                    self.console.print(f"  [dim]• Reading Wave 2: {cat_folder.name}[/dim]")
                    cat_content = self._extract_folder_content(cat_folder, project_path, max_chars=10000)
                    if cat_content:
                        category_folder_contents.append(
                            f"\n{'='*60}\nCATEGORY FOLDER (Wave 2): {cat_folder.name}\n{'='*60}\n{cat_content}"
                        )
        
        combined_category_content = "\n\n".join(category_folder_contents)
        self.console.print(f"[dim]Total category folder content: {len(combined_category_content):,} characters[/dim]")
        
        # Also include Close-out and Project Update content for vendor/lever info
        if combined_impact_content:
            combined_category_content = combined_impact_content + "\n\n" + combined_category_content
        
        # Call LLM for categories extraction
        if category_list_str or combined_category_content:
            from datetime import date
            extraction_date = date.today().isoformat()
            
            system_prompt, user_prompt = get_categories_prompt(
                client_name=extracted_client_name,
                category_list=category_list_str,
                exhibit_a_data=exhibit_a_str,
                category_folder_contents=combined_category_content or "(No category folder content)",
                extraction_date=extraction_date,
            )
            
            with self.console.status(f"[cyan]Extracting detailed category info with {MODEL}...[/cyan]"):
                try:
                    categories_response = self.llm_client.analyze(
                        system_prompt=system_prompt,
                        user_content=user_prompt,
                    )
                except Exception as e:
                    self.console.print(f"[red]Failed to extract categories: {e}[/red]")
                    categories_data = {"error": str(e)}
                    categories_response = None
            
            # Parse the response
            if categories_response:
                try:
                    categories_data = extract_json_from_response(categories_response.content)
                except (json.JSONDecodeError, ValueError) as e:
                    self.console.print(f"[red]Failed to parse categories response: {e}[/red]")
                    categories_data = {"raw_response": categories_response.content, "parse_error": str(e)}
            
            # Display categories results
            self._display_categories_results(categories_data)
            
            # Show token usage
            if categories_response:
                self.console.print(f"\n[dim]Tokens: {categories_response.input_tokens:,} in / {categories_response.output_tokens:,} out[/dim]")
        else:
            self.console.print("[yellow]⚠️ No category data available for extraction[/yellow]")
            categories_data = {"error": "No category data available"}
        
        # Store categories data
        self._last_categories = categories_data
        
        # =====================================================================
        # STEP 8: Case Study Content Generation
        # =====================================================================
        self.console.print(Panel(
            f"[bold]Step 8/{total_steps}:[/bold] Generating Case Study Content",
            border_style="cyan",
        ))
        
        self.console.print("[dim]Synthesizing all extracted data into case study content...[/dim]")
        
        # Prepare all data from previous steps as JSON strings
        project_scope_str = json.dumps(project_scope_data, indent=2) if project_scope_data else "{}"
        client_context_str = json.dumps(client_context_data, indent=2) if client_context_data else "{}"
        engagement_background_str = json.dumps(engagement_background_data, indent=2) if engagement_background_data else "{}"
        impact_str = json.dumps(impact_data, indent=2) if impact_data else "{}"
        categories_str = json.dumps(categories_data, indent=2) if categories_data else "{}"
        
        # Show what data we have
        data_status = []
        if project_scope_data and "error" not in project_scope_data:
            data_status.append("Project Scope ✓")
        if client_context_data and "error" not in client_context_data:
            data_status.append("Client Context ✓")
        if engagement_background_data and "error" not in engagement_background_data:
            data_status.append("Engagement Background ✓")
        if impact_data and "error" not in impact_data:
            data_status.append("Impact ✓")
        if categories_data and "error" not in categories_data:
            data_status.append("Categories ✓")
        
        self.console.print(f"[green]Data available:[/green] {', '.join(data_status)}")
        
        # Call LLM for case study generation
        system_prompt, user_prompt = get_case_study_generation_prompt(
            project_scope_data=project_scope_str,
            client_context_data=client_context_str,
            engagement_background_data=engagement_background_str,
            impact_data=impact_str,
            categories_data=categories_str,
        )
        
        with self.console.status(f"[cyan]Generating case study content with {MODEL}...[/cyan]"):
            try:
                case_study_response = self.llm_client.analyze(
                    system_prompt=system_prompt,
                    user_content=user_prompt,
                )
            except Exception as e:
                self.console.print(f"[red]Failed to generate case study: {e}[/red]")
                case_study_data = {"error": str(e)}
                case_study_response = None
        
        # Parse the response
        if case_study_response:
            try:
                case_study_data = extract_json_from_response(case_study_response.content)
            except (json.JSONDecodeError, ValueError) as e:
                self.console.print(f"[red]Failed to parse case study response: {e}[/red]")
                case_study_data = {"raw_response": case_study_response.content, "parse_error": str(e)}
        
        # Display case study results
        self._display_case_study_packaging_results(case_study_data)
        
        # Show token usage
        if case_study_response:
            self.console.print(f"\n[dim]Tokens: {case_study_response.input_tokens:,} in / {case_study_response.output_tokens:,} out[/dim]")
        
        # Store case study data
        self._last_case_study = case_study_data
        
        # =====================================================================
        # STEP 9: Supplier Battlecards
        # =====================================================================
        self.console.print(Panel(
            f"[bold]Step 9/{total_steps}:[/bold] Generating Supplier Battlecards",
            border_style="cyan",
        ))
        
        self.console.print("[dim]Analyzing complex categories for strategic supplier information...[/dim]")
        
        # Build categories summary from Step 7 results
        categories_list = categories_data.get("categories", [])
        if categories_list:
            categories_summary_items = []
            for cat in categories_list:
                cat_name = cat.get("category_name", cat.get("category_label", "Unknown"))
                vendors_before = cat.get("vendors_before", [])
                vendors_after = cat.get("vendors_after", [])
                
                # Handle baseline_spend - could be a dict with 'amount' or a plain number
                baseline_raw = cat.get("baseline_spend", 0)
                if isinstance(baseline_raw, dict):
                    baseline = baseline_raw.get("amount", 0) or 0
                else:
                    baseline = baseline_raw or 0
                
                # Handle savings - could be annual_savings or savings_annual_run_rate
                savings_raw = cat.get("annual_savings", cat.get("savings_annual_run_rate", 0))
                if isinstance(savings_raw, dict):
                    savings = savings_raw.get("amount", 0) or 0
                else:
                    savings = savings_raw or 0
                
                levers = cat.get("levers", [])
                
                summary_item = f"""
Category: {cat_name}
  Vendors Before: {', '.join(vendors_before) if vendors_before else 'N/A'}
  Vendors After: {', '.join(vendors_after) if vendors_after else 'N/A'}
  Baseline Spend: ${baseline:,.0f}
  Savings: ${savings:,.0f}
  Levers: {', '.join(levers) if levers else 'N/A'}
"""
                categories_summary_items.append(summary_item)
            
            categories_summary_str = "\n".join(categories_summary_items)
            self.console.print(f"[green]✓[/green] Found {len(categories_list)} categories from Step 7")
        else:
            categories_summary_str = "(No categories data available from Step 7)"
            self.console.print("[yellow]⚠️ No categories data available[/yellow]")
        
        # Reuse category folder content from Step 7 (already in combined_category_content)
        # If not available, we need to re-extract
        if not combined_category_content:
            self.console.print("[dim]Re-reading category folders for battlecard extraction...[/dim]")
            category_folder_contents_bc = []
            categories_folder = project_path / "Categories"
            
            if not categories_folder.exists():
                categories_folder = project_path / "Category"
            if not categories_folder.exists():
                for folder in project_path.iterdir():
                    if folder.is_dir() and "categor" in folder.name.lower():
                        categories_folder = folder
                        break
            
            if categories_folder.exists() and categories_folder.is_dir():
                for cat_folder in categories_folder.iterdir():
                    if cat_folder.is_dir():
                        cat_content = self._extract_folder_content(cat_folder, project_path, max_chars=20000)
                        if cat_content:
                            category_folder_contents_bc.append(
                                f"\n{'='*60}\nCATEGORY FOLDER: {cat_folder.name}\n{'='*60}\n{cat_content}"
                            )
            
            combined_category_content = "\n\n".join(category_folder_contents_bc)
        
        self.console.print(f"[dim]Category folder content: {len(combined_category_content):,} characters[/dim]")
        
        # Call LLM for supplier battlecards
        if categories_summary_str and combined_category_content:
            system_prompt, user_prompt = get_supplier_battlecards_prompt(
                client_name=extracted_client_name,
                categories_summary=categories_summary_str,
                category_folder_contents=combined_category_content,
            )
            
            with self.console.status(f"[cyan]Generating supplier battlecards with {MODEL}...[/cyan]"):
                try:
                    battlecards_response = self.llm_client.analyze(
                        system_prompt=system_prompt,
                        user_content=user_prompt,
                    )
                except Exception as e:
                    self.console.print(f"[red]Failed to generate battlecards: {e}[/red]")
                    battlecards_data = {"error": str(e)}
                    battlecards_response = None
            
            # Parse the response
            if battlecards_response:
                try:
                    battlecards_data = extract_json_from_response(battlecards_response.content)
                except (json.JSONDecodeError, ValueError) as e:
                    self.console.print(f"[red]Failed to parse battlecards response: {e}[/red]")
                    battlecards_data = {"raw_response": battlecards_response.content, "parse_error": str(e)}
            
            # Display battlecards results
            self._display_battlecards_results(battlecards_data)
            
            # Show token usage
            if battlecards_response:
                self.console.print(f"\n[dim]Tokens: {battlecards_response.input_tokens:,} in / {battlecards_response.output_tokens:,} out[/dim]")
        else:
            self.console.print("[yellow]⚠️ Insufficient data for supplier battlecard generation[/yellow]")
            battlecards_data = {"error": "Insufficient data"}
        
        # Store battlecards data
        self._last_battlecards = battlecards_data
        
        # =====================================================================
        # Save Combined Output
        # =====================================================================
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Save project scope
        scope_file = OUTPUTS_DIR / f"{scan_result.project_name}_{timestamp}_project_scope.json"
        try:
            scope_file.write_text(json.dumps(project_scope_data, indent=2), encoding="utf-8")
            self.console.print(f"\n[green]✓[/green] Project Scope saved: {scope_file.name}")
        except Exception as e:
            self.console.print(f"[yellow]⚠️ Could not save project scope: {e}[/yellow]")
        
        # Save client context
        client_file = OUTPUTS_DIR / f"{scan_result.project_name}_{timestamp}_client_context.json"
        try:
            client_file.write_text(json.dumps(client_context_data, indent=2), encoding="utf-8")
            self.console.print(f"[green]✓[/green] Client Context saved: {client_file.name}")
        except Exception as e:
            self.console.print(f"[yellow]⚠️ Could not save client context: {e}[/yellow]")
        
        # Save engagement background
        engagement_file = OUTPUTS_DIR / f"{scan_result.project_name}_{timestamp}_engagement_background.json"
        try:
            engagement_file.write_text(json.dumps(engagement_background_data, indent=2), encoding="utf-8")
            self.console.print(f"[green]✓[/green] Engagement Background saved: {engagement_file.name}")
        except Exception as e:
            self.console.print(f"[yellow]⚠️ Could not save engagement background: {e}[/yellow]")
        
        # Save impact
        impact_file = OUTPUTS_DIR / f"{scan_result.project_name}_{timestamp}_impact.json"
        try:
            impact_file.write_text(json.dumps(impact_data, indent=2), encoding="utf-8")
            self.console.print(f"[green]✓[/green] Impact saved: {impact_file.name}")
        except Exception as e:
            self.console.print(f"[yellow]⚠️ Could not save impact: {e}[/yellow]")
        
        # Save categories
        categories_file = OUTPUTS_DIR / f"{scan_result.project_name}_{timestamp}_categories.json"
        try:
            categories_file.write_text(json.dumps(categories_data, indent=2), encoding="utf-8")
            self.console.print(f"[green]✓[/green] Categories saved: {categories_file.name}")
        except Exception as e:
            self.console.print(f"[yellow]⚠️ Could not save categories: {e}[/yellow]")
        
        # Save case study content
        case_study_file = OUTPUTS_DIR / f"{scan_result.project_name}_{timestamp}_case_study.json"
        try:
            case_study_file.write_text(json.dumps(case_study_data, indent=2), encoding="utf-8")
            self.console.print(f"[green]✓[/green] Case Study saved: {case_study_file.name}")
        except Exception as e:
            self.console.print(f"[yellow]⚠️ Could not save case study: {e}[/yellow]")
        
        # Save supplier battlecards
        battlecards_file = OUTPUTS_DIR / f"{scan_result.project_name}_{timestamp}_battlecards.json"
        try:
            battlecards_file.write_text(json.dumps(battlecards_data, indent=2), encoding="utf-8")
            self.console.print(f"[green]✓[/green] Supplier Battlecards saved: {battlecards_file.name}")
        except Exception as e:
            self.console.print(f"[yellow]⚠️ Could not save battlecards: {e}[/yellow]")
        
        # =====================================================================
        # STEP 10: Save to Azure SQL Database (if enabled)
        # =====================================================================
        if AZURE_SQL_ENABLED:
            self.console.print(Panel(
                f"[bold]Step 10/{total_steps}:[/bold] Saving to Azure SQL Database",
                border_style="cyan",
            ))
            
            # Validate Azure config
            azure_errors = validate_azure_config()
            if azure_errors:
                self.console.print("[red]Azure SQL configuration errors:[/red]")
                for error in azure_errors:
                    self.console.print(f"  [red]•[/red] {error}")
            else:
                try:
                    connection_string = get_azure_connection_string()
                    extraction_dt = datetime.strptime(timestamp, "%Y%m%d_%H%M%S")
                    
                    # Define blocking database operations to run in thread pool
                    def save_to_azure_sync():
                        """Run all blocking pyodbc operations in a separate thread."""
                        import time
                        
                        writer = AzureSQLWriter(
                            connection_string=connection_string,
                            table_name=AZURE_SQL_TABLE,
                        )
                        
                        # Connect with retries
                        writer.connect(retries=3)
                        
                        # Ensure table exists
                        writer.ensure_table_exists()
                        
                        # Save to database
                        row_id = writer.save_extraction(
                            client_name=extracted_client_name,
                            project_scope=project_scope_data or {},
                            client_context=client_context_data or {},
                            engagement_background=engagement_background_data or {},
                            impact=impact_data or {},
                            categories=categories_data or {},
                            case_study=case_study_data or {},
                            battlecards=battlecards_data or {},
                            extraction_timestamp=extraction_dt,
                            upsert=True,
                        )
                        
                        writer.close()
                        return row_id
                    
                    # Run blocking database operations in thread pool
                    # This prevents pyodbc from blocking the asyncio event loop
                    self.console.print("[cyan]Connecting to Azure SQL (in background thread)...[/cyan]")
                    row_id = await asyncio.to_thread(save_to_azure_sync)
                    self.console.print(f"[green]✓[/green] Saved to Azure SQL (client: {extracted_client_name})")
                        
                except ImportError as e:
                    self.console.print(f"[yellow]⚠️ Azure SQL driver not available: {e}[/yellow]")
                    self.console.print("[dim]Install with: pip install pyodbc[/dim]")
                    self.console.print("[dim]Also install ODBC Driver 18 for SQL Server[/dim]")
                except Exception as e:
                    self.console.print(f"[red]❌ Failed to save to Azure SQL: {e}[/red]")
                    self.console.print("[dim]You can manually upload the JSON files later.[/dim]")
        
        self.console.print()
    
    def _extract_folder_content(self, folder_path: Path, project_path: Path, max_chars: int = 30000) -> str:
        """
        Extract content from all files in a folder.
        
        Args:
            folder_path: Path to the folder
            project_path: Root project path for relative paths
            max_chars: Maximum total characters to extract
            
        Returns:
            Combined content from all files in the folder
        """
        if not folder_path.exists() or not folder_path.is_dir():
            return ""
        
        contents = []
        chars_remaining = max_chars
        
        # Get all supported files in the folder
        supported_extensions = {".pdf", ".pptx", ".xlsx", ".docx", ".txt"}
        files = []
        for ext in supported_extensions:
            files.extend(folder_path.rglob(f"*{ext}"))
        
        # Sort by modification time (newest first)
        files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        
        for file_path in files:
            if chars_remaining <= 0:
                break
            
            # Calculate per-file limit
            per_file_limit = min(chars_remaining, max_chars // max(1, len(files)))
            
            result = extract_file_content(file_path, max_chars=per_file_limit)
            
            if result.success and result.text_content:
                try:
                    relative_path = file_path.relative_to(project_path)
                except ValueError:
                    relative_path = file_path.name
                
                header = f"\n{'='*60}\nFILE: {relative_path}\n{'='*60}\n"
                content_with_header = header + result.text_content
                contents.append(content_with_header)
                chars_remaining -= len(content_with_header)
        
        return "\n".join(contents)
    
    def _display_client_context_results(self, data: dict) -> None:
        """Display client context extraction results."""
        self.console.print("\n[bold cyan]═══ CLIENT CONTEXT ═══[/bold cyan]\n")
        
        # Check for errors
        if "error" in data:
            self.console.print(f"[red]❌ Error: {data['error']}[/red]")
            return
        
        if "parse_error" in data:
            self.console.print(f"[red]❌ Parse error: {data['parse_error']}[/red]")
            return
        
        # Client identification
        client = data.get("client", {})
        if client:
            self.console.print("[bold green]Client Identification[/bold green]")
            
            if client.get("client_name"):
                self.console.print(f"  [cyan]Name:[/cyan] {client['client_name']}")
            
            if client.get("primary_industry_sector"):
                self.console.print(f"  [cyan]Primary Industry Sector:[/cyan] {client['primary_industry_sector']}")
            
            industry = client.get("industry_primary", "")
            if client.get("industry_secondary"):
                industry += f" / {client['industry_secondary']}"
            if industry:
                self.console.print(f"  [cyan]Secondary Industry:[/cyan] {industry}")
            
            if client.get("business_model"):
                self.console.print(f"  [cyan]Business Model:[/cyan] {client['business_model']}")
            
            if client.get("sponsor_pe_firm"):
                self.console.print(f"  [cyan]PE Sponsor:[/cyan] {client['sponsor_pe_firm']}")
            else:
                self.console.print(f"  [cyan]PE Sponsor:[/cyan] [dim](Not PE-backed)[/dim]")
            
            if client.get("client_history"):
                history = client["client_history"]
                if len(history) > 150:
                    history = history[:150] + "..."
                self.console.print(f"  [cyan]Background:[/cyan] {history}")
            
            self.console.print()
        
        # Size metrics
        size_metrics = data.get("size_metrics", {})
        if size_metrics:
            self.console.print("[bold green]Size Metrics[/bold green]")
            
            conf_icons = {"high": "🟢", "medium": "🟡", "low": "🔴"}
            
            # Revenue
            revenue = size_metrics.get("revenue")
            if revenue and revenue.get("amount"):
                conf = conf_icons.get(revenue.get("confidence", ""), "⚪")
                source = revenue.get("source", "unknown")
                self.console.print(f"  [cyan]Revenue:[/cyan] ${revenue['amount']:,.0f} {conf}")
                self.console.print(f"    [dim]Source: {source}[/dim]")
                if revenue.get("notes"):
                    self.console.print(f"    [dim]Notes: {revenue['notes']}[/dim]")
            
            # EBITDA
            ebitda = size_metrics.get("ebitda")
            if ebitda and ebitda.get("amount"):
                conf = conf_icons.get(ebitda.get("confidence", ""), "⚪")
                self.console.print(f"  [cyan]EBITDA:[/cyan] ${ebitda['amount']:,.0f} {conf}")
            
            # Locations
            locations = size_metrics.get("locations")
            if locations and locations.get("count"):
                conf = conf_icons.get(locations.get("confidence", ""), "⚪")
                source = locations.get("source", "unknown")
                self.console.print(f"  [cyan]Locations:[/cyan] {locations['count']} {conf}")
                self.console.print(f"    [dim]Source: {source}[/dim]")
                if locations.get("notes"):
                    self.console.print(f"    [dim]Notes: {locations['notes']}[/dim]")
            
            # Employees
            employees = size_metrics.get("employees")
            if employees and employees.get("count"):
                conf = conf_icons.get(employees.get("confidence", ""), "⚪")
                source = employees.get("source", "unknown")
                self.console.print(f"  [cyan]Employees:[/cyan] {employees['count']:,} {conf}")
                self.console.print(f"    [dim]Source: {source}[/dim]")
            
            self.console.print()
        
        # Extraction sources
        sources = data.get("extraction_sources", [])
        if sources:
            self.console.print("[bold green]Sources Used[/bold green]")
            for src in sources:
                self.console.print(f"  [dim]• {src}[/dim]")
            self.console.print()
        
        # Extraction notes
        notes = data.get("extraction_notes", [])
        if notes:
            self.console.print("[yellow]Extraction Notes:[/yellow]")
            for note in notes:
                self.console.print(f"  ⚠️ {note}")
            self.console.print()
    
    def _display_case_study_packaging_results(self, data: dict) -> None:
        """Display case study packaging/generation results."""
        self.console.print("\n[bold magenta]═══ CASE STUDY CONTENT ═══[/bold magenta]\n")
        
        # Check for errors
        if "error" in data:
            self.console.print(f"[red]❌ Error: {data['error']}[/red]")
            return
        
        if "parse_error" in data:
            self.console.print(f"[red]❌ Parse error: {data['parse_error']}[/red]")
            return
        
        packaging = data.get("case_study_packaging", {})
        if not packaging:
            self.console.print("[yellow]No case study content generated[/yellow]")
            return
        
        # Case study ready assessment
        is_ready = packaging.get("case_study_ready", False)
        readiness_notes = packaging.get("readiness_notes", "")
        
        if is_ready:
            self.console.print("[bold green]✅ CASE STUDY READY[/bold green]")
        else:
            self.console.print("[bold yellow]⚠️ CASE STUDY NOT READY[/bold yellow]")
        
        if readiness_notes:
            self.console.print(f"[dim]{readiness_notes}[/dim]")
        self.console.print()
        
        # Headline
        headline = packaging.get("headline")
        if headline:
            self.console.print("[bold magenta]📣 HEADLINE[/bold magenta]")
            self.console.print(f"[bold]{headline}[/bold]")
            self.console.print()
        
        # Client Problem Statement
        problem = packaging.get("client_problem_statement")
        if problem:
            self.console.print("[bold magenta]🎯 CLIENT PROBLEM[/bold magenta]")
            self.console.print(f"{problem}")
            self.console.print()
        
        # Client Problem - Anonymized
        problem_anon = packaging.get("client_problem_anonymized")
        if problem_anon:
            self.console.print("[bold magenta]🎯 CLIENT PROBLEM (ANONYMIZED)[/bold magenta]")
            self.console.print(f"{problem_anon}")
            self.console.print()
        
        # Approach Summary
        approach = packaging.get("approach_summary", [])
        if approach:
            self.console.print("[bold magenta]🔧 APPROACH[/bold magenta]")
            for bullet in approach:
                self.console.print(f"  • {bullet}")
            self.console.print()
        
        # Top Levers
        levers = packaging.get("top_levers", [])
        if levers:
            self.console.print("[bold magenta]⚡ TOP LEVERS[/bold magenta]")
            for i, lever in enumerate(levers, 1):
                self.console.print(f"  {i}. {lever}")
            self.console.print()
        
        # Value Delivered
        value = packaging.get("value_delivered_blurb")
        if value:
            self.console.print("[bold magenta]💰 VALUE DELIVERED[/bold magenta]")
            self.console.print(f"{value}")
            self.console.print()
        
        # Where We Were Unique
        unique = packaging.get("where_we_were_unique", [])
        if unique:
            self.console.print("[bold magenta]⭐ WHERE WE WERE UNIQUE[/bold magenta]")
            for item in unique:
                self.console.print(f"  ✓ {item}")
            self.console.print()
        
        # Generation notes
        notes = data.get("generation_notes", [])
        if notes:
            self.console.print("[dim]Generation Notes:[/dim]")
            for note in notes:
                self.console.print(f"  [dim]• {note}[/dim]")
            self.console.print()
    
    def _display_categories_results(self, data: dict) -> None:
        """Display categories extraction results."""
        self.console.print("\n[bold cyan]═══ DETAILED CATEGORIES ═══[/bold cyan]\n")
        
        # Check for errors
        if "error" in data:
            self.console.print(f"[red]❌ Error: {data['error']}[/red]")
            return
        
        if "parse_error" in data:
            self.console.print(f"[red]❌ Parse error: {data['parse_error']}[/red]")
            return
        
        categories = data.get("categories", [])
        if not categories:
            self.console.print("[yellow]No categories extracted[/yellow]")
            return
        
        # Status icons
        status_icons = {
            "implemented": "✅",
            "negotiated": "🤝",
            "in_progress": "🔄",
            "in progress": "🔄",
            "identified": "🎯",
            "not_pursued": "❌",
            "not pursued": "❌",
        }
        
        conf_icons = {"high": "🟢", "medium": "🟡", "low": "🔴"}
        
        for cat in categories:
            name = cat.get("category_label", "Unknown")
            status = cat.get("status", "unknown")
            icon = status_icons.get(status.lower().replace("_", " "), "❓")
            
            self.console.print(f"{icon} [bold]{name}[/bold] [{status}]")
            
            # Vendors
            vendors_before = cat.get("vendors_before", [])
            vendors_after = cat.get("vendors_after", [])
            if vendors_before or vendors_after:
                if vendors_before:
                    self.console.print(f"   [dim]Vendors Before:[/dim] {', '.join(vendors_before)}")
                if vendors_after:
                    self.console.print(f"   [green]Vendors After:[/green] {', '.join(vendors_after)}")
            
            # Levers
            levers = cat.get("levers", [])
            if levers:
                self.console.print(f"   [cyan]Levers:[/cyan] {', '.join(levers)}")
            
            # Financials
            baseline = cat.get("baseline_spend")
            savings = cat.get("savings_annual_run_rate")
            pct = cat.get("savings_percentage")
            
            if baseline and baseline.get("amount"):
                conf = conf_icons.get(baseline.get("confidence", ""), "⚪")
                self.console.print(f"   [dim]Baseline:[/dim] ${baseline['amount']:,.0f} {conf}")
            
            if savings and savings.get("amount"):
                conf = conf_icons.get(savings.get("confidence", ""), "⚪")
                pct_str = f" ({pct:.1f}%)" if pct else ""
                self.console.print(f"   [green]Savings:[/green] ${savings['amount']:,.0f}{pct_str} {conf}")
            
            # Constraints (if any)
            constraints = cat.get("constraints", {})
            if constraints and any(constraints.values()):
                self.console.print(f"   [yellow]Constraints:[/yellow]")
                for ctype, cval in constraints.items():
                    if cval:
                        ctype_display = ctype.replace("_", " ").title()
                        self.console.print(f"      • {ctype_display}: {cval}")
            
            # Notes
            notes = cat.get("notes")
            if notes:
                self.console.print(f"   [dim]Notes: {notes}[/dim]")
            
            self.console.print()  # Blank line between categories
        
        # Summary
        summary = data.get("categories_summary", {})
        if summary:
            self.console.print("[bold green]Category Summary[/bold green]")
            
            total = summary.get("total_count", len(categories))
            implemented = summary.get("implemented_count", 0)
            in_progress = summary.get("in_progress_count", 0)
            
            self.console.print(f"  Total Categories: {total}")
            self.console.print(f"  ✅ Implemented: {implemented}")
            self.console.print(f"  🔄 In Progress: {in_progress}")
            
            total_baseline = summary.get("total_baseline_spend")
            total_savings = summary.get("total_savings")
            avg_pct = summary.get("average_savings_percentage")
            
            if total_baseline:
                self.console.print(f"  Total Baseline Spend: ${total_baseline:,.0f}")
            if total_savings:
                self.console.print(f"  Total Savings: [green]${total_savings:,.0f}[/green]")
            if avg_pct:
                self.console.print(f"  Average Savings %: {avg_pct:.1f}%")
            
            self.console.print()
        
        # Extraction sources
        sources = data.get("extraction_sources", [])
        if sources:
            self.console.print("[bold green]Sources Used[/bold green]")
            for src in sources[:5]:  # Limit to 5
                self.console.print(f"  [dim]• {src}[/dim]")
            if len(sources) > 5:
                self.console.print(f"  [dim]... and {len(sources) - 5} more[/dim]")
            self.console.print()
        
        # Extraction notes
        notes = data.get("extraction_notes", [])
        if notes:
            self.console.print("[yellow]Extraction Notes:[/yellow]")
            for note in notes:
                self.console.print(f"  ⚠️ {note}")
            self.console.print()
    
    def _display_battlecards_results(self, data: dict) -> None:
        """Display supplier battlecards results."""
        self.console.print("\n[bold cyan]═══ SUPPLIER BATTLECARDS ═══[/bold cyan]\n")
        
        # Check for errors
        if "error" in data:
            self.console.print(f"[red]❌ Error: {data['error']}[/red]")
            return
        
        if "parse_error" in data:
            self.console.print(f"[red]❌ Parse error: {data['parse_error']}[/red]")
            return
        
        battlecards = data.get("battlecards", [])
        if not battlecards:
            self.console.print("[yellow]No supplier battlecards generated[/yellow]")
            self.console.print("[dim]This may mean no categories met the complexity threshold.[/dim]")
            return
        
        # Status icons for relationship
        status_icons = {
            "incumbent": "🔄",
            "new": "✅",
            "displaced": "❌",
            "considered": "🔍",
        }
        
        for idx, card in enumerate(battlecards, 1):
            supplier_name = card.get("supplier_name", "Unknown Supplier")
            category = card.get("category", "Unknown")
            status = card.get("relationship_status", "unknown")
            status_icon = status_icons.get(status.lower(), "❓")
            is_complex = card.get("is_complex", False)
            was_incumbent = card.get("was_incumbent", False)
            was_awarded = card.get("was_awarded", False)
            
            # Header for each battlecard
            self.console.print(f"[bold]━━━ Battlecard {idx}: {supplier_name} ━━━[/bold]")
            self.console.print(f"  [cyan]Category:[/cyan] {category}")
            self.console.print(f"  [cyan]Status:[/cyan] {status_icon} {status.title()}")
            
            # Incumbent and Awarded indicators
            incumbent_str = "[green]Yes[/green]" if was_incumbent else "[dim]No[/dim]"
            awarded_str = "[green]Yes[/green]" if was_awarded else "[dim]No[/dim]"
            self.console.print(f"  [cyan]Was Incumbent:[/cyan] {incumbent_str}  |  [cyan]Was Awarded:[/cyan] {awarded_str}")
            
            # Complexity reasons
            complexity_reasons = card.get("complexity_reasons", [])
            if complexity_reasons:
                self.console.print(f"  [cyan]Why Complex:[/cyan] {', '.join(complexity_reasons)}")
            
            # Financial summary
            baseline = card.get("baseline_spend")
            final = card.get("final_spend")
            savings_dollars = card.get("savings_dollars")
            savings_pct = card.get("savings_percent")
            
            self.console.print()
            self.console.print("  [bold green]Financial Summary[/bold green]")
            if baseline:
                self.console.print(f"    Baseline Spend: ${baseline:,.0f}")
            if final:
                self.console.print(f"    Final Spend: ${final:,.0f}")
            if savings_dollars:
                pct_str = f" ({savings_pct:.1f}%)" if savings_pct else ""
                self.console.print(f"    [green]Savings: ${savings_dollars:,.0f}{pct_str}[/green]")
            
            # Levers applied
            levers = card.get("levers_applied", [])
            if levers:
                self.console.print(f"    Levers: {', '.join(levers)}")
            
            # Strategic information
            alternatives = card.get("alternatives_considered", [])
            why_selected = card.get("why_selected")
            why_not_selected = card.get("why_not_selected")
            contract_terms = card.get("contract_terms")
            leverage = card.get("negotiation_leverage")
            
            if alternatives or why_selected or contract_terms or leverage:
                self.console.print()
                self.console.print("  [bold green]Strategic Details[/bold green]")
                
                if alternatives:
                    self.console.print(f"    Alternatives Considered: {', '.join(alternatives)}")
                if why_selected:
                    self.console.print(f"    Why Selected: {why_selected}")
                if why_not_selected:
                    self.console.print(f"    Why Not Selected: {why_not_selected}")
                if contract_terms:
                    self.console.print(f"    Contract Terms: {contract_terms}")
                if leverage:
                    self.console.print(f"    Negotiation Leverage: {leverage}")
            
            # Strengths/Weaknesses
            strengths = card.get("supplier_strengths")
            weaknesses = card.get("supplier_weaknesses")
            switching_costs = card.get("switching_costs")
            
            if strengths or weaknesses or switching_costs:
                self.console.print()
                self.console.print("  [bold green]Supplier Assessment[/bold green]")
                
                if strengths:
                    self.console.print(f"    [green]Strengths:[/green] {strengths}")
                if weaknesses:
                    self.console.print(f"    [yellow]Weaknesses:[/yellow] {weaknesses}")
                if switching_costs:
                    self.console.print(f"    [dim]Switching Costs:[/dim] {switching_costs}")
            
            # Notes
            notes = card.get("notes")
            if notes:
                self.console.print()
                self.console.print(f"  [dim]Notes: {notes}[/dim]")
            
            self.console.print()  # Blank line between battlecards
        
        # Summary
        summary = data.get("summary", {})
        if summary:
            self.console.print("[bold green]Battlecards Summary[/bold green]")
            
            total_evaluated = summary.get("total_suppliers_evaluated", 0)
            battlecards_generated = summary.get("battlecards_generated", len(battlecards))
            categories_covered = summary.get("categories_with_battlecards", [])
            skipped_reason = summary.get("skipped_reason", "")
            
            self.console.print(f"  Suppliers Evaluated: {total_evaluated}")
            self.console.print(f"  Battlecards Generated: [green]{battlecards_generated}[/green]")
            if categories_covered:
                self.console.print(f"  Categories Covered: {', '.join(categories_covered)}")
            if skipped_reason:
                self.console.print(f"  [dim]{skipped_reason}[/dim]")
            
            self.console.print()
        
        # Extraction notes
        extraction_notes = data.get("extraction_notes", [])
        if extraction_notes:
            self.console.print("[yellow]Extraction Notes:[/yellow]")
            for note in extraction_notes:
                self.console.print(f"  ⚠️ {note}")
            self.console.print()
    
    def _display_impact_results(self, data: dict) -> None:
        """Display impact extraction results."""
        self.console.print("\n[bold green]═══ IMPACT & RESULTS ═══[/bold green]\n")
        
        # Check for errors
        if "error" in data:
            self.console.print(f"[red]❌ Error: {data['error']}[/red]")
            return
        
        if "parse_error" in data:
            self.console.print(f"[red]❌ Parse error: {data['parse_error']}[/red]")
            return
        
        impact = data.get("impact", {})
        if not impact:
            self.console.print("[yellow]No impact data extracted[/yellow]")
            return
        
        conf_icons = {"high": "🟢", "medium": "🟡", "low": "🔴"}
        
        # Summary section
        summary = impact.get("summary", {})
        if summary:
            if summary.get("headline"):
                self.console.print(f"[bold green]📣 {summary['headline']}[/bold green]")
                self.console.print()
            
            if summary.get("narrative"):
                self.console.print("[bold]Narrative[/bold]")
                self.console.print(f"  {summary['narrative']}")
                self.console.print()
        
        # Financials section
        financials = impact.get("financials", {})
        if financials:
            self.console.print("[bold green]Financial Impact[/bold green]")
            
            # Total annual savings
            total = financials.get("total_annual_savings")
            if total and total.get("amount"):
                conf = conf_icons.get(total.get("confidence", ""), "⚪")
                self.console.print(f"  [cyan]Total Annual Savings:[/cyan] [bold green]${total['amount']:,.0f}[/bold green] {conf}")
                if total.get("notes"):
                    self.console.print(f"    [dim]{total['notes']}[/dim]")
            
            # Finalized savings
            finalized = financials.get("finalized_savings")
            if finalized and finalized.get("amount"):
                conf = conf_icons.get(finalized.get("confidence", ""), "⚪")
                self.console.print(f"  [cyan]Finalized Savings:[/cyan] [green]${finalized['amount']:,.0f}[/green] {conf}")
            
            # In-progress savings
            in_progress = financials.get("in_progress_savings")
            if in_progress and in_progress.get("amount"):
                conf = conf_icons.get(in_progress.get("confidence", ""), "⚪")
                self.console.print(f"  [cyan]In-Progress Savings:[/cyan] [yellow]${in_progress['amount']:,.0f}[/yellow] {conf}")
            
            # Legacy support: annual_savings (if no total_annual_savings)
            if not total:
                annual = financials.get("annual_savings")
                if annual and annual.get("amount"):
                    conf = conf_icons.get(annual.get("confidence", ""), "⚪")
                    self.console.print(f"  [cyan]Annual Savings:[/cyan] [bold green]${annual['amount']:,.0f}[/bold green] {conf}")
                    if annual.get("source_file"):
                        self.console.print(f"    [dim]Source: {annual['source_file']}[/dim]")
                    if annual.get("notes"):
                        self.console.print(f"    [dim]Notes: {annual['notes']}[/dim]")
            
            # One-time savings
            one_time = financials.get("one_time_savings")
            if one_time and one_time.get("amount"):
                conf = conf_icons.get(one_time.get("confidence", ""), "⚪")
                self.console.print(f"  [cyan]One-Time Savings:[/cyan] [green]${one_time['amount']:,.0f}[/green] {conf}")
            
            self.console.print()
        
        # Category Results breakdown
        category_results = impact.get("category_results", [])
        if category_results:
            self.console.print("[bold green]Category Results[/bold green]")
            
            # Status icons
            status_icons = {
                "finalized": "✅",
                "implemented": "✅",
                "complete": "✅",
                "in progress": "🔄",
                "in_progress": "🔄",
                "awaiting signature": "📝",
                "awaiting_signature": "📝",
                "pending": "📝",
                "proposal": "📋",
                "negotiation": "🤝",
            }
            
            for cat in category_results:
                name = cat.get("category_name", "Unknown")
                savings = cat.get("annual_savings", 0)
                status = cat.get("status", "unknown").lower()
                notes = cat.get("status_notes", "")
                
                icon = status_icons.get(status, "❓")
                status_display = status.replace("_", " ").title()
                
                self.console.print(f"  {icon} [bold]{name}[/bold]: ${savings:,.0f} [{status_display}]")
                if notes:
                    self.console.print(f"      [dim]{notes}[/dim]")
            
            self.console.print()
        
        # Excluded categories
        excluded = impact.get("excluded_categories", [])
        if excluded:
            self.console.print("[dim]Excluded Categories:[/dim]")
            for cat in excluded:
                name = cat.get("category_name", "Unknown")
                reason = cat.get("reason", "")
                self.console.print(f"  [dim]✗ {name}: {reason}[/dim]")
            self.console.print()
        
        # Not started categories (in scope but no work performed)
        not_started = impact.get("not_started_categories", [])
        if not_started:
            self.console.print("[dim]Not Started (in scope but no work performed):[/dim]")
            for cat in not_started:
                name = cat.get("category_name", "Unknown")
                reason = cat.get("reason", "")
                self.console.print(f"  [dim]⏸️ {name}: {reason}[/dim]")
            self.console.print()
        
        # Time to value
        ttv = impact.get("time_to_value", {})
        if ttv:
            value_days = ttv.get("value_realized_in_days")
            if value_days and value_days.get("value"):
                conf = conf_icons.get(value_days.get("confidence", ""), "⚪")
                self.console.print("[bold green]Time to Value[/bold green]")
                self.console.print(f"  [cyan]First Value Realized:[/cyan] {value_days['value']:.0f} days {conf}")
                if ttv.get("notes"):
                    self.console.print(f"  [dim]{ttv['notes']}[/dim]")
                self.console.print()
        
        # Operational improvements
        ops = impact.get("operational_improvements")
        if ops:
            self.console.print("[bold green]Operational Improvements[/bold green]")
            self.console.print(f"  {ops}")
            self.console.print()
        
        # Proof points
        proof_points = impact.get("proof_points", [])
        if proof_points:
            self.console.print("[bold green]Proof Points[/bold green]")
            for i, pp in enumerate(proof_points, 1):
                statement = pp.get("statement", "")
                category = pp.get("category")
                
                cat_str = f" [dim]({category})[/dim]" if category else ""
                self.console.print(f"  [green]✓[/green] {statement}{cat_str}")
                
                # Show evidence if available
                evidence = pp.get("evidence", [])
                for ev in evidence[:1]:  # Show first evidence only for brevity
                    if ev.get("quote"):
                        quote = ev["quote"]
                        if len(quote) > 80:
                            quote = quote[:80] + "..."
                        self.console.print(f"    [dim]Quote: \"{quote}\"[/dim]")
            
            self.console.print()
        
        # Extraction sources
        sources = data.get("extraction_sources", [])
        if sources:
            self.console.print("[bold green]Sources Used[/bold green]")
            for src in sources:
                self.console.print(f"  [dim]• {src}[/dim]")
            self.console.print()
        
        # Extraction notes
        notes = data.get("extraction_notes", [])
        if notes:
            self.console.print("[yellow]Extraction Notes:[/yellow]")
            for note in notes:
                self.console.print(f"  ⚠️ {note}")
            self.console.print()
    
    def _display_engagement_background_results(self, data: dict) -> None:
        """Display engagement background extraction results."""
        self.console.print("\n[bold cyan]═══ ENGAGEMENT BACKGROUND ═══[/bold cyan]\n")
        
        # Check for errors
        if "error" in data:
            self.console.print(f"[red]❌ Error: {data['error']}[/red]")
            return
        
        if "parse_error" in data:
            self.console.print(f"[red]❌ Parse error: {data['parse_error']}[/red]")
            return
        
        # Engagement background section
        eb = data.get("engagement_background", {})
        if eb:
            # Objective
            if eb.get("objective"):
                self.console.print("[bold green]Objective[/bold green]")
                self.console.print(f"  {eb['objective']}")
                self.console.print()
            
            # Scope summary
            if eb.get("scope_summary"):
                self.console.print("[bold green]Scope Summary[/bold green]")
                self.console.print(f"  {eb['scope_summary']}")
                self.console.print()
            
            # Constraints & Challenges
            constraints = eb.get("constraints_challenges", [])
            if constraints:
                self.console.print("[bold green]Constraints & Challenges[/bold green]")
                for constraint in constraints:
                    self.console.print(f"  [yellow]⚠️[/yellow] {constraint}")
                self.console.print()
        
        # Procurement environment
        pe = data.get("procurement_environment", {})
        if pe:
            self.console.print("[bold green]Procurement Environment[/bold green]")
            
            conf_icons = {"high": "🟢", "medium": "🟡", "low": "🔴"}
            conf = conf_icons.get(pe.get("confidence", ""), "⚪")
            
            # Operating model
            operating_model = pe.get("operating_model")
            if operating_model:
                model_display = {
                    "centralized": "Centralized",
                    "decentralized": "Decentralized",
                    "hybrid": "Hybrid",
                    "center_led": "Center-Led",
                }.get(operating_model, operating_model)
                self.console.print(f"  [cyan]Operating Model:[/cyan] {model_display}")
            
            # Maturity
            maturity = pe.get("maturity")
            if maturity:
                maturity_display = {
                    "low": "Low 🔴",
                    "medium": "Medium 🟡",
                    "high": "High 🟢",
                }.get(maturity, maturity)
                self.console.print(f"  [cyan]Procurement Maturity:[/cyan] {maturity_display}")
            
            # Data availability
            if pe.get("data_availability"):
                self.console.print(f"  [cyan]Data Availability:[/cyan] {pe['data_availability']}")
            
            # Data quality notes
            if pe.get("data_quality_notes"):
                self.console.print(f"  [cyan]Data Quality Notes:[/cyan] {pe['data_quality_notes']}")
            
            # Source and confidence
            if pe.get("source_file"):
                self.console.print(f"  [dim]Source: {pe['source_file']} {conf}[/dim]")
            
            self.console.print()
        
        # Extraction sources
        sources = data.get("extraction_sources", [])
        if sources:
            self.console.print("[bold green]Sources Used[/bold green]")
            for src in sources:
                self.console.print(f"  [dim]• {src}[/dim]")
            self.console.print()
        
        # Extraction notes
        notes = data.get("extraction_notes", [])
        if notes:
            self.console.print("[yellow]Extraction Notes:[/yellow]")
            for note in notes:
                self.console.print(f"  ⚠️ {note}")
            self.console.print()
    
    def _validate_anchor_paths(self, anchor_data: dict, scan_result) -> dict:
        """Validate that anchor paths actually exist in the directory."""
        all_paths = set(scan_result.get_all_file_paths())
        
        # Also build a set of folder paths
        folder_paths = set()
        self._collect_folder_paths(scan_result.root_folder, "", folder_paths)
        all_valid = all_paths | folder_paths
        
        def normalize_for_comparison(s: str) -> str:
            """Normalize a string for fuzzy comparison (lowercase, remove extra spaces)."""
            # Lowercase
            s = s.lower()
            # Normalize common variations: "AP Derm" vs "APDerm" -> "apderm"
            # Remove spaces that might be inconsistent
            s = s.replace(" ", "")
            return s
        
        def validate_path(path: Optional[str]) -> tuple:
            """Return (is_valid, normalized_path)"""
            if not path:
                return False, None
            
            normalized = path.rstrip("/").lstrip("./")
            
            # Try exact match first
            if normalized in all_valid or normalized + "/" in all_valid:
                return True, normalized
            
            # Try with trailing slash (for folders)
            if normalized.endswith("/"):
                clean = normalized.rstrip("/")
                if clean in all_valid:
                    return True, clean
            
            # Try case-insensitive match
            lower_path = normalized.lower()
            for ap in all_valid:
                if ap.lower() == lower_path or ap.lower().rstrip("/") == lower_path:
                    return True, ap.rstrip("/")
            
            # Try fuzzy match (handles "AP Derm" vs "APDerm" variations)
            # Compare the filename part with spaces removed
            fuzzy_path = normalize_for_comparison(normalized)
            for ap in all_valid:
                if normalize_for_comparison(ap) == fuzzy_path:
                    return True, ap.rstrip("/")
            
            # Try matching just the filename (in case path structure differs slightly)
            if "/" in normalized:
                filename = normalized.split("/")[-1]
                fuzzy_filename = normalize_for_comparison(filename)
                for ap in all_valid:
                    if "/" in ap:
                        ap_filename = ap.split("/")[-1]
                        if normalize_for_comparison(ap_filename) == fuzzy_filename:
                            return True, ap.rstrip("/")
            
            return False, None
        
        # Validate each anchor
        for anchor_key in ["agreement", "assessment", "case_study", "kickoff", "project_close_out"]:
            if anchor_key in anchor_data and anchor_data[anchor_key].get("found"):
                path = anchor_data[anchor_key].get("path")
                is_valid, normalized = validate_path(path)
                if not is_valid:
                    anchor_data[anchor_key]["found"] = False
                    anchor_data[anchor_key]["validation_error"] = f"Path not found: {path}"
                else:
                    anchor_data[anchor_key]["path"] = normalized
        
        # Validate project_updates paths
        if "project_updates" in anchor_data and anchor_data["project_updates"].get("found"):
            paths = anchor_data["project_updates"].get("paths", [])
            valid_paths = []
            invalid_paths = []
            
            for path in paths:
                is_valid, normalized = validate_path(path)
                if is_valid:
                    valid_paths.append(normalized)
                else:
                    invalid_paths.append(path)
            
            anchor_data["project_updates"]["paths"] = valid_paths
            if invalid_paths:
                anchor_data["project_updates"]["invalid_paths"] = invalid_paths
            if not valid_paths:
                anchor_data["project_updates"]["found"] = False
        
        return anchor_data
    
    def _collect_folder_paths(self, folder, prefix: str, folder_paths: set) -> None:
        """Recursively collect all folder paths."""
        for sf in folder.subfolders:
            path = f"{prefix}{sf.name}" if prefix else sf.name
            folder_paths.add(path)
            folder_paths.add(path + "/")
            self._collect_folder_paths(sf, path + "/", folder_paths)
    
    def _display_anchor_results(self, anchor_data: dict) -> None:
        """Display anchor detection results in a nice format."""
        self.console.print("\n[bold cyan]═══ ANCHOR FILES/FOLDERS DETECTION ═══[/bold cyan]\n")
        
        found_count = 0
        total_count = 6
        
        # Define display order and labels
        anchors = [
            ("agreement", "Agreement Folder", "folder"),
            ("assessment", "Assessment Folder", "folder"),
            ("case_study", "Case Study", "file_or_folder"),
            ("kickoff", "Kickoff", "file_or_folder"),
            ("project_updates", "Project Updates", "files"),
            ("project_close_out", "Project Close Out", "file_or_folder"),
        ]
        
        for key, label, expected_type in anchors:
            data = anchor_data.get(key, {})
            found = data.get("found", False)
            
            if found:
                found_count += 1
                self.console.print(f"[green]✅ {label}[/green]")
                
                if key == "project_updates":
                    # Multiple paths
                    paths = data.get("paths", [])
                    for path in paths:
                        self.console.print(f"   [dim]└─[/dim] {path}")
                    if data.get("invalid_paths"):
                        for path in data["invalid_paths"]:
                            self.console.print(f"   [red]└─ (invalid)[/red] [dim]{path}[/dim]")
                else:
                    # Single path
                    path = data.get("path", "(unknown)")
                    anchor_type = data.get("type", "")
                    date_str = data.get("date_in_name", "")
                    
                    type_indicator = ""
                    if anchor_type == "folder":
                        type_indicator = "📁 "
                    elif anchor_type == "file":
                        type_indicator = "📄 "
                    
                    date_indicator = f" [dim](date: {date_str})[/dim]" if date_str else ""
                    self.console.print(f"   [dim]└─[/dim] {type_indicator}{path}{date_indicator}")
                
                # Show validation error if any
                if data.get("validation_error"):
                    self.console.print(f"   [red]⚠️ {data['validation_error']}[/red]")
            else:
                self.console.print(f"[red]❌ {label}[/red]")
                self.console.print(f"   [dim]└─ (Not found)[/dim]")
            
            self.console.print()  # Blank line between sections
        
        # Summary
        status_color = "green" if found_count >= 4 else "yellow" if found_count >= 2 else "red"
        self.console.print(f"[{status_color}]Found: {found_count}/{total_count} anchor sections[/{status_color}]")
    
    def _display_project_scope_results(self, data: dict) -> None:
        """Display project scope extraction results."""
        self.console.print("\n[bold cyan]═══ PROJECT SCOPE EXTRACTION ═══[/bold cyan]\n")
        
        # Check if we have a parse error
        if "parse_error" in data:
            self.console.print("[red]❌ Failed to parse extraction response[/red]")
            self.console.print(f"[dim]Error: {data.get('parse_error')}[/dim]")
            return
        
        # =====================================================================
        # EXHIBIT A - Project Scope
        # =====================================================================
        exhibit_a = data.get("exhibit_a", {})
        if exhibit_a:
            self.console.print("[bold green]EXHIBIT A - Project Scope[/bold green]")
            
            # Categories
            categories = exhibit_a.get("initial_categories", [])
            cat_count = exhibit_a.get("initial_categories_count", len(categories))
            self.console.print(f"  [cyan]Categories:[/cyan] {cat_count} found")
            for cat in categories[:10]:  # Show first 10
                self.console.print(f"    • {cat}")
            if len(categories) > 10:
                self.console.print(f"    [dim]... and {len(categories) - 10} more[/dim]")
            
            # Spend totals
            total_spend = exhibit_a.get("total_spend")
            total_addressable = exhibit_a.get("total_addressable_spend")
            if total_spend:
                self.console.print(f"  [cyan]Total Spend:[/cyan] ${total_spend:,.0f}")
            if total_addressable:
                self.console.print(f"  [cyan]Total Addressable Spend:[/cyan] ${total_addressable:,.0f}")
                if total_spend and total_spend > 0:
                    pct = (total_addressable / total_spend) * 100
                    self.console.print(f"    [dim]({pct:.0f}% addressable)[/dim]")
            
            # Savings estimates
            savings_low = exhibit_a.get("savings_estimate_low")
            savings_high = exhibit_a.get("savings_estimate_high")
            if savings_low or savings_high:
                if savings_low and savings_high:
                    self.console.print(f"  [cyan]Savings Estimate:[/cyan] ${savings_low:,.0f} - ${savings_high:,.0f}")
                elif savings_low:
                    self.console.print(f"  [cyan]Savings Estimate Low:[/cyan] ${savings_low:,.0f}")
                elif savings_high:
                    self.console.print(f"  [cyan]Savings Estimate High:[/cyan] ${savings_high:,.0f}")
            
            # Category details (if present)
            category_details = exhibit_a.get("category_details", [])
            if category_details:
                self.console.print("\n  [dim]Category Details:[/dim]")
                
                # Create a simple table with COGS column
                table = Table(show_header=True, border_style="dim", padding=(0, 1))
                table.add_column("Category", style="white", max_width=25)
                table.add_column("Spend", style="cyan", justify="right")
                table.add_column("Addr%", style="dim", justify="right")
                table.add_column("Savings Range", style="green", justify="right")
                table.add_column("COGS", style="yellow", justify="center")
                
                for cat in category_details[:15]:  # Limit to 15 rows
                    name = cat.get("category_name", "")[:25]
                    spend = f"${cat.get('spend', 0):,.0f}" if cat.get('spend') else "-"
                    addr_pct = f"{cat.get('addressable_pct', 0)}%" if cat.get('addressable_pct') else "-"
                    
                    low = cat.get("savings_low")
                    high = cat.get("savings_high")
                    if low and high:
                        savings = f"${low:,.0f} - ${high:,.0f}"
                    elif low:
                        savings = f"${low:,.0f}"
                    else:
                        savings = "-"
                    
                    # COGS indicator
                    is_cogs = cat.get("is_cogs", False)
                    cogs_indicator = "✓" if is_cogs else ""
                    
                    table.add_row(name, spend, addr_pct, savings, cogs_indicator)
                
                self.console.print(table)
            
            # COGS Summary
            cogs_count = exhibit_a.get("cogs_categories_count")
            cogs_pct = exhibit_a.get("cogs_categories_percentage")
            cogs_spend = exhibit_a.get("cogs_addressable_spend")
            cogs_spend_pct = exhibit_a.get("cogs_addressable_percentage")
            
            # Get list of COGS categories from category_details
            cogs_categories = []
            if category_details:
                for cat in category_details:
                    if cat.get("is_cogs", False):
                        cogs_categories.append(cat.get("category_name", "Unknown"))
            
            if cogs_count is not None or cogs_pct is not None or cogs_categories:
                self.console.print("\n  [bold yellow]COGS Analysis:[/bold yellow]")
                
                # List COGS categories
                if cogs_categories:
                    self.console.print(f"    COGS Categories Identified:")
                    for cat_name in cogs_categories:
                        self.console.print(f"      [yellow]✓[/yellow] {cat_name}")
                
                if cogs_count is not None and cogs_pct is not None:
                    self.console.print(f"    Total: {cogs_count} COGS categories ({cogs_pct:.1f}% of total)")
                elif cogs_count is not None:
                    self.console.print(f"    Total: {cogs_count} COGS categories")
                
                if cogs_spend is not None and cogs_spend_pct is not None:
                    self.console.print(f"    COGS Addressable Spend: ${cogs_spend:,.0f} ({cogs_spend_pct:.1f}% of total)")
                elif cogs_spend is not None:
                    self.console.print(f"    COGS Addressable Spend: ${cogs_spend:,.0f}")
            
            self.console.print()
        
        # =====================================================================
        # EXHIBIT B - Fees
        # =====================================================================
        exhibit_b = data.get("exhibit_b", {})
        if exhibit_b:
            self.console.print("[bold green]EXHIBIT B - Fee Structure[/bold green]")
            
            fee_type = exhibit_b.get("fee_type", "unknown")
            fee_type_display = {
                "fixed": "🔒 Fixed Fee",
                "hybrid": "🔀 Hybrid Fee",
                "contingent": "📊 Contingent Fee",
            }.get(fee_type, fee_type)
            
            self.console.print(f"  [cyan]Fee Type:[/cyan] {fee_type_display}")
            
            # Fee amount (for fixed/hybrid)
            fee_amount = exhibit_b.get("fee_amount")
            if fee_amount:
                self.console.print(f"  [cyan]Fee Amount:[/cyan] ${fee_amount:,.0f}")
            
            # Minimum savings guarantee
            msg = exhibit_b.get("minimum_savings_guarantee")
            if msg:
                self.console.print(f"  [cyan]Min. Savings Guarantee:[/cyan] ${msg:,.0f}")
            
            # Minimum return on fees ratio (ROI guarantee)
            roi_ratio = exhibit_b.get("minimum_return_on_fees_ratio")
            if roi_ratio:
                self.console.print(f"  [cyan]Min. Return on Fees Ratio:[/cyan] {roi_ratio}×")
            
            # Hybrid-specific fields
            if fee_type == "hybrid":
                threshold = exhibit_b.get("fee_hybrid_threshold")
                if threshold:
                    self.console.print(f"  [cyan]Threshold:[/cyan] ${threshold:,.0f}")
                
                contingent_pct = exhibit_b.get("fee_contingent_percentage")
                if contingent_pct:
                    self.console.print(f"  [cyan]Variable Fee:[/cyan] {contingent_pct}% above threshold")
            
            # Contingent percentage (for contingent/hybrid)
            if fee_type == "contingent":
                contingent_pct = exhibit_b.get("fee_contingent_percentage")
                if contingent_pct:
                    self.console.print(f"  [cyan]Fee Percentage:[/cyan] {contingent_pct}% of savings")
            
            # Fee notes
            fee_notes = exhibit_b.get("fee_notes")
            if fee_notes:
                self.console.print(f"  [dim]Notes: {fee_notes}[/dim]")
            
            self.console.print()
        
        # =====================================================================
        # Timing
        # =====================================================================
        timing = data.get("timing", {})
        if timing:
            start_date = timing.get("start_date")
            end_date = timing.get("end_date")
            engagement_type = timing.get("engagement_type")
            
            if start_date or end_date or engagement_type:
                self.console.print("[bold green]Timing & Engagement[/bold green]")
                
                if engagement_type:
                    self.console.print(f"  [cyan]Type:[/cyan] {engagement_type}")
                if start_date:
                    self.console.print(f"  [cyan]Start Date:[/cyan] {start_date}")
                if end_date:
                    self.console.print(f"  [cyan]End Date:[/cyan] {end_date}")
                
                self.console.print()
        
        # =====================================================================
        # Extraction Notes
        # =====================================================================
        notes = data.get("extraction_notes", [])
        if notes:
            self.console.print("[yellow]Extraction Notes:[/yellow]")
            for note in notes:
                self.console.print(f"  ⚠️ {note}")
            self.console.print()
    
    def _generate_reasoning_log(
        self,
        scan_result,
        file_selection_prompt: str,
        selection_response,
        extraction_prompt: str,
        extraction_response,
    ) -> str:
        """Generate a log file containing all LLM reasoning for debugging."""
        lines = [
            "=" * 100,
            "LLM REASONING LOG",
            "=" * 100,
            f"Project: {scan_result.project_name}",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Model: {MODEL}",
            "",
            "",
            "=" * 100,
            "PASS 1: FILE SELECTION",
            "=" * 100,
            "",
            "--- PROMPT SENT TO LLM ---",
            file_selection_prompt,
            "",
            "--- LLM RESPONSE ---",
            f"Tokens: {selection_response.input_tokens:,} in / {selection_response.output_tokens:,} out",
            "",
            selection_response.content,
            "",
            "",
            "=" * 100,
            "PASS 2: SCHEMA EXTRACTION",
            "=" * 100,
            "",
            "--- PROMPT SENT TO LLM (truncated - file contents removed for brevity) ---",
            "",
            "NOTE: The full extraction prompt included the following file contents:",
        ]
        
        # Add note about which files were in the prompt
        if "## Extracted Document Contents:" in extraction_prompt:
            # Get the part before the file contents
            prompt_header = extraction_prompt.split("## Extracted Document Contents:")[0]
            lines.append(prompt_header)
            lines.append("")
            lines.append("[FILE CONTENTS OMITTED - See selected files above]")
        else:
            lines.append(extraction_prompt[:5000] + "\n... [TRUNCATED]")
        
        lines.extend([
            "",
            "--- LLM RESPONSE ---",
            f"Tokens: {extraction_response.input_tokens:,} in / {extraction_response.output_tokens:,} out",
            "",
            extraction_response.content,
        ])
        
        return "\n".join(lines)
    
    def _truncate_source(self, source: Optional[str], max_len: int = 40) -> str:
        """Truncate a source file path for display."""
        if not source:
            return ""
        if len(source) <= max_len:
            return source
        # Show just the filename
        return Path(source).name[:max_len]
    
    def _format_claim(self, claim, include_source: bool = True) -> str:
        """Format a ClaimMoney or ClaimNumber with confidence indicator."""
        if not claim or not hasattr(claim, 'amount') or not claim.amount:
            return ""
        
        conf_icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(getattr(claim, 'confidence', None) or "", "⚪")
        result = f"${claim.amount:,.0f} {conf_icon}"
        if include_source and hasattr(claim, 'source_file') and claim.source_file:
            result += f" [dim]({Path(claim.source_file).name})[/dim]"
        return result
    
    def _format_claim_text(self, claim, label: str) -> str:
        """Format a ClaimMoney for text output with confidence and source."""
        if not claim or not hasattr(claim, 'amount') or not claim.amount:
            return ""
        
        conf = getattr(claim, 'confidence', 'unknown') or 'unknown'
        source = getattr(claim, 'source_file', '') or ''
        source_name = Path(source).name if source else 'unknown'
        
        return f"{label}: ${claim.amount:,.0f} [confidence: {conf}] (source: {source_name})"
    
    def _fix_extraction_data(self, data: dict) -> dict:
        """
        Pre-process extraction data to fix common LLM output issues.
        
        This handles cases where the LLM returns values that are semantically
        correct but don't match our exact enum values.
        """
        # Status value mappings (LLM output -> our enum value)
        status_mappings = {
            "complete": "complete",  # Now a valid enum
            "completed": "completed",  # Now a valid enum
            "done": "implemented",
            "finished": "implemented",
            "active": "in_progress",
            "ongoing": "in_progress",
            "pending": "identified",
            "declined": "not_pursued",
            "rejected": "not_pursued",
            "cancelled": "not_pursued",
            "canceled": "not_pursued",
        }
        
        # Fix category statuses
        if "categories" in data and isinstance(data["categories"], list):
            for cat in data["categories"]:
                if "status" in cat and cat["status"]:
                    status_lower = cat["status"].lower().strip()
                    if status_lower in status_mappings:
                        cat["status"] = status_mappings[status_lower]
        
        # Fix fee_type if needed
        fee_type_mappings = {
            "fixed_fee": "fixed",
            "contingency": "contingent",
            "percentage": "contingent",
            "mixed": "hybrid",
            "combination": "hybrid",
        }
        if "project_scope" in data and data["project_scope"]:
            fee_type = data["project_scope"].get("fee_type")
            if fee_type and fee_type.lower() in fee_type_mappings:
                data["project_scope"]["fee_type"] = fee_type_mappings[fee_type.lower()]
        
        return data
    
    def _display_case_study_summary(self, case_study: CaseStudy) -> None:
        """Display a comprehensive summary of the extracted case study."""
        
        # Legend for confidence
        self.console.print("\n[dim]Confidence: 🟢 high | 🟡 medium | 🔴 low | ⚪ unknown[/dim]")
        
        # =====================================================================
        # SECTION 1: Client Overview
        # =====================================================================
        self.console.print("\n[bold cyan]═══ CLIENT OVERVIEW ═══[/bold cyan]")
        
        client_table = Table(border_style="cyan", show_header=False, padding=(0, 1))
        client_table.add_column("Field", style="cyan", width=20)
        client_table.add_column("Value", style="white")
        
        client_table.add_row("Client Name", case_study.client.client_name)
        if case_study.client.primary_industry_sector:
            client_table.add_row("Primary Industry Sector", case_study.client.primary_industry_sector)
        if case_study.client.industry_primary:
            industry = case_study.client.industry_primary
            if case_study.client.industry_secondary:
                industry += f" / {case_study.client.industry_secondary}"
            client_table.add_row("Secondary Industry", industry)
        if case_study.client.business_model:
            client_table.add_row("Business Model", case_study.client.business_model)
        if case_study.client.sponsor_pe_firm:
            client_table.add_row("PE Sponsor", case_study.client.sponsor_pe_firm)
        if case_study.client.client_history:
            # Truncate if too long
            history = case_study.client.client_history
            if len(history) > 100:
                history = history[:100] + "..."
            client_table.add_row("Background", history)
        
        # Size metrics with sources
        if case_study.client.size_metrics:
            sm = case_study.client.size_metrics
            if sm.revenue and sm.revenue.amount:
                conf_icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(sm.revenue.confidence or "", "⚪")
                source = Path(sm.revenue.source_file).name if sm.revenue.source_file else ""
                client_table.add_row("Revenue", f"${sm.revenue.amount:,.0f} {conf_icon} [dim]({source})[/dim]")
            if sm.ebitda and sm.ebitda.amount:
                conf_icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(sm.ebitda.confidence or "", "⚪")
                client_table.add_row("EBITDA", f"${sm.ebitda.amount:,.0f} {conf_icon}")
            if sm.locations_count:
                loc_conf = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(sm.locations_confidence or "", "⚪")
                loc_src = Path(sm.locations_source).name if sm.locations_source else ""
                client_table.add_row("Locations", f"{sm.locations_count} {loc_conf} [dim]({loc_src})[/dim]")
            if sm.employees_count:
                client_table.add_row("Employees", f"{sm.employees_count:,}")
        
        self.console.print(client_table)
        
        # =====================================================================
        # SECTION 2: Engagement Background
        # =====================================================================
        if case_study.engagement_background:
            eb = case_study.engagement_background
            self.console.print("\n[bold cyan]═══ ENGAGEMENT BACKGROUND ═══[/bold cyan]")
            
            if eb.objective:
                self.console.print(f"[bold]Objective:[/bold] {eb.objective}")
            if eb.scope_summary:
                self.console.print(f"[bold]Scope:[/bold] {eb.scope_summary}")
            
            if eb.constraints_challenges:
                self.console.print("[bold]Constraints/Challenges:[/bold]")
                for c in eb.constraints_challenges:
                    self.console.print(f"  • {c}")
            
            if eb.procurement_environment:
                pe = eb.procurement_environment
                conf_icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(pe.confidence or "", "⚪")
                source = Path(pe.source_file).name if pe.source_file else "unknown"
                self.console.print(f"[bold]Procurement Environment:[/bold] {conf_icon}")
                self.console.print(f"  [dim]Source: {source}[/dim]")
                if pe.operating_model:
                    self.console.print(f"  • Operating Model: {pe.operating_model.value}")
                if pe.maturity:
                    self.console.print(f"  • Maturity: {pe.maturity.value}")
                if pe.data_availability:
                    self.console.print(f"  • Data Availability: {pe.data_availability}")
                if pe.data_quality_notes:
                    self.console.print(f"  [dim]Notes: {pe.data_quality_notes}[/dim]")
        
        # =====================================================================
        # SECTION 3: Project Scope & Fees (Should be from Agreement)
        # =====================================================================
        if case_study.project_scope:
            ps = case_study.project_scope
            self.console.print("\n[bold cyan]═══ PROJECT SCOPE & FEES ═══[/bold cyan]")
            self.console.print("[dim]⚠️ These fields should come from Agreement. 🔴 = NOT from Agreement[/dim]\n")
            
            def is_from_agreement(source_file: Optional[str]) -> bool:
                """Check if source is from Agreement folder."""
                if not source_file:
                    return False
                return "agreement" in source_file.lower()
            
            if ps.engagement_type:
                self.console.print(f"[bold]Engagement Type:[/bold] {ps.engagement_type}")
            
            if ps.fee_type:
                fee_str = ps.fee_type.value
                if ps.fee_contingent_percentage:
                    fee_str += f" ({ps.fee_contingent_percentage}% of savings)"
                self.console.print(f"[bold]Fee Type:[/bold] {fee_str}")
            
            if ps.fee_amount and ps.fee_amount.amount:
                from_agr = is_from_agreement(ps.fee_amount.source_file)
                icon = "🟢" if from_agr else "🔴"
                warning = "" if from_agr else " [red]NOT FROM AGREEMENT[/red]"
                self.console.print(f"[bold]Fee Amount:[/bold] ${ps.fee_amount.amount:,.0f} {icon}{warning}")
                if ps.fee_amount.source_file:
                    self.console.print(f"   [dim]Source: {Path(ps.fee_amount.source_file).name}[/dim]")
            
            if ps.initial_categories_count:
                self.console.print(f"[bold]Initial Categories:[/bold] {ps.initial_categories_count}")
            
            if ps.addressable_spend and ps.addressable_spend.amount:
                from_agr = is_from_agreement(ps.addressable_spend.source_file)
                icon = "🟢" if from_agr else "🔴"
                warning = "" if from_agr else " [red]NOT FROM AGREEMENT[/red]"
                self.console.print(f"[bold]Addressable Spend:[/bold] ${ps.addressable_spend.amount:,.0f} {icon}{warning}")
                if ps.addressable_spend.source_file:
                    self.console.print(f"   [dim]Source: {Path(ps.addressable_spend.source_file).name}[/dim]")
            
            if ps.savings_estimate_low and ps.savings_estimate_low.amount:
                low = ps.savings_estimate_low.amount
                high = ps.savings_estimate_high.amount if ps.savings_estimate_high else None
                from_agr = is_from_agreement(ps.savings_estimate_low.source_file)
                icon = "🟢" if from_agr else "🔴"
                warning = "" if from_agr else " [red]NOT FROM AGREEMENT[/red]"
                if high:
                    self.console.print(f"[bold]Savings Estimate:[/bold] ${low:,.0f} - ${high:,.0f} {icon}{warning}")
                else:
                    self.console.print(f"[bold]Savings Estimate:[/bold] ${low:,.0f} {icon}{warning}")
                if ps.savings_estimate_low.source_file:
                    self.console.print(f"   [dim]Source: {Path(ps.savings_estimate_low.source_file).name}[/dim]")
            
            if ps.start_date:
                dates = str(ps.start_date)
                if ps.end_date:
                    dates += f" → {ps.end_date}"
                self.console.print(f"[bold]Timeline:[/bold] {dates}")
            
            if ps.operational_objectives:
                self.console.print("[bold]Operational Objectives:[/bold]")
                for obj in ps.operational_objectives:
                    self.console.print(f"  • {obj}")
        
        # =====================================================================
        # SECTION 4: Impact
        # =====================================================================
        if case_study.impact:
            imp = case_study.impact
            self.console.print("\n[bold green]═══ IMPACT ═══[/bold green]")
            
            if imp.summary:
                if imp.summary.headline:
                    self.console.print(f"[bold green]📣 {imp.summary.headline}[/bold green]")
                if imp.summary.narrative:
                    self.console.print(f"\n{imp.summary.narrative}")
            
            if imp.financials:
                fin = imp.financials
                self.console.print("\n[bold]Financial Impact:[/bold]")
                if fin.annual_savings and fin.annual_savings.amount:
                    conf_icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(fin.annual_savings.confidence or "", "⚪")
                    source = Path(fin.annual_savings.source_file).name if fin.annual_savings.source_file else "unknown"
                    self.console.print(f"  • Annual Savings: [green]${fin.annual_savings.amount:,.0f}[/green] {conf_icon}")
                    self.console.print(f"    [dim]Source: {source}[/dim]")
                if fin.one_time_savings and fin.one_time_savings.amount:
                    conf_icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(fin.one_time_savings.confidence or "", "⚪")
                    self.console.print(f"  • One-Time Savings: [green]${fin.one_time_savings.amount:,.0f}[/green] {conf_icon}")
            
            if imp.time_to_value and imp.time_to_value.value_realized_in_days:
                ttv = imp.time_to_value.value_realized_in_days
                if ttv.value:
                    self.console.print(f"\n[bold]Time to Value:[/bold] {ttv.value:.0f} days")
            
            if imp.operational_improvements:
                self.console.print(f"\n[bold]Operational Improvements:[/bold] {imp.operational_improvements}")
            
            if imp.proof_points:
                self.console.print("\n[bold]Proof Points:[/bold]")
                for pp in imp.proof_points:
                    self.console.print(f"  ✓ {pp.statement}")
                    if pp.evidence:
                        for ev in pp.evidence:
                            source = Path(ev.source_file).name if ev.source_file else "unknown"
                            self.console.print(f"    [dim]Source: {source}[/dim]")
                            if ev.quote:
                                quote_preview = ev.quote[:80] + "..." if len(ev.quote) > 80 else ev.quote
                                self.console.print(f"    [dim]Quote: \"{quote_preview}\"[/dim]")
        
        # =====================================================================
        # SECTION 5: Categories (Detailed) - WITH CONFIDENCE FOR FACT-CHECKING
        # =====================================================================
        if case_study.categories:
            self.console.print("\n[bold cyan]═══ CATEGORY OUTCOMES ({} categories) ═══[/bold cyan]".format(len(case_study.categories)))
            self.console.print("[dim]Confidence: 🟢 high  🟡 medium  🔴 low  ⚪ unknown[/dim]\n")
            
            for cat in case_study.categories:
                status_icon = {
                    "implemented": "✅",
                    "negotiated": "🔄", 
                    "identified": "🎯",
                    "not_pursued": "❌",
                }.get(cat.status.value if cat.status else "unknown", "❓")
                
                status_str = cat.status.value if cat.status else "unknown"
                self.console.print(f"{status_icon} [bold]{cat.category_label}[/bold] [{status_str}]")
                
                # Baseline with confidence and source
                if cat.baseline_spend and cat.baseline_spend.amount:
                    conf_icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(cat.baseline_spend.confidence or "", "⚪")
                    source = Path(cat.baseline_spend.source_file).name if cat.baseline_spend.source_file else "unknown"
                    self.console.print(f"   Baseline: ${cat.baseline_spend.amount:,.0f} {conf_icon}")
                    self.console.print(f"   [dim]Source: {source}[/dim]")
                
                # Savings with confidence and source
                if cat.savings_annual_run_rate and cat.savings_annual_run_rate.amount:
                    conf_icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(cat.savings_annual_run_rate.confidence or "", "⚪")
                    pct = f" ({cat.savings_percentage:.0f}%)" if cat.savings_percentage else ""
                    source = Path(cat.savings_annual_run_rate.source_file).name if cat.savings_annual_run_rate.source_file else "unknown"
                    self.console.print(f"   Savings: [green]${cat.savings_annual_run_rate.amount:,.0f}/yr{pct}[/green] {conf_icon}")
                    self.console.print(f"   [dim]Source: {source}[/dim]")
                
                # Levers
                if cat.levers:
                    self.console.print(f"   Levers: {', '.join(cat.levers)}")
                
                # Vendors (Pre/Post Sourcing)
                if cat.vendors_before:
                    self.console.print(f"   Vendors Before: {', '.join(cat.vendors_before)}")
                if cat.vendors_after:
                    self.console.print(f"   Vendors After: [green]{', '.join(cat.vendors_after)}[/green]")
                
                # Notes
                if cat.notes:
                    self.console.print(f"   [dim]Notes: {cat.notes}[/dim]")
                
                self.console.print()  # Blank line between categories
            
            # Show levers summary
            all_levers = set()
            for cat in case_study.categories:
                if cat.levers:
                    all_levers.update(cat.levers)
            if all_levers:
                self.console.print(f"[bold]All Levers Used:[/bold] {', '.join(sorted(all_levers))}")
        
        # =====================================================================
        # SECTION 6: Case Study Packaging
        # =====================================================================
        if case_study.case_study_packaging:
            csp = case_study.case_study_packaging
            self.console.print("\n[bold magenta]═══ CASE STUDY PACKAGING ═══[/bold magenta]")
            
            if csp.headline:
                self.console.print(f"[bold]Headline:[/bold] {csp.headline}")
            if csp.client_problem_statement:
                self.console.print(f"[bold]Problem:[/bold] {csp.client_problem_statement}")
            if csp.client_problem_anonymized:
                self.console.print(f"[bold]Problem (Anonymized):[/bold] {csp.client_problem_anonymized}")
            
            if csp.approach_summary:
                self.console.print("[bold]Approach:[/bold]")
                for a in csp.approach_summary:
                    self.console.print(f"  • {a}")
            
            if csp.top_levers:
                self.console.print(f"[bold]Top Levers:[/bold] {', '.join(csp.top_levers)}")
            
            if csp.value_delivered_blurb:
                self.console.print(f"[bold]Value Delivered:[/bold] {csp.value_delivered_blurb}")
            
            if csp.where_we_were_unique:
                self.console.print(f"[bold]Unique Approach:[/bold] {', '.join(csp.where_we_were_unique)}")
        
        # =====================================================================
        # SECTION 7: Extraction Notes
        # =====================================================================
        if case_study.extraction_notes:
            self.console.print("\n[bold yellow]═══ EXTRACTION NOTES ═══[/bold yellow]")
            for note in case_study.extraction_notes:
                self.console.print(f"  ⚠️ {note}")
    
    def _generate_text_summary(
        self,
        scan_result,
        selected_files: List[str],
        case_study: Optional[CaseStudy],
        case_study_data: dict,
        total_input_tokens: int,
        total_output_tokens: int,
    ) -> str:
        """Generate a comprehensive text summary of the extraction."""
        lines = [
            f"{'='*80}",
            f"CASE STUDY EXTRACTION: {scan_result.project_name.upper()}",
            f"{'='*80}",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Model: {MODEL}",
            f"Tokens: {total_input_tokens:,} in / {total_output_tokens:,} out",
            "",
        ]
        
        if not case_study:
            lines.append("RAW EXTRACTION DATA:")
            lines.append(json.dumps(case_study_data, indent=2))
            return "\n".join(lines)
        
        # =====================================================================
        # CLIENT OVERVIEW
        # =====================================================================
        lines.extend([
            "=" * 80,
            "CLIENT OVERVIEW",
            "=" * 80,
            f"Client Name: {case_study.client.client_name}",
        ])
        
        if case_study.client.primary_industry_sector:
            lines.append(f"Primary Industry Sector: {case_study.client.primary_industry_sector}")
        if case_study.client.industry_primary:
            industry = case_study.client.industry_primary
            if case_study.client.industry_secondary:
                industry += f" / {case_study.client.industry_secondary}"
            lines.append(f"Secondary Industry: {industry}")
        if case_study.client.business_model:
            lines.append(f"Business Model: {case_study.client.business_model}")
        if case_study.client.sponsor_pe_firm:
            lines.append(f"PE Sponsor: {case_study.client.sponsor_pe_firm}")
        if case_study.client.client_history:
            lines.append(f"Background: {case_study.client.client_history}")
        
        if case_study.client.size_metrics:
            sm = case_study.client.size_metrics
            if sm.revenue and sm.revenue.amount:
                conf = sm.revenue.confidence or "unknown"
                src = Path(sm.revenue.source_file).name if sm.revenue.source_file else "unknown"
                lines.append(f"Revenue: ${sm.revenue.amount:,.0f} [confidence: {conf}]")
                lines.append(f"  Source: {src}")
            if sm.ebitda and sm.ebitda.amount:
                conf = sm.ebitda.confidence or "unknown"
                lines.append(f"EBITDA: ${sm.ebitda.amount:,.0f} [confidence: {conf}]")
            if sm.locations_count:
                loc_conf = sm.locations_confidence or "unknown"
                loc_src = Path(sm.locations_source).name if sm.locations_source else "unknown"
                lines.append(f"Locations: {sm.locations_count} [confidence: {loc_conf}]")
                lines.append(f"  Source: {loc_src}")
            if sm.employees_count:
                lines.append(f"Employees: {sm.employees_count:,}")
        
        # =====================================================================
        # ENGAGEMENT BACKGROUND
        # =====================================================================
        if case_study.engagement_background:
            eb = case_study.engagement_background
            lines.extend([
                "",
                "=" * 80,
                "ENGAGEMENT BACKGROUND",
                "=" * 80,
            ])
            if eb.objective:
                lines.append(f"Objective: {eb.objective}")
            if eb.scope_summary:
                lines.append(f"Scope: {eb.scope_summary}")
            if eb.constraints_challenges:
                lines.append("Constraints/Challenges:")
                for c in eb.constraints_challenges:
                    lines.append(f"  • {c}")
            if eb.procurement_environment:
                pe = eb.procurement_environment
                conf = pe.confidence or "unknown"
                src = Path(pe.source_file).name if pe.source_file else "unknown"
                lines.append(f"Procurement Environment: [confidence: {conf}]")
                lines.append(f"  Source: {src}")
                if pe.operating_model:
                    lines.append(f"  • Operating Model: {pe.operating_model.value}")
                if pe.maturity:
                    lines.append(f"  • Maturity: {pe.maturity.value}")
                if pe.data_availability:
                    lines.append(f"  • Data Availability: {pe.data_availability}")
        
        # =====================================================================
        # PROJECT SCOPE & FEES (WITH AGREEMENT CHECK)
        # =====================================================================
        if case_study.project_scope:
            ps = case_study.project_scope
            
            def is_from_agreement(source_file: Optional[str]) -> bool:
                if not source_file:
                    return False
                return "agreement" in source_file.lower()
            
            lines.extend([
                "",
                "=" * 80,
                "PROJECT SCOPE & FEES",
                "(⚠️ These fields should come from Agreement. ❌ = NOT from Agreement)",
                "=" * 80,
            ])
            if ps.engagement_type:
                lines.append(f"Engagement Type: {ps.engagement_type}")
            if ps.fee_type:
                fee_str = ps.fee_type.value
                if ps.fee_contingent_percentage:
                    fee_str += f" ({ps.fee_contingent_percentage}% of savings)"
                lines.append(f"Fee Type: {fee_str}")
            if ps.fee_amount and ps.fee_amount.amount:
                src = Path(ps.fee_amount.source_file).name if ps.fee_amount.source_file else "unknown"
                from_agr = is_from_agreement(ps.fee_amount.source_file)
                flag = "✓ FROM AGREEMENT" if from_agr else "❌ NOT FROM AGREEMENT"
                lines.append(f"Fee Amount: ${ps.fee_amount.amount:,.0f} [{flag}]")
                lines.append(f"  Source: {src}")
            if ps.initial_categories_count:
                lines.append(f"Initial Categories: {ps.initial_categories_count}")
            if ps.addressable_spend and ps.addressable_spend.amount:
                src = Path(ps.addressable_spend.source_file).name if ps.addressable_spend.source_file else "unknown"
                from_agr = is_from_agreement(ps.addressable_spend.source_file)
                flag = "✓ FROM AGREEMENT" if from_agr else "❌ NOT FROM AGREEMENT"
                lines.append(f"Addressable Spend: ${ps.addressable_spend.amount:,.0f} [{flag}]")
                lines.append(f"  Source: {src}")
            if ps.savings_estimate_low and ps.savings_estimate_low.amount:
                low = ps.savings_estimate_low.amount
                high = ps.savings_estimate_high.amount if ps.savings_estimate_high else None
                src = Path(ps.savings_estimate_low.source_file).name if ps.savings_estimate_low.source_file else "unknown"
                from_agr = is_from_agreement(ps.savings_estimate_low.source_file)
                flag = "✓ FROM AGREEMENT" if from_agr else "❌ NOT FROM AGREEMENT"
                if high:
                    lines.append(f"Savings Estimate: ${low:,.0f} - ${high:,.0f} [{flag}]")
                else:
                    lines.append(f"Savings Estimate: ${low:,.0f} [{flag}]")
                lines.append(f"  Source: {src}")
            if ps.start_date:
                dates = str(ps.start_date)
                if ps.end_date:
                    dates += f" → {ps.end_date}"
                lines.append(f"Timeline: {dates}")
            if ps.operational_objectives:
                lines.append("Operational Objectives:")
                for obj in ps.operational_objectives:
                    lines.append(f"  • {obj}")
        
        # =====================================================================
        # IMPACT (WITH CONFIDENCE FOR FACT-CHECKING)
        # =====================================================================
        if case_study.impact:
            imp = case_study.impact
            lines.extend([
                "",
                "=" * 80,
                "IMPACT (ACTUAL RESULTS)",
                "=" * 80,
            ])
            if imp.summary:
                if imp.summary.headline:
                    lines.append(f"Headline: {imp.summary.headline}")
                if imp.summary.narrative:
                    lines.append(f"Narrative: {imp.summary.narrative}")
            if imp.financials:
                if imp.financials.annual_savings and imp.financials.annual_savings.amount:
                    sav = imp.financials.annual_savings
                    conf = sav.confidence or "unknown"
                    src = Path(sav.source_file).name if sav.source_file else "unknown"
                    lines.append(f"Annual Savings: ${sav.amount:,.0f} [confidence: {conf}]")
                    lines.append(f"  Source: {src}")
                if imp.financials.one_time_savings and imp.financials.one_time_savings.amount:
                    ots = imp.financials.one_time_savings
                    conf = ots.confidence or "unknown"
                    src = Path(ots.source_file).name if ots.source_file else "unknown"
                    lines.append(f"One-Time Savings: ${ots.amount:,.0f} [confidence: {conf}]")
                    lines.append(f"  Source: {src}")
            if imp.time_to_value and imp.time_to_value.value_realized_in_days:
                ttv = imp.time_to_value.value_realized_in_days
                if ttv.value:
                    lines.append(f"Time to Value: {ttv.value:.0f} days")
            if imp.operational_improvements:
                lines.append(f"Operational Improvements: {imp.operational_improvements}")
            if imp.proof_points:
                lines.append("Proof Points:")
                for pp in imp.proof_points:
                    lines.append(f"  ✓ {pp.statement}")
                    if pp.evidence:
                        for ev in pp.evidence:
                            if ev.source_file:
                                lines.append(f"      Source: {Path(ev.source_file).name}")
                            if ev.quote:
                                lines.append(f"      Quote: \"{ev.quote[:100]}...\"" if len(ev.quote) > 100 else f"      Quote: \"{ev.quote}\"")
        
        # =====================================================================
        # CATEGORY OUTCOMES (WITH CONFIDENCE FOR FACT-CHECKING)
        # =====================================================================
        if case_study.categories:
            lines.extend([
                "",
                "=" * 80,
                "CATEGORY OUTCOMES",
                "=" * 80,
                "",
                "Legend: [confidence: high/medium/low] indicates data reliability",
                "",
            ])
            for cat in case_study.categories:
                status = cat.status.value if cat.status else "unknown"
                lines.append(f"[{status.upper()}] {cat.category_label}")
                
                if cat.baseline_spend and cat.baseline_spend.amount:
                    conf = cat.baseline_spend.confidence or "unknown"
                    src = Path(cat.baseline_spend.source_file).name if cat.baseline_spend.source_file else "unknown"
                    lines.append(f"  Baseline Spend: ${cat.baseline_spend.amount:,.0f} [confidence: {conf}]")
                    lines.append(f"    Source: {src}")
                
                if cat.savings_annual_run_rate and cat.savings_annual_run_rate.amount:
                    savings = cat.savings_annual_run_rate.amount
                    pct = f" ({cat.savings_percentage:.0f}%)" if cat.savings_percentage else ""
                    conf = cat.savings_annual_run_rate.confidence or "unknown"
                    src = Path(cat.savings_annual_run_rate.source_file).name if cat.savings_annual_run_rate.source_file else "unknown"
                    lines.append(f"  Annual Savings: ${savings:,.0f}{pct} [confidence: {conf}]")
                    lines.append(f"    Source: {src}")
                
                if cat.savings_one_time and cat.savings_one_time.amount:
                    conf = cat.savings_one_time.confidence or "unknown"
                    lines.append(f"  One-Time Savings: ${cat.savings_one_time.amount:,.0f} [confidence: {conf}]")
                
                if cat.levers:
                    lines.append(f"  Levers: {', '.join(cat.levers)}")
                if cat.vendors_before:
                    lines.append(f"  Vendors Before: {', '.join(cat.vendors_before)}")
                if cat.vendors_after:
                    lines.append(f"  Vendors After: {', '.join(cat.vendors_after)}")
                if cat.notes:
                    lines.append(f"  Notes: {cat.notes}")
                lines.append("")  # Blank line between categories
        
        # =====================================================================
        # CASE STUDY PACKAGING
        # =====================================================================
        if case_study.case_study_packaging:
            csp = case_study.case_study_packaging
            lines.extend([
                "",
                "=" * 80,
                "CASE STUDY PACKAGING (MARKETING-READY)",
                "=" * 80,
            ])
            if csp.headline:
                lines.append(f"Headline: {csp.headline}")
            if csp.client_problem_statement:
                lines.append(f"Problem Statement: {csp.client_problem_statement}")
            if csp.client_problem_anonymized:
                lines.append(f"Problem Statement (Anonymized): {csp.client_problem_anonymized}")
            if csp.approach_summary:
                lines.append("Approach:")
                for a in csp.approach_summary:
                    lines.append(f"  • {a}")
            if csp.top_levers:
                lines.append(f"Top Levers: {', '.join(csp.top_levers)}")
            if csp.value_delivered_blurb:
                lines.append(f"Value Delivered: {csp.value_delivered_blurb}")
            if csp.where_we_were_unique:
                lines.append(f"Unique Approach: {', '.join(csp.where_we_were_unique)}")
        
        # =====================================================================
        # EXTRACTION NOTES
        # =====================================================================
        if case_study.extraction_notes:
            lines.extend([
                "",
                "=" * 80,
                "EXTRACTION NOTES",
                "=" * 80,
            ])
            for note in case_study.extraction_notes:
                lines.append(f"  ⚠️ {note}")
        
        # =====================================================================
        # FILES ANALYZED
        # =====================================================================
        lines.extend([
            "",
            "=" * 80,
            "FILES ANALYZED",
            "=" * 80,
        ])
        for f in selected_files:
            lines.append(f"  • {f}")
        
        return "\n".join(lines)
    
    async def handle_input(self, user_input: str) -> None:
        """Handle user input."""
        if not user_input.startswith("/"):
            self.console.print("[dim]Type /help for available commands[/dim]")
            return
        
        parts = user_input.strip().split()
        cmd = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []
        
        if cmd in self._commands:
            handler, _ = self._commands[cmd]
            await handler(args)
        else:
            self.console.print(f"[red]Unknown command: {cmd}[/red]")
            self.console.print("[dim]Type /help for available commands[/dim]")
    
    def get_input(self) -> str:
        """Get user input with prompt."""
        try:
            return input("> ").strip()
        except KeyboardInterrupt:
            print("\nCancelled")
            return ""
        except EOFError:
            raise


async def run_console() -> None:
    """Run the interactive console."""
    app = ConsoleApp()
    
    # Print banner and help
    app._print_banner()
    app._print_help()
    
    while not app.exit_requested:
        try:
            user_input = app.get_input()
            
            if not user_input:
                continue
            
            await app.handle_input(user_input)
            
        except KeyboardInterrupt:
            app.console.print("\n[yellow]Cancelled[/yellow]")
            continue
        except asyncio.CancelledError:
            app.console.print("\n[yellow]Operation cancelled[/yellow]")
            continue
        except EOFError:
            app.console.print("\n[yellow]👋 Goodbye![/yellow]")
            break
        except Exception as e:
            app.console.print(f"[red]Error:[/red] {e}")
