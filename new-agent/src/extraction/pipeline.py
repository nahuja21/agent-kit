"""
Multi-Pass Extraction Pipeline.

Breaks extraction into focused passes for better accuracy:
1. File Selection
2. Agreement Extraction
3. Category Extraction  
4. Impact/Narrative Extraction
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional

from src.llm.client import OpenAIClient, LLMResponse
from src.prompts.loader import (
    get_file_selection_prompt,
    get_agreement_extraction_prompt,
    get_category_extraction_prompt,
    get_impact_extraction_prompt,
)


@dataclass
class ExtractionResult:
    """Results from the extraction pipeline."""
    
    # Pass 1: File Selection
    categories_found: List[str] = field(default_factory=list)
    selected_files: List[str] = field(default_factory=list)
    
    # Pass 2: Agreement Data
    agreement_data: Dict[str, Any] = field(default_factory=dict)
    
    # Pass 3: Category Data
    categories_data: List[Dict[str, Any]] = field(default_factory=list)
    
    # Pass 4: Impact/Narrative Data
    impact_data: Dict[str, Any] = field(default_factory=dict)
    
    # Web Search Data
    web_search_data: str = ""
    
    # Reasoning logs
    reasoning_logs: List[Dict[str, str]] = field(default_factory=list)
    
    # Token usage
    total_input_tokens: int = 0
    total_output_tokens: int = 0


class ExtractionPipeline:
    """
    Multi-pass extraction pipeline.
    
    Breaks extraction into focused passes:
    1. File Selection (identify categories, select files)
    2. Agreement Extraction (fee, scope, initial categories)
    3. Category Extraction (details for each category)
    4. Impact Extraction (narrative, proof points)
    """
    
    def __init__(self, llm_client: OpenAIClient):
        self.llm = llm_client
        self.result = ExtractionResult()
    
    def run_pass_1_file_selection(
        self,
        directory_tree: str,
        file_count: int = 30
    ) -> tuple[List[str], List[str]]:
        """
        Pass 1: Select files and identify categories.
        
        Returns:
            Tuple of (categories_found, selected_files)
        """
        system_prompt, user_prompt = get_file_selection_prompt(
            directory_tree=directory_tree,
            file_count=file_count,
        )
        
        response = self.llm.analyze(system_prompt, user_prompt)
        self._log_reasoning("file_selection", response)
        
        # Parse response
        try:
            content = self._extract_json(response.content)
            parsed = json.loads(content)
            
            self.result.categories_found = parsed.get("categories_found", [])
            self.result.selected_files = parsed.get("selected_files", [])
            
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse file selection response: {e}")
        
        return self.result.categories_found, self.result.selected_files
    
    def run_pass_2_agreement(
        self,
        agreement_content: str
    ) -> Dict[str, Any]:
        """
        Pass 2: Extract Agreement data (Exhibit A & B).
        
        Returns:
            Agreement data dict
        """
        system_prompt, user_prompt = get_agreement_extraction_prompt(
            agreement_content=agreement_content,
        )
        
        response = self.llm.analyze(system_prompt, user_prompt)
        self._log_reasoning("agreement_extraction", response)
        
        # Parse response
        try:
            content = self._extract_json(response.content)
            self.result.agreement_data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse agreement response: {e}")
        
        return self.result.agreement_data
    
    def run_pass_3_categories(
        self,
        categories_list: List[str],
        document_contents: str
    ) -> List[Dict[str, Any]]:
        """
        Pass 3: Extract category details.
        
        Returns:
            List of category data dicts
        """
        system_prompt, user_prompt = get_category_extraction_prompt(
            categories_list=categories_list,
            document_contents=document_contents,
            category_count=len(categories_list),
        )
        
        response = self.llm.analyze(system_prompt, user_prompt)
        self._log_reasoning("category_extraction", response)
        
        # Parse response
        try:
            content = self._extract_json(response.content)
            parsed = json.loads(content)
            self.result.categories_data = parsed.get("categories", [])
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse category response: {e}")
        
        return self.result.categories_data
    
    def run_pass_4_impact(
        self,
        web_search_results: str,
        document_contents: str,
        category_summary: str
    ) -> Dict[str, Any]:
        """
        Pass 4: Extract impact and narrative.
        
        Returns:
            Impact data dict
        """
        # Get agreement data for context
        agreement = self.result.agreement_data
        
        system_prompt, user_prompt = get_impact_extraction_prompt(
            web_search_results=web_search_results,
            document_contents=document_contents,
            initial_categories=agreement.get("initial_categories", []),
            addressable_spend=agreement.get("addressable_spend", 0),
            savings_low=agreement.get("savings_estimate_low", 0),
            savings_high=agreement.get("savings_estimate_high", 0),
            category_summary=category_summary,
        )
        
        response = self.llm.analyze(system_prompt, user_prompt)
        self._log_reasoning("impact_extraction", response)
        
        # Parse response
        try:
            content = self._extract_json(response.content)
            self.result.impact_data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse impact response: {e}")
        
        return self.result.impact_data
    
    def run_web_search(self, client_name: str) -> str:
        """Run web search for company info."""
        query = f"{client_name} company revenue employees locations"
        response = self.llm.web_search(query)
        self._log_reasoning("web_search", response)
        self.result.web_search_data = response.content
        return response.content
    
    def _extract_json(self, content: str) -> str:
        """Extract JSON from response, handling markdown code blocks."""
        content = content.strip()
        
        # Handle ```json blocks
        if "```json" in content:
            start = content.find("```json") + 7
            end = content.find("```", start)
            if end > start:
                content = content[start:end].strip()
        elif "```" in content:
            start = content.find("```") + 3
            end = content.find("```", start)
            if end > start:
                content = content[start:end].strip()
        
        return content
    
    def _log_reasoning(self, pass_name: str, response: LLMResponse) -> None:
        """Log reasoning from a pass."""
        self.result.reasoning_logs.append({
            "pass": pass_name,
            "reasoning": response.reasoning or "",
            "content_preview": response.content[:500] if response.content else "",
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
        })
        self.result.total_input_tokens += response.input_tokens
        self.result.total_output_tokens += response.output_tokens
    
    def get_reasoning_log(self) -> str:
        """Generate full reasoning log as text."""
        lines = [
            "=" * 80,
            "EXTRACTION PIPELINE REASONING LOG",
            "=" * 80,
            "",
        ]
        
        for log in self.result.reasoning_logs:
            lines.extend([
                f"### {log['pass'].upper()}",
                f"Tokens: {log['input_tokens']:,} in / {log['output_tokens']:,} out",
                "",
                "Reasoning Summary:",
                log['reasoning'] or "(No reasoning captured)",
                "",
                "-" * 40,
                "",
            ])
        
        lines.extend([
            "",
            f"Total Tokens: {self.result.total_input_tokens:,} in / {self.result.total_output_tokens:,} out",
        ])
        
        return "\n".join(lines)
