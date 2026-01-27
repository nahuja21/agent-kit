"""
Enhanced YAML Prompt Loader.

Adapted from agent-kit framework with:
- Parameter validation
- Template injection with {{variable}} syntax
- Caching for performance
- Support for agent-kit style YAML format
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from src.config_loader import get_config

logger = logging.getLogger(__name__)


@dataclass
class PromptParameter:
    """Parameter definition for prompt templates."""
    name: str
    type: str = "string"  # string, int, float, bool, list, dict
    required: bool = True
    default: Any = None
    description: Optional[str] = None
    
    def validate(self, value: Any) -> Any:
        """Validate and coerce a parameter value."""
        if value is None:
            if self.required and self.default is None:
                raise ValueError(f"Required parameter '{self.name}' is missing")
            return self.default
        
        # Type coercion
        type_map = {
            "string": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
        }
        
        expected_type = type_map.get(self.type)
        if expected_type and not isinstance(value, expected_type):
            try:
                return expected_type(value)
            except (ValueError, TypeError):
                raise ValueError(f"Parameter '{self.name}' must be {self.type}, got {type(value).__name__}")
        
        return value


@dataclass
class PromptConfig:
    """Complete prompt configuration loaded from YAML file."""
    step: str  # Extraction step name (e.g., "agreement_extraction")
    prompt: Dict[str, str]  # Contains "instructions" and optionally "user_template"
    parameters: List[PromptParameter] = field(default_factory=list)
    examples: List[Dict[str, Any]] = field(default_factory=list)
    
    @property
    def instructions(self) -> str:
        """Get the instructions (system prompt)."""
        return self.prompt.get("instructions", "")
    
    @property
    def user_template(self) -> str:
        """Get the user template."""
        return self.prompt.get("user_template", "")
    
    def get_required_parameters(self) -> List[str]:
        """Get list of required parameter names."""
        return [p.name for p in self.parameters if p.required]
    
    def get_defaults(self) -> Dict[str, Any]:
        """Get dictionary of parameter defaults."""
        return {p.name: p.default for p in self.parameters if p.default is not None}
    
    def validate_parameters(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and prepare parameters for injection."""
        result = dict(params)
        
        # Check required parameters
        for param in self.parameters:
            if param.name not in result:
                if param.required and param.default is None:
                    raise ValueError(f"Missing required parameter: {param.name}")
                if param.default is not None:
                    result[param.name] = param.default
            else:
                result[param.name] = param.validate(result[param.name])
        
        return result


