"""
Example: Using the Enhanced LLM Client with Structured Output

This example demonstrates how to use the new infrastructure:
1. EnhancedOpenAIClient with debug logging and structured output
2. EnhancedPromptLoader with parameter validation
3. Per-step model configuration

Run from the new-agent directory:
    python -m examples.enhanced_extraction_example
"""

import asyncio
import json
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

# Import the new enhanced modules
from src.config_loader import get_config, load_config
from src.llm.enhanced_client import EnhancedOpenAIClient
from src.prompts.enhanced_loader import get_prompt, get_prompt_loader


# ============================================================================
# Pydantic Models for Structured Output
# ============================================================================

class AnchorFile(BaseModel):
    """Single anchor file/folder detection result."""
    found: bool
    type: Optional[str] = None  # "file", "folder", "files"
    path: Optional[str] = None
    paths: Optional[List[str]] = None  # For project_updates
    date_in_name: Optional[str] = None


class AnchorDetectionResult(BaseModel):
    """Full anchor detection result with all anchor types."""
    agreement: AnchorFile
    assessment: AnchorFile
    case_study: AnchorFile
    kickoff: AnchorFile
    project_updates: AnchorFile
    project_close_out: AnchorFile


class AgreementExtractionResult(BaseModel):
    """Structured output for agreement extraction."""
    initial_categories: List[str] = Field(default_factory=list)
    addressable_spend: Optional[float] = None
    savings_estimate_low: Optional[float] = None
    savings_estimate_high: Optional[float] = None
    fee_type: Optional[str] = None  # "fixed", "contingent", "hybrid"
    fee_amount: Optional[float] = None
    fee_percentage: Optional[float] = None
    minimum_savings_guarantee: Optional[float] = None
    start_date: Optional[str] = None
    source_file: Optional[str] = None


class CategoryResult(BaseModel):
    """Single category extraction result."""
    category_name: str
    status: str = "unknown"
    baseline_spend: Optional[float] = None
    savings_amount: Optional[float] = None
    savings_percentage: Optional[float] = None
    levers: List[str] = Field(default_factory=list)
    vendors_before: List[str] = Field(default_factory=list)
    vendors_after: List[str] = Field(default_factory=list)
    source_file: Optional[str] = None
    confidence: str = "low"
    notes: Optional[str] = None


class CategoryExtractionResult(BaseModel):
    """Structured output for category extraction."""
    categories: List[CategoryResult]


# ============================================================================
# Example Usage
# ============================================================================

def example_basic_usage():
    """Example: Basic usage with the enhanced client."""
    print("\n" + "=" * 60)
    print("Example 1: Basic Usage with Enhanced Client")
    print("=" * 60)
    
    # Initialize config (loads from config.yaml)
    config = load_config()
    print(f"Config loaded: model={config.openai.model}, debug={config.openai.debug_prompts.enabled}")
    
    # Create enhanced client
    client = EnhancedOpenAIClient()
    
    # Simple analysis without structured output
    response = client.analyze(
        step_name="test",
        instructions="You are a helpful assistant.",
        user_content="What is 2 + 2? Reply with just the number.",
    )
    
    print(f"\nResponse: {response.content}")
    print(f"Model: {response.model}")
    print(f"Tokens: {response.total_tokens}")
    if response.reasoning:
        print(f"Reasoning: {response.reasoning[:200]}...")


def example_structured_output():
    """Example: Using structured output with Pydantic models."""
    print("\n" + "=" * 60)
    print("Example 2: Structured Output with Pydantic")
    print("=" * 60)
    
    # Create enhanced client
    client = EnhancedOpenAIClient()
    
    # Mock directory tree for anchor detection
    mock_directory = """
    Savida/
    ├── Agreement/
    │   └── Procurement Cost Reduction Services Agreement.pdf
    ├── Assessment/
    │   └── Initial Assessment.pptx
    ├── Case Study/
    │   └── Savida Case Study Final.pdf
    ├── Project Updates/
    │   ├── Project Update 2024-10-15.pptx
    │   └── Project Update 2024-11-01.pptx
    └── Categories/
        ├── Medical Supplies/
        └── Office Supplies/
    """
    
    # Get prompt using the enhanced loader
    instructions, user_content = get_prompt(
        "agent/anchor_detection",
        directory_tree=mock_directory,
    )
    
    print(f"\nPrompt loaded. Instructions length: {len(instructions)} chars")
    
    # Call with structured output - the response will be validated against the model
    response = client.analyze(
        step_name="anchor_detection",
        instructions=instructions,
        user_content=user_content,
        response_model=AnchorDetectionResult,  # <-- This enforces the schema!
    )
    
    print(f"\nStructured output parsed: {response.parsed is not None}")
    
    if response.parsed:
        result: AnchorDetectionResult = response.parsed
        print(f"\nAnchor Detection Results:")
        print(f"  Agreement found: {result.agreement.found} -> {result.agreement.path}")
        print(f"  Assessment found: {result.assessment.found} -> {result.assessment.path}")
        print(f"  Case Study found: {result.case_study.found} -> {result.case_study.path}")
        print(f"  Project Updates: {result.project_updates.paths}")
    
    print(f"\nTokens used: {response.total_tokens}")


