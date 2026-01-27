"""
Enhanced OpenAI client with structured output and debug logging.

Features:
- Structured output with Pydantic model enforcement
- Debug logging (saves all prompts/responses to files)
- Per-step model and reasoning effort configuration
- Async support for better performance
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, TypeVar

from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel

from src.config_loader import (
    get_config,
    get_model_for_step,
    get_model_limit,
    get_reasoning_for_step,
)

logger = logging.getLogger(__name__)

# TypeVar for structured output
T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMResponse:
    """Structured response from LLM."""
    content: str
    reasoning: Optional[str]
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    parsed: Optional[Any] = None  # Parsed Pydantic model if structured output was used


class PromptDebugger:
    """Handles saving prompts and responses to files for debugging."""
    
    def __init__(self, enabled: bool, directory: str, max_files: int, project_root: Path):
        self.enabled = enabled
        self.directory = project_root / directory
        self.max_files = max_files
        
        if self.enabled:
            self.directory.mkdir(parents=True, exist_ok=True)
    
    def save(
        self,
        step_name: str,
        model: str,
        instructions: str,
        user_content: str,
        response: Optional[LLMResponse] = None,
        error: Optional[str] = None,
        iteration: int = 1,
    ) -> Optional[Path]:
        """Save prompt and response to a debug file."""
        if not self.enabled:
            return None
        
        try:
            timestamp = datetime.now()
            filename = f"{step_name}_iter-{iteration:02d}_{timestamp.strftime('%Y-%m-%d_%H-%M-%S')}.txt"
            debug_file = self.directory / filename
            
            lines = [
                "=" * 80,
                "CASE STUDY EXTRACTOR - PROMPT DEBUG",
                "=" * 80,
                f"Timestamp: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
                f"Step: {step_name}",
                f"Iteration: {iteration}",
                f"Model: {model}",
                "",
                "=" * 80,
                "INSTRUCTIONS (System Prompt)",
                "=" * 80,
                instructions,
                "",
                "=" * 80,
                "USER CONTENT",
                "=" * 80,
                user_content[:50000] + "..." if len(user_content) > 50000 else user_content,
                "",
            ]
            
            if response:
                lines.extend([
                    "=" * 80,
                    "RESPONSE",
                    "=" * 80,
                    f"Input Tokens: {response.input_tokens:,}",
                    f"Output Tokens: {response.output_tokens:,}",
                    f"Total Tokens: {response.total_tokens:,}",
                    "",
                ])
                
                if response.reasoning:
                    lines.extend([
                        "--- REASONING ---",
                        response.reasoning,
                        "",
                    ])
                
                lines.extend([
                    "--- CONTENT ---",
                    response.content,
                    "",
                ])
                
                if response.parsed:
                    lines.extend([
                        "--- PARSED (Pydantic) ---",
                        json.dumps(response.parsed.model_dump(), indent=2, default=str),
                        "",
                    ])
            
            if error:
                lines.extend([
                    "=" * 80,
                    "ERROR",
                    "=" * 80,
                    error,
                    "",
                ])
            
            lines.extend(["=" * 80, "END OF DEBUG", "=" * 80])
            
            debug_file.write_text("\n".join(lines), encoding="utf-8")
            logger.debug(f"Saved prompt debug to: {debug_file}")
            
            # Cleanup old files
            self._cleanup_old_files()
            
            return debug_file
            
        except Exception as e:
            logger.warning(f"Failed to save prompt debug: {e}")
            return None
    
    def _cleanup_old_files(self) -> None:
        """Remove old debug files, keeping only the most recent ones."""
        try:
            files = sorted(self.directory.glob("*.txt"), key=lambda f: f.stat().st_mtime)
            if len(files) > self.max_files:
                for file in files[:len(files) - self.max_files]:
                    file.unlink()
        except Exception as e:
            logger.warning(f"Failed to cleanup old debug files: {e}")


class EnhancedOpenAIClient:
    """
    Enhanced OpenAI client with structured output and debug logging.
    
    Features:
    - Structured output with Pydantic models
    - Debug logging for all prompts/responses
    - Per-step model configuration
    - Both sync and async methods
    """
    
    def __init__(self):
        """Initialize the enhanced OpenAI client."""
        self.config = get_config()
        self.sync_client = OpenAI(
            api_key=self.config.openai.api_key,
            timeout=self.config.openai.request_timeout,
            max_retries=self.config.openai.retry_attempts,
        )
        self.async_client = AsyncOpenAI(
            api_key=self.config.openai.api_key,
            timeout=self.config.openai.request_timeout,
            max_retries=self.config.openai.retry_attempts,
        )
        
        # Initialize debugger
        self.debugger = PromptDebugger(
            enabled=self.config.openai.debug_prompts.enabled,
            directory=self.config.openai.debug_prompts.directory,
            max_files=self.config.openai.debug_prompts.max_files,
            project_root=self.config.project_root,
        )
        
        logger.info(f"EnhancedOpenAIClient initialized (model={self.config.openai.model})")
        if self.config.openai.debug_prompts.enabled:
            logger.info(f"Debug prompts enabled: {self.config.openai.debug_prompts.directory}")
    
    def _is_reasoning_model(self, model: str) -> bool:
        """Check if model supports reasoning (o1, o3, etc.)."""
        return model.startswith("o1") or model.startswith("o3")
    
    def _extract_text_content(self, response: Any) -> str:
        """Extract text content from Responses API response."""
        content_parts = []
        
        if hasattr(response, 'output'):
            for block in response.output:
                if hasattr(block, 'type') and block.type == 'message':
                    if hasattr(block, 'content'):
                        for item in block.content:
                            if hasattr(item, 'text'):
                                content_parts.append(item.text)
        
        return "".join(content_parts)
    
    def _extract_reasoning(self, response: Any) -> Optional[str]:
        """Extract reasoning summary from response (for o1/o3 models)."""
        reasoning_parts = []
        
        if hasattr(response, 'output'):
            for block in response.output:
                if hasattr(block, 'type') and block.type == 'reasoning':
                    if hasattr(block, 'summary'):
                        for item in block.summary:
                            if hasattr(item, 'text'):
                                reasoning_parts.append(item.text)
        
        return "\n".join(reasoning_parts) if reasoning_parts else None
    
    def analyze(
        self,
        step_name: str,
        instructions: str,
        user_content: str,
        response_model: Optional[Type[T]] = None,
        reasoning_effort: Optional[str] = None,
        iteration: int = 1,
    ) -> LLMResponse:
        """
        Analyze content using the Responses API (synchronous).
        
        Args:
            step_name: Name of the extraction step (for model selection and logging)
            instructions: System prompt / instructions
            user_content: User message content
            response_model: Optional Pydantic model for structured output
            reasoning_effort: Override reasoning effort
            iteration: Iteration number for logging
            
        Returns:
            LLMResponse with content, reasoning, tokens, and optionally parsed model
        """
        model = get_model_for_step(step_name)
        effort = reasoning_effort or get_reasoning_for_step(step_name)
        
        # Build input
        input_content = [{"role": "user", "content": user_content}]
        
        # Build reasoning config
        reasoning_config = None
        if self._is_reasoning_model(model):
            reasoning_config = {"effort": effort, "summary": "auto"}
        
        # Build response format for structured output
        response_format = None
        if response_model:
            schema = response_model.model_json_schema()
            response_format = {
                "format": {
                    "type": "json_schema",
                    "name": response_model.__name__,
                    "schema": schema,
                    "strict": True,
                }
            }
        
        try:
            response = self.sync_client.responses.create(
                model=model,
                instructions=instructions,
                input=input_content,
                max_output_tokens=self.config.openai.max_output_tokens,
                reasoning=reasoning_config,
                text=response_format,
            )
            
            content = self._extract_text_content(response)
            reasoning = self._extract_reasoning(response)
            
            input_tokens = response.usage.input_tokens if response.usage else 0
            output_tokens = response.usage.output_tokens if response.usage else 0
            
            # Parse structured output if model provided
            parsed = None
            if response_model and content:
                try:
                    parsed = response_model.model_validate_json(content)
                except Exception as e:
                    logger.warning(f"Failed to parse structured output: {e}")
            
            llm_response = LLMResponse(
                content=content,
                reasoning=reasoning,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                parsed=parsed,
            )
            
            # Save debug log
            self.debugger.save(
                step_name=step_name,
                model=model,
                instructions=instructions,
                user_content=user_content,
                response=llm_response,
                iteration=iteration,
            )
            
            return llm_response
            
        except Exception as e:
            # Save debug log with error
            self.debugger.save(
                step_name=step_name,
                model=model,
                instructions=instructions,
                user_content=user_content,
                error=str(e),
                iteration=iteration,
            )
            raise RuntimeError(f"Responses API call failed: {e}")
    
    async def analyze_async(
        self,
        step_name: str,
        instructions: str,
        user_content: str,
        response_model: Optional[Type[T]] = None,
        reasoning_effort: Optional[str] = None,
        iteration: int = 1,
    ) -> LLMResponse:
        """
        Analyze content using the Responses API (asynchronous).
        
        Same as analyze() but async for better performance.
        """
        model = get_model_for_step(step_name)
        effort = reasoning_effort or get_reasoning_for_step(step_name)
        
        # Build input
        input_content = [{"role": "user", "content": user_content}]
        
        # Build reasoning config
        reasoning_config = None
        if self._is_reasoning_model(model):
            reasoning_config = {"effort": effort, "summary": "auto"}
        
        # Build response format for structured output
        response_format = None
        if response_model:
            schema = response_model.model_json_schema()
            response_format = {
                "format": {
                    "type": "json_schema",
                    "name": response_model.__name__,
                    "schema": schema,
                    "strict": True,
                }
            }
        
        try:
            response = await self.async_client.responses.create(
                model=model,
                instructions=instructions,
                input=input_content,
                max_output_tokens=self.config.openai.max_output_tokens,
                reasoning=reasoning_config,
                text=response_format,
            )
            
            content = self._extract_text_content(response)
            reasoning = self._extract_reasoning(response)
            
            input_tokens = response.usage.input_tokens if response.usage else 0
            output_tokens = response.usage.output_tokens if response.usage else 0
            
            # Parse structured output if model provided
            parsed = None
            if response_model and content:
                try:
                    parsed = response_model.model_validate_json(content)
                except Exception as e:
                    logger.warning(f"Failed to parse structured output: {e}")
            
            llm_response = LLMResponse(
                content=content,
                reasoning=reasoning,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                parsed=parsed,
            )
            
            # Save debug log
            self.debugger.save(
                step_name=step_name,
                model=model,
                instructions=instructions,
                user_content=user_content,
                response=llm_response,
                iteration=iteration,
            )
            
            return llm_response
            
        except Exception as e:
            # Save debug log with error
            self.debugger.save(
                step_name=step_name,
                model=model,
                instructions=instructions,
                user_content=user_content,
                error=str(e),
                iteration=iteration,
            )
            raise RuntimeError(f"Responses API call failed: {e}")
    
    def web_search(self, query: str) -> LLMResponse:
        """
        Search the web for information using OpenAI's web search tool.
        
        Args:
            query: The search query
            
        Returns:
            LLMResponse with search results
        """
        model = get_model_for_step("web_search")
        
        try:
            response = self.sync_client.responses.create(
                model=model,
                tools=[{"type": "web_search_preview"}],
                input=f"Search the web for: {query}. Return key facts with source URLs.",
                max_output_tokens=2000,
            )
            
            content = self._extract_text_content(response)
            
            input_tokens = response.usage.input_tokens if response.usage else 0
            output_tokens = response.usage.output_tokens if response.usage else 0
            
            llm_response = LLMResponse(
                content=content or "No results found",
                reasoning=None,
                model=f"{model}-web-search",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            )
            
            # Save debug log
            self.debugger.save(
                step_name="web_search",
                model=model,
                instructions="Web search tool",
                user_content=query,
                response=llm_response,
            )
            
            return llm_response
            
        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return LLMResponse(
                content=f"Web search failed: {e}. Manually lookup: {query}",
                reasoning=None,
                model="error",
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
            )


# Convenience function for backwards compatibility
def create_client() -> EnhancedOpenAIClient:
    """Create an enhanced OpenAI client instance."""
    return EnhancedOpenAIClient()
