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
    
    Args:
        prompt_name: Name of the prompt file
        **variables: Template variables to substitute
        
    Returns:
        Tuple of (system_prompt, user_prompt)
    """
    prompt_data = load_prompt(prompt_name)
    
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