def example_prompt_loader():
    """Example: Using the enhanced prompt loader."""
    print("\n" + "=" * 60)
    print("Example 3: Enhanced Prompt Loader")
    print("=" * 60)
    
    loader = get_prompt_loader()
    
    # Load agreement extraction prompt
    config = loader.load_prompt("agreement_extraction")
    
    print(f"Loaded prompt: {config.step}")
    print(f"Parameters: {[p.name for p in config.parameters]}")
    print(f"Required: {config.get_required_parameters()}")
    print(f"Instructions preview: {config.instructions[:100]}...")
    
    # Render with parameters
    instructions, user_content = loader.get_prompt(
        "agreement_extraction",
        agreement_content="[Agreement content would go here...]",
    )
    
    print(f"\nRendered user_content length: {len(user_content)} chars")


async def example_async_usage():
    """Example: Async usage for better performance."""
    print("\n" + "=" * 60)
    print("Example 4: Async Usage")
    print("=" * 60)
    
    client = EnhancedOpenAIClient()
    
    # Run multiple analyses in parallel
    tasks = [
        client.analyze_async(
            step_name="test",
            instructions="You are a helpful assistant.",
            user_content=f"What is {i} + {i}? Reply with just the number.",
            iteration=i,
        )
        for i in range(1, 4)
    ]
    
    responses = await asyncio.gather(*tasks)
    
    for i, response in enumerate(responses, 1):
        print(f"Response {i}: {response.content.strip()}")


def example_per_step_config():
    """Example: Different models/reasoning for different steps."""
    print("\n" + "=" * 60)
    print("Example 5: Per-Step Configuration")
    print("=" * 60)
    
    from src.config_loader import get_model_for_step, get_reasoning_for_step
    
    steps = ["anchor_detection", "agreement_extraction", "category_extraction", "web_search"]
    
    print("\nStep-specific configuration:")
    for step in steps:
        model = get_model_for_step(step)
        reasoning = get_reasoning_for_step(step)
        print(f"  {step}: model={model}, reasoning={reasoning}")


def example_debug_output():
    """Example: Show where debug files are saved."""
    print("\n" + "=" * 60)
    print("Example 6: Debug Output Location")
    print("=" * 60)
    
    config = get_config()
    
    if config.openai.debug_prompts.enabled:
        debug_dir = config.project_root / config.openai.debug_prompts.directory
        print(f"Debug prompts enabled!")
        print(f"Directory: {debug_dir}")
        print(f"Max files: {config.openai.debug_prompts.max_files}")
        
        # List existing debug files
        if debug_dir.exists():
            files = list(debug_dir.glob("*.txt"))
            print(f"Existing debug files: {len(files)}")
            for f in files[-5:]:  # Show last 5
                print(f"  - {f.name}")
    else:
        print("Debug prompts are disabled. Enable in config.yaml:")
        print("  debug_prompts:")
        print("    enabled: true")


def main():
    """Run all examples."""
    print("\n" + "=" * 60)
    print("ENHANCED EXTRACTION INFRASTRUCTURE EXAMPLES")
    print("=" * 60)
    
    # Load config first
    load_config()
    
    # Run examples
    example_per_step_config()
    example_prompt_loader()
    example_debug_output()
    
    # Uncomment these to run API calls (costs money!)
    # example_basic_usage()
    # example_structured_output()
    # asyncio.run(example_async_usage())
    
    print("\n" + "=" * 60)
    print("EXAMPLES COMPLETE")
    print("=" * 60)
    print("\nTo run the API examples, uncomment them in main().")
    print("Debug prompts will be saved to: outputs/debug_prompts/")


if __name__ == "__main__":
    main()