class EnhancedPromptLoader:
    """
    Enhanced prompt loader with caching and validation.
    
    Supports two YAML formats:
    1. Agent-kit style: {step, prompt: {instructions, user_template}, parameters: [...]}
    2. Legacy style: {system_prompt, user_template, examples}
    """
    
    def __init__(self, prompts_dir: Optional[Path] = None):
        """
        Initialize the prompt loader.
        
        Args:
            prompts_dir: Directory containing prompt YAML files.
                        If None, uses config.paths.prompts relative to project root.
        """
        self._cache: Dict[str, PromptConfig] = {}
        
        if prompts_dir:
            self.prompts_dir = prompts_dir
        else:
            config = get_config()
            self.prompts_dir = config.project_root / config.paths.prompts
        
        logger.debug(f"PromptLoader initialized with prompts_dir: {self.prompts_dir}")
    
    def _find_prompt_file(self, prompt_name: str) -> Path:
        """Find the prompt file, handling nested paths."""
        # Try direct path first
        direct_path = self.prompts_dir / f"{prompt_name}.yaml"
        if direct_path.exists():
            return direct_path
        
        # Try with subdirectory (e.g., "agent/anchor_detection")
        if "/" in prompt_name:
            nested_path = self.prompts_dir / f"{prompt_name}.yaml"
            if nested_path.exists():
                return nested_path
        
        raise FileNotFoundError(f"Prompt file not found: {prompt_name}.yaml in {self.prompts_dir}")
    
    def _parse_parameters(self, params_data: List[Dict[str, Any]]) -> List[PromptParameter]:
        """Parse parameter definitions from YAML."""
        parameters = []
        for p in params_data:
            parameters.append(PromptParameter(
                name=p.get("name", ""),
                type=p.get("type", "string"),
                required=p.get("required", True),
                default=p.get("default"),
                description=p.get("description"),
            ))
        return parameters
    
    def load_prompt(self, prompt_name: str) -> PromptConfig:
        """
        Load a prompt configuration from YAML file.
        
        Args:
            prompt_name: Name of the prompt (without .yaml extension).
                        Can include subdirectory like "agent/anchor_detection".
        
        Returns:
            PromptConfig instance.
        """
        # Check cache
        if prompt_name in self._cache:
            return self._cache[prompt_name]
        
        prompt_path = self._find_prompt_file(prompt_name)
        
        with open(prompt_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        # Detect format and normalize
        if "prompt" in data:
            # Agent-kit style format
            config = PromptConfig(
                step=data.get("step", prompt_name),
                prompt=data["prompt"],
                parameters=self._parse_parameters(data.get("parameters", [])),
                examples=data.get("examples", []),
            )
        else:
            # Legacy style format - convert to new format
            prompt_dict = {}
            if "system_prompt" in data:
                prompt_dict["instructions"] = data["system_prompt"]
            if "user_template" in data:
                prompt_dict["user_template"] = data["user_template"]
            
            config = PromptConfig(
                step=prompt_name,
                prompt=prompt_dict,
                parameters=[],  # Legacy format doesn't have typed parameters
                examples=data.get("examples", []),
            )
        
        self._cache[prompt_name] = config
        return config
    
    def render_template(self, template: str, variables: Dict[str, Any]) -> str:
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
                    str_value = "\n".join(f"- {v}" for v in value)
                elif value is None:
                    str_value = "null"
                else:
                    str_value = str(value)
                result = result.replace(placeholder, str_value)
        
        return result
    
    def get_prompt(
        self,
        prompt_name: str,
        **variables: Any,
    ) -> tuple[str, str]:
        """
        Load and render a prompt with variables.
        
        Args:
            prompt_name: Name of the prompt file
            **variables: Template variables to substitute
            
        Returns:
            Tuple of (instructions, user_content)
        """
        config = self.load_prompt(prompt_name)
        
        # Validate parameters if defined
        if config.parameters:
            variables = config.validate_parameters(variables)
        
        # Render templates
        instructions = self.render_template(config.instructions, variables)
        user_content = self.render_template(config.user_template, variables)
        
        return instructions, user_content
    
    def clear_cache(self) -> None:
        """Clear the prompt cache."""
        self._cache.clear()


# Global loader instance
_loader: Optional[EnhancedPromptLoader] = None


def get_prompt_loader() -> EnhancedPromptLoader:
    """Get the global prompt loader instance."""
    global _loader
    if _loader is None:
        _loader = EnhancedPromptLoader()
    return _loader


def get_prompt(prompt_name: str, **variables: Any) -> tuple[str, str]:
    """
    Convenience function to load and render a prompt.
    
    Args:
        prompt_name: Name of the prompt file
        **variables: Template variables to substitute
        
    Returns:
        Tuple of (instructions, user_content)
    """
    return get_prompt_loader().get_prompt(prompt_name, **variables)


# ============================================================================
# Convenience functions for each extraction step
# ============================================================================

def get_anchor_detection_prompt(directory_tree: str) -> tuple[str, str]:
    """Get the anchor detection prompt."""
    return get_prompt("agent/anchor_detection", directory_tree=directory_tree)


def get_file_selection_prompt(directory_tree: str, file_count: int = 30) -> tuple[str, str]:
    """Get the file selection prompt."""
    return get_prompt("file_selection", directory_tree=directory_tree, file_count=file_count)


def get_agreement_extraction_prompt(agreement_content: str) -> tuple[str, str]:
    """Get the agreement extraction prompt."""
    return get_prompt("agreement_extraction", agreement_content=agreement_content)


def get_category_extraction_prompt(
    categories_list: List[str],
    document_contents: str,
    category_count: int,
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
    initial_categories: List[str],
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
