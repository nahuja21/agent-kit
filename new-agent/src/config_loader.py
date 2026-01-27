"""
Configuration loader for new-agent.

Loads configuration from YAML file with environment variable substitution.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


@dataclass
class DebugPromptsConfig:
    """Debug prompts configuration."""
    enabled: bool = False
    directory: str = "outputs/debug_prompts"
    max_files: int = 50


@dataclass
class OpenAIConfig:
    """OpenAI API configuration."""
    api_key: str = ""
    model: str = "o3"
    reasoning_effort: str = "medium"
    max_output_tokens: int = 16000
    output_token_ratio: float = 0.25
    model_limits: Dict[str, int] = field(default_factory=lambda: {"default": 128000})
    step_models: Dict[str, str] = field(default_factory=dict)
    step_reasoning: Dict[str, str] = field(default_factory=dict)
    request_timeout: int = 120
    retry_attempts: int = 3
    debug_prompts: DebugPromptsConfig = field(default_factory=DebugPromptsConfig)


@dataclass
class ExtractionConfig:
    """Extraction pipeline configuration."""
    max_files_to_select: int = 30
    max_chars_agreement: int = 40000
    max_chars_default: int = 20000
    excel_max_rows: int = 100
    excel_max_cols: int = 20


@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str = "INFO"
    format: str = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    datefmt: str = "%H:%M:%S"


@dataclass
class PathsConfig:
    """Paths configuration."""
    inputs: str = "inputs"
    outputs: str = "outputs"
    prompts: str = "prompts"


@dataclass
class AppConfig:
    """Main application configuration."""
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    
    # Resolved paths (set after loading)
    project_root: Path = field(default_factory=lambda: Path(__file__).parent.parent)


# Global configuration instance
_config: Optional[AppConfig] = None


def _substitute_env_vars(value: Any) -> Any:
    """Substitute ${VAR} patterns with environment variable values."""
    if isinstance(value, str):
        pattern = r'\$\{([^}]+)\}'
        matches = re.findall(pattern, value)
        for var_name in matches:
            env_value = os.environ.get(var_name, "")
            value = value.replace(f"${{{var_name}}}", env_value)
        return value
    elif isinstance(value, dict):
        return {k: _substitute_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_substitute_env_vars(item) for item in value]
    return value


def _dict_to_debug_prompts_config(data: Dict[str, Any]) -> DebugPromptsConfig:
    """Convert dict to DebugPromptsConfig."""
    return DebugPromptsConfig(
        enabled=data.get("enabled", False),
        directory=data.get("directory", "outputs/debug_prompts"),
        max_files=data.get("max_files", 50),
    )


def _dict_to_openai_config(data: Dict[str, Any]) -> OpenAIConfig:
    """Convert dict to OpenAIConfig."""
    debug_prompts_data = data.get("debug_prompts", {})
    return OpenAIConfig(
        api_key=data.get("api_key", ""),
        model=data.get("model", "o3"),
        reasoning_effort=data.get("reasoning_effort", "medium"),
        max_output_tokens=data.get("max_output_tokens", 16000),
        output_token_ratio=data.get("output_token_ratio", 0.25),
        model_limits=data.get("model_limits", {"default": 128000}),
        step_models=data.get("step_models", {}),
        step_reasoning=data.get("step_reasoning", {}),
        request_timeout=data.get("request_timeout", 120),
        retry_attempts=data.get("retry_attempts", 3),
        debug_prompts=_dict_to_debug_prompts_config(debug_prompts_data),
    )


def _dict_to_extraction_config(data: Dict[str, Any]) -> ExtractionConfig:
    """Convert dict to ExtractionConfig."""
    return ExtractionConfig(
        max_files_to_select=data.get("max_files_to_select", 30),
        max_chars_agreement=data.get("max_chars_agreement", 40000),
        max_chars_default=data.get("max_chars_default", 20000),
        excel_max_rows=data.get("excel_max_rows", 100),
        excel_max_cols=data.get("excel_max_cols", 20),
    )


def _dict_to_logging_config(data: Dict[str, Any]) -> LoggingConfig:
    """Convert dict to LoggingConfig."""
    return LoggingConfig(
        level=data.get("level", "INFO"),
        format=data.get("format", "%(asctime)s - %(levelname)s - %(name)s - %(message)s"),
        datefmt=data.get("datefmt", "%H:%M:%S"),
    )


def _dict_to_paths_config(data: Dict[str, Any]) -> PathsConfig:
    """Convert dict to PathsConfig."""
    return PathsConfig(
        inputs=data.get("inputs", "inputs"),
        outputs=data.get("outputs", "outputs"),
        prompts=data.get("prompts", "prompts"),
    )


def load_config(config_path: Optional[Path] = None) -> AppConfig:
    """
    Load configuration from YAML file.
    
    Args:
        config_path: Path to config file. If None, uses default location.
        
    Returns:
        Loaded AppConfig instance.
    """
    global _config
    
    if _config is not None:
        return _config
    
    project_root = Path(__file__).parent.parent
    
    if config_path is None:
        config_path = project_root / "config.yaml"
    
    if not config_path.exists():
        # Return defaults if no config file
        _config = AppConfig(project_root=project_root)
        return _config
    
    with open(config_path, "r", encoding="utf-8") as f:
        raw_data = yaml.safe_load(f)
    
    # Substitute environment variables
    data = _substitute_env_vars(raw_data)
    
    # Build config
    _config = AppConfig(
        openai=_dict_to_openai_config(data.get("openai", {})),
        extraction=_dict_to_extraction_config(data.get("extraction", {})),
        logging=_dict_to_logging_config(data.get("logging", {})),
        paths=_dict_to_paths_config(data.get("paths", {})),
        project_root=project_root,
    )
    
    return _config


def get_config() -> AppConfig:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def get_model_for_step(step_name: str) -> str:
    """Get the model to use for a specific extraction step."""
    config = get_config()
    return config.openai.step_models.get(step_name, config.openai.model)


def get_reasoning_for_step(step_name: str) -> str:
    """Get the reasoning effort for a specific extraction step."""
    config = get_config()
    return config.openai.step_reasoning.get(step_name, config.openai.reasoning_effort)


def get_model_limit(model: str) -> int:
    """Get the context limit for a model."""
    config = get_config()
    return config.openai.model_limits.get(model, config.openai.model_limits.get("default", 128000))
