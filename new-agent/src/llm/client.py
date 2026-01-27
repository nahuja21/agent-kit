"""OpenAI client using the Responses API with o3 support."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List, Dict, Any

from openai import OpenAI

from src.config import OPENAI_API_KEY, MODEL, MAX_TOKENS, REASONING_EFFORT


@dataclass
class LLMResponse:
    """Structured response from LLM."""
    content: str
    reasoning: Optional[str]
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int


class OpenAIClient:
    """OpenAI client using the Responses API with o3 reasoning support."""
    
    def __init__(self):
        """Initialize the OpenAI client."""
        self.client = OpenAI(api_key=OPENAI_API_KEY)
        self.model = MODEL
        self.reasoning_effort = REASONING_EFFORT
    
    def analyze(
        self,
        system_prompt: str,
        user_content: str,
        reasoning_effort: Optional[str] = None
    ) -> LLMResponse:
        """
        Send content to OpenAI for analysis using the Responses API.
        
        Args:
            system_prompt: Background context and instructions
            user_content: The content to analyze
            reasoning_effort: Override reasoning effort (low/medium/high)
            
        Returns:
            LLMResponse with content, reasoning, and token usage
        """
        effort = reasoning_effort or self.reasoning_effort
        
        # Build input for Responses API
        input_content = [{"role": "user", "content": user_content}]
        
        # Build reasoning config for o3 models
        is_reasoning_model = self.model.startswith("o1") or self.model.startswith("o3")
        reasoning_config = None
        if is_reasoning_model:
            reasoning_config = {
                "effort": effort,
                "summary": "auto"  # Get reasoning summary
            }
        
        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=system_prompt,
                input=input_content,
                max_output_tokens=MAX_TOKENS,
                reasoning=reasoning_config,
            )
            
            content = self._extract_text_content(response)
            reasoning = self._extract_reasoning(response)
            
            input_tokens = response.usage.input_tokens if response.usage else 0
            output_tokens = response.usage.output_tokens if response.usage else 0
            
            return LLMResponse(
                content=content,
                reasoning=reasoning,
                model=self.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            )
            
        except Exception as e:
            raise RuntimeError(f"Responses API call failed: {e}")
    
    def _extract_text_content(self, response) -> str:
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
    
    def _extract_reasoning(self, response) -> Optional[str]:
        """Extract reasoning summary from response (for o3 models)."""
        reasoning_parts = []
        
        if hasattr(response, 'output'):
            for block in response.output:
                if hasattr(block, 'type') and block.type == 'reasoning':
                    if hasattr(block, 'summary'):
                        for item in block.summary:
                            if hasattr(item, 'text'):
                                reasoning_parts.append(item.text)
        
        return "\n".join(reasoning_parts) if reasoning_parts else None
    
    def analyze_image(
        self,
        image_base64: str,
        prompt: str,
        detail: str = "high"
    ) -> LLMResponse:
        """
        Analyze an image using GPT-4o Vision.
        
        Args:
            image_base64: Base64-encoded image data
            prompt: What to extract/analyze from the image
            detail: Image detail level ("low", "high", "auto")
            
        Returns:
            LLMResponse with extracted content
        """
        try:
            response = self.client.responses.create(
                model="gpt-4o",  # Vision requires gpt-4o
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_image",
                                "image_url": f"data:image/png;base64,{image_base64}",
                                "detail": detail,
                            },
                            {
                                "type": "input_text",
                                "text": prompt,
                            },
                        ],
                    }
                ],
                max_output_tokens=4000,
            )
            
            content = self._extract_text_content(response)
            
            input_tokens = response.usage.input_tokens if response.usage else 0
            output_tokens = response.usage.output_tokens if response.usage else 0
            
            return LLMResponse(
                content=content or "",
                reasoning=None,
                model="gpt-4o-vision",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            )
            
        except Exception as e:
            return LLMResponse(
                content=f"Vision API failed: {e}",
                reasoning=None,
                model="error",
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
            )
    
    def web_search(self, query: str) -> LLMResponse:
        """
        Search the web for information using OpenAI's web search tool.
        
        Args:
            query: The search query
            
        Returns:
            LLMResponse with search results
        """
        try:
            response = self.client.responses.create(
                model="gpt-4o",  # Web search uses gpt-4o
                tools=[{"type": "web_search_preview"}],
                input=f"Search the web for: {query}. Return key facts with source URLs.",
                max_output_tokens=2000,
            )
            
            content = self._extract_text_content(response)
            
            input_tokens = response.usage.input_tokens if response.usage else 0
            output_tokens = response.usage.output_tokens if response.usage else 0
            
            return LLMResponse(
                content=content or "No results found",
                reasoning=None,
                model="gpt-4o-web-search",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            )
            
        except Exception as e:
            return LLMResponse(
                content=f"Web search failed: {e}. Manually lookup: {query}",
                reasoning=None,
                model="error",
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
            )
