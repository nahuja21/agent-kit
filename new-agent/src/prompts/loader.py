"""
YAML Prompt Loader.

Loads prompts from YAML files and renders templates with variables.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


# Base path for prompt files
PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def load_prompt(prompt_name: str) -> Dict[str, Any]:
    """
    Load a prompt from a YAML file.
    
    Args:
        prompt_name: Name of the prompt file (without .yaml extension)
        
    Returns:
        Dict containing system_prompt, user_template, and examples
    """
    prompt_file = PROMPTS_DIR / f"{prompt_name}.yaml"
    
    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")
    
    with open(prompt_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def render_template(template: str, variables: Dict[str, Any]) -> str:
    """
    Render a template with variables using {{variable}} syntax.
    
    Args:
        template: Template string with {{variable}} placeholders
        variables: Dict of variable names to values
        
    Returns:
        Rendered template string
    """
    result = template
    
    for key, value in variables.items():
        placeholder = "{{" + key + "}}"
        if placeholder in result:
            # Convert value to string, handle lists nicely
            if isinstance(value, list):
                str_value = ", ".join(str(v) for v in value)
            elif value is None:
                str_value = "null"
            else:
                str_value = str(value)
            result = result.replace(placeholder, str_value)
    
    return result


def get_prompt(
    prompt_name: str,
    **variables: Any
) -> tuple[str, str]:
    """
    Load and render a prompt.
    
    Supports both formats:
    - Legacy: {system_prompt, user_template}
    - Agent-kit style: {prompt: {instructions, user_template}}
    
    Args:
        prompt_name: Name of the prompt file
        **variables: Template variables to substitute
        
    Returns:
        Tuple of (system_prompt, user_prompt)
    """
    prompt_data = load_prompt(prompt_name)
    
    # Handle both formats
    if "prompt" in prompt_data:
        # Agent-kit style format: {prompt: {instructions, user_template}}
        prompt_section = prompt_data["prompt"]
        system_prompt = prompt_section.get("instructions", "")
        user_template = prompt_section.get("user_template", "")
    else:
        # Legacy format: {system_prompt, user_template}
        system_prompt = prompt_data.get("system_prompt", "")
        user_template = prompt_data.get("user_template", "")
    
    # Render templates
    system_prompt = render_template(system_prompt, variables)
    user_prompt = render_template(user_template, variables)
    
    return system_prompt, user_prompt


# Convenience functions for each prompt type

def get_file_selection_prompt(
    directory_tree: str,
    file_count: int = 30
) -> tuple[str, str]:
    """Get the file selection prompt."""
    return get_prompt(
        "file_selection",
        directory_tree=directory_tree,
        file_count=file_count,
    )


def get_agreement_extraction_prompt(
    agreement_content: str
) -> tuple[str, str]:
    """Get the agreement extraction prompt."""
    return get_prompt(
        "agreement_extraction",
        agreement_content=agreement_content,
    )


def get_category_extraction_prompt(
    categories_list: list[str],
    document_contents: str,
    category_count: int
) -> tuple[str, str]:
    """Get the category extraction prompt."""
    return get_prompt(
        "category_extraction",
        categories_list=categories_list,
        document_contents=document_contents,
        category_count=category_count,
    )


def get_impact_extraction_prompt(
    web_search_results: str,
    document_contents: str,
    initial_categories: list[str],
    addressable_spend: float,
    savings_low: float,
    savings_high: float,
    category_summary: str,
) -> tuple[str, str]:
    """Get the impact extraction prompt."""
    return get_prompt(
        "impact_extraction",
        web_search_results=web_search_results,
        document_contents=document_contents,
        initial_categories=initial_categories,
        addressable_spend=addressable_spend,
        savings_low=savings_low,
        savings_high=savings_high,
        category_summary=category_summary,
    )


def get_anchor_detection_prompt(
    directory_tree: str,
) -> tuple[str, str]:
    """Get the anchor detection prompt for /agent command."""
    return get_prompt(
        "agent/anchor_detection",
        directory_tree=directory_tree,
    )


def get_project_scope_prompt(
    agreement_content: str,
) -> tuple[str, str]:
    """
    Get the project scope extraction prompt for Step 3.
    
    Extracts from Agreement document:
    - Exhibit A: Categories, spend, addressable, savings estimates
    - Exhibit B: Fee structure (fixed, hybrid, or contingent)
    """
    return get_prompt(
        "agent/project_scope_extraction",
        agreement_content=agreement_content,
    )


def get_client_context_prompt(
    client_name_hint: str,
    web_search_results: str,
    document_contents: str,
) -> tuple[str, str]:
    """
    Get the client context extraction prompt for Step 4.
    
    Extracts client background and company information:
    - Client name, industry, business model
    - PE sponsor (if applicable)
    - Size metrics: revenue, EBITDA, locations, employees
    
    Sources: Assessment, Case Study, Agreement, Kick-off, and Web Search
    """
    return get_prompt(
        "agent/client_context_extraction",
        client_name_hint=client_name_hint,
        web_search_results=web_search_results,
        document_contents=document_contents,
    )


def get_engagement_background_prompt(
    client_name: str,
    document_contents: str,
) -> tuple[str, str]:
    """
    Get the engagement background extraction prompt for Step 5.
    
    Extracts engagement context:
    - Objective: Why the engagement
    - Scope summary: What's in/out of scope
    - Constraints/challenges: Array of obstacles
    - Procurement environment: operating model, maturity, data availability
    
    Sources: Agreement, Assessment, Case Study, Kick-off
    """
    return get_prompt(
        "agent/engagement_background_extraction",
        client_name=client_name,
        document_contents=document_contents,
    )


def get_impact_prompt(
    client_name: str,
    document_contents: str,
    initial_categories: str = "",
    addressable_spend: float = 0,
    savings_low: float = 0,
    savings_high: float = 0,
) -> tuple[str, str]:
    """
    Get the impact extraction prompt for Step 6.
    
    Extracts ACTUAL achieved results:
    - Summary: headline, narrative
    - Financials: annual_savings, one_time_savings (ACTUAL, not estimates)
    - Time to value: days to first savings
    - Operational improvements
    - Proof points with evidence
    
    Sources: Case Study, Project Updates, Project Close Out
    """
    return get_prompt(
        "agent/impact_extraction",
        client_name=client_name,
        document_contents=document_contents,
        initial_categories=initial_categories,
        addressable_spend=addressable_spend,
        savings_low=savings_low,
        savings_high=savings_high,
    )


def get_categories_prompt(
    client_name: str,
    category_list: str,
    exhibit_a_data: str,
    category_folder_contents: str,
    extraction_date: str,
) -> tuple[str, str]:
    """
    Get the categories extraction prompt for Step 7.
    
    Extracts detailed category information:
    - Vendors before/after
    - Levers used (GPO, RFP, consolidation, etc.)
    - Constraints (supplier, operational, contractual, implementation)
    - Baseline spend and savings with percentages
    - Evidence and notes
    
    Sources: Impact results (category list), Exhibit A (baseline), Category folders (details)
    """
    return get_prompt(
        "agent/categories_extraction",
        client_name=client_name,
        category_list=category_list,
        exhibit_a_data=exhibit_a_data,
        category_folder_contents=category_folder_contents,
        extraction_date=extraction_date,
    )


def get_case_study_generation_prompt(
    project_scope_data: str,
    client_context_data: str,
    engagement_background_data: str,
    impact_data: str,
    categories_data: str,
) -> tuple[str, str]:
    """
    Get the case study generation prompt for Step 8.
    
    Synthesizes ALL extracted data into polished case study content:
    - case_study_ready: Boolean assessment
    - headline: Marketing-ready headline
    - client_problem_statement: Problem faced
    - approach_summary: 3-5 bullets
    - top_levers: Ranked list
    - value_delivered_blurb: Value narrative
    - where_we_were_unique: Differentiators
    
    Input: All data from Steps 3-7
    """
    return get_prompt(
        "agent/case_study_generation",
        project_scope_data=project_scope_data,
        client_context_data=client_context_data,
        engagement_background_data=engagement_background_data,
        impact_data=impact_data,
        categories_data=categories_data,
    )
