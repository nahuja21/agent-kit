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
    ensure_directories,
)
from src.scanner import DirectoryScanner, find_project_in_inputs, extract_zip_project
from src.llm import OpenAIClient
from src.prompts import ContextBuilder
from src.prompts.context import get_file_selection_prompt, get_schema_extraction_prompt, FILE_SELECTION_COUNT
from src.extractors.base import extract_file_content
from src.models.schema import CaseStudy


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
        
        self.console.print(table)
        
        if errors:
            self.console.print("\n[red]Configuration Errors:[/red]")
            for error in errors:
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
        
        # =====================================================================
        # STEP 1: Scan Directory Structure
        # =====================================================================
        self.console.print(Panel(
            "[bold]Step 1/3:[/bold] Scanning directory structure",
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
            "[bold]Step 2/3:[/bold] Detecting anchor files and folders",
            border_style="cyan",
        ))
        
        anchor_prompt = self._get_anchor_detection_prompt(scan_result.to_tree_string())
        
        with self.console.status(f"[cyan]Asking {MODEL} to find anchor files...[/cyan]"):
            try:
                anchor_response = self.llm_client.analyze(
                    system_prompt="You are a document analyst. Analyze the directory structure and find the requested files/folders. Return only valid JSON.",
                    user_content=anchor_prompt,
                )
            except Exception as e:
                self.console.print(f"[red]Failed to detect anchor files: {e}[/red]")
                return
        
        # Parse anchor detection response
        try:
            content = anchor_response.content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])
            
            anchor_data = json.loads(content)
        except json.JSONDecodeError as e:
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
        # STEP 3: (Placeholder for future extraction)
        # =====================================================================
        self.console.print(Panel(
            "[bold]Step 3/3:[/bold] Content extraction [dim](not yet implemented)[/dim]",
            border_style="yellow",
        ))
        self.console.print("[yellow]⚠️ Step 3 is a placeholder - will be implemented next.[/yellow]")
        
        # Store anchor data for potential Step 3 use
        self._last_anchor_data = anchor_data
        self._last_scan_result = scan_result
        self._last_project_path = project_path
        
        self.console.print()
    
    def _get_anchor_detection_prompt(self, directory_tree: str) -> str:
        """Generate the prompt for anchor file/folder detection."""
        return f"""# Anchor File/Folder Detection

You are analyzing a project folder structure to find specific "anchor" files and folders that are important for case study extraction.

## Directory Tree:
```
{directory_tree}
```

## Files/Folders to Find:

### 1. Agreement (FOLDER)
- Look for folders named "Agreement", "Agreements", or containing "Agreement" in the name
- If there are multiple, pick the one with the MOST RECENT date in the folder name
- Date formats could be: "2021-03-15", "March 2021", "3-15-21", "Q3 2021", etc.

### 2. Assessment (FOLDER)
- Look for folders named "Assessment", "Assessments", or containing "Assessment" in the name
- If there are multiple, pick the one with the MOST RECENT date in the folder name

### 3. Case Study (FILE or FOLDER)
- Look for files or folders named "Case Study", "CaseStudy", "Case-Study", or containing these terms
- Common file types: .pdf, .pptx, .docx
- If there are multiple, pick the one with the MOST RECENT date in the name
- Return the TYPE as "file" or "folder"

### 4. Kickoff (FILE or FOLDER)
- Look for files or folders named "Kickoff", "Kick-off", "Kick off", or containing these terms
- Common file types: .pptx, .pdf
- If there are multiple, pick the one with the MOST RECENT date in the name
- Return the TYPE as "file" or "folder"

### 5. Project Updates (FILES - find up to 5)
- Search ANYWHERE in the directory tree for files containing "ProjectUpdate", "Project Update", "Project_Update"
- These are typically .pptx files but could be other formats
- Return UP TO 5 of them, sorted by the date in filename (MOST RECENT first)
- If they are all in one folder, that's fine. If scattered, list each file path.

### 6. Project Close Out (FILE or FOLDER)
- Look for files or folders named "Close Out", "CloseOut", "Closeout", "Close-Out", "Project Close"
- Could also be called "Final Update", "Project Completion"
- If there are multiple, pick the one with the MOST RECENT date in the name
- Return the TYPE as "file" or "folder"

## Response Format:

Return ONLY valid JSON in this exact format:

```json
{{
  "agreement": {{
    "found": true,
    "type": "folder",
    "path": "Agreement/",
    "date_in_name": "2021-03-15"
  }},
  "assessment": {{
    "found": true,
    "type": "folder",
    "path": "Assessment/",
    "date_in_name": null
  }},
  "case_study": {{
    "found": true,
    "type": "file",
    "path": "Case Study/Final Case Study.pdf",
    "date_in_name": null
  }},
  "kickoff": {{
    "found": false,
    "type": null,
    "path": null,
    "date_in_name": null
  }},
  "project_updates": {{
    "found": true,
    "type": "files",
    "paths": [
      "Project Updates/ProjectUpdate 2021-12-01.pptx",
      "Project Updates/ProjectUpdate 2021-11-15.pptx"
    ]
  }},
  "project_close_out": {{
    "found": false,
    "type": null,
    "path": null,
    "date_in_name": null
  }}
}}
```

IMPORTANT:
- Use the EXACT paths as they appear in the directory tree
- For "project_updates", return an array of paths (up to 5)
- For other anchors, return a single path string
- If not found, set "found": false and all other fields to null
- "date_in_name" should be the date extracted from the filename (normalized to YYYY-MM-DD if possible, otherwise as found)
"""
    
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
        if case_study.client.industry_primary:
            industry = case_study.client.industry_primary
            if case_study.client.industry_secondary:
                industry += f" / {case_study.client.industry_secondary}"
            client_table.add_row("Industry", industry)
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
        
        if case_study.client.industry_primary:
            industry = case_study.client.industry_primary
            if case_study.client.industry_secondary:
                industry += f" / {case_study.client.industry_secondary}"
            lines.append(f"Industry: {industry}")
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
