"""
PowerPoint Slide Prompt Loader with Validation.

Loads PPTX slide prompts, renders templates, validates output, and retries on failure.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from src.llm.client import OpenAIClient, LLMResponse


# Base path for prompt files
PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts" / "agent"

# Retry configuration
MAX_RETRIES = 3


@dataclass
class SlideContent:
    """Container for generated slide content."""
    success: bool
    content: Dict[str, str]
    errors: List[str]
    retries_used: int


@dataclass
class ValidationResult:
    """Result of content validation."""
    valid: bool
    errors: List[str]


def load_pptx_prompt(slide_name: str) -> Dict[str, Any]:
    """
    Load a PPTX slide prompt from YAML file.
    
    Args:
        slide_name: Name like 'pptx_slide_2', 'pptx_slide_3', 'pptx_slide_4'
        
    Returns:
        Dict containing prompt configuration
    """
    prompt_file = PROMPTS_DIR / f"{slide_name}.yaml"
    
    if not prompt_file.exists():
        raise FileNotFoundError(f"PPTX prompt file not found: {prompt_file}")
    
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
            if isinstance(value, list):
                str_value = "\n".join(f"- {v}" for v in value)
            elif value is None:
                str_value = "N/A"
            else:
                str_value = str(value)
            result = result.replace(placeholder, str_value)
    
    return result


def validate_output(
    output: str,
    validation_rules: Dict[str, Any],
    variables: Dict[str, Any]
) -> ValidationResult:
    """
    Validate LLM output against rules from YAML.
    
    Args:
        output: Raw LLM output string
        validation_rules: Validation rules from YAML prompt
        variables: Original variables (for must_not_contain checks)
        
    Returns:
        ValidationResult with valid flag and list of errors
    """
    errors = []
    
    # Check max_length
    if "max_length" in validation_rules:
        max_len = validation_rules["max_length"]
        if len(output) > max_len:
            errors.append(f"Output too long: {len(output)} chars (max {max_len})")
    
    # Check max_words
    if "max_words" in validation_rules:
        max_words = validation_rules["max_words"]
        word_count = len(output.split())
        if word_count > max_words:
            errors.append(f"Output too long: {word_count} words (max {max_words})")
    
    # Check must_not_contain (substitute variables)
    if "must_not_contain" in validation_rules:
        for pattern in validation_rules["must_not_contain"]:
            # Replace {{variable}} with actual value
            check_pattern = pattern
            for key, value in variables.items():
                check_pattern = check_pattern.replace("{{" + key + "}}", str(value or ""))
            
            if check_pattern and check_pattern.lower() in output.lower():
                errors.append(f"Output contains forbidden text: '{check_pattern}'")
    
    # Check must_contain_one_of
    if "must_contain_one_of" in validation_rules:
        patterns = validation_rules["must_contain_one_of"]
        found = any(p.lower() in output.lower() for p in patterns)
        if not found:
            errors.append(f"Output must contain one of: {patterns}")
    
    # Check format_pattern (regex)
    if "format_pattern" in validation_rules:
        pattern = validation_rules["format_pattern"]
        if not re.match(pattern, output.strip()):
            errors.append(f"Output doesn't match required format: {pattern}")
    
    return ValidationResult(valid=len(errors) == 0, errors=errors)


def validate_slide_3_output(
    parsed: Dict[str, str],
    validation_rules: Dict[str, Any],
    variables: Dict[str, Any]
) -> ValidationResult:
    """Validate slide 3 parsed output (multiple fields)."""
    errors = []
    
    # Validate client_description
    if "client_description" in validation_rules:
        rules = validation_rules["client_description"]
        desc = parsed.get("client_description", "")
        
        if "max_length" in rules and len(desc) > rules["max_length"]:
            errors.append(f"client_description too long: {len(desc)} chars (max {rules['max_length']})")
        
        if "must_not_contain" in rules:
            for pattern in rules["must_not_contain"]:
                check = pattern.replace("{{client_name}}", str(variables.get("client_name", "")))
                if check and check.lower() in desc.lower():
                    errors.append(f"client_description contains client name")
    
    # Validate challenge_text
    if "challenge_text" in validation_rules:
        rules = validation_rules["challenge_text"]
        text = parsed.get("challenge_text", "")
        
        if "max_words" in rules and len(text.split()) > rules["max_words"]:
            errors.append(f"challenge_text too long: {len(text.split())} words (max {rules['max_words']})")
        
        if "must_not_contain" in rules:
            for pattern in rules["must_not_contain"]:
                check = pattern.replace("{{client_name}}", str(variables.get("client_name", "")))
                if check and check.lower() in text.lower():
                    errors.append(f"challenge_text contains client name")
    
    # Validate approach_text
    if "approach_text" in validation_rules:
        rules = validation_rules["approach_text"]
        text = parsed.get("approach_text", "")
        
        if "max_words" in rules and len(text.split()) > rules["max_words"]:
            errors.append(f"approach_text too long: {len(text.split())} words (max {rules['max_words']})")
    
    return ValidationResult(valid=len(errors) == 0, errors=errors)


def validate_slide_4_output(
    parsed: Dict[str, Any],
    validation_rules: Dict[str, Any]
) -> ValidationResult:
    """Validate slide 4 parsed output (levers and differentiators)."""
    errors = []
    
    # Validate top_levers
    if "top_levers" in validation_rules:
        rules = validation_rules["top_levers"]
        levers = parsed.get("top_levers", [])
        
        # Support both exact count and min/max range
        if "count" in rules and len(levers) != rules["count"]:
            errors.append(f"top_levers count: {len(levers)} (expected {rules['count']})")
        if "min_count" in rules and len(levers) < rules["min_count"]:
            errors.append(f"top_levers count: {len(levers)} (minimum {rules['min_count']})")
        if "max_count" in rules and len(levers) > rules["max_count"]:
            errors.append(f"top_levers count: {len(levers)} (maximum {rules['max_count']})")
        
        if "max_words_per_item" in rules:
            max_words = rules["max_words_per_item"]
            for i, lever in enumerate(levers):
                if len(lever.split()) > max_words:
                    errors.append(f"top_levers[{i}] too long: {len(lever.split())} words (max {max_words})")
    
    # Validate differentiators
    if "differentiators" in validation_rules:
        rules = validation_rules["differentiators"]
        diffs = parsed.get("differentiators", [])
        
        if "count" in rules and len(diffs) != rules["count"]:
            errors.append(f"differentiators count: {len(diffs)} (expected {rules['count']})")
        
        if "max_words_per_item" in rules:
            max_words = rules["max_words_per_item"]
            for i, diff in enumerate(diffs):
                if len(diff.split()) > max_words:
                    errors.append(f"differentiators[{i}] too long: {len(diff.split())} words (max {max_words})")
        
        # Character limit validation
        if "max_chars_per_item" in rules:
            max_chars = rules["max_chars_per_item"]
            for i, diff in enumerate(diffs):
                if len(diff) > max_chars:
                    errors.append(f"differentiators[{i}] too long: {len(diff)} chars (max {max_chars})")
    
    return ValidationResult(valid=len(errors) == 0, errors=errors)


def parse_slide_2_output(output: str) -> str:
    """Parse slide 2 output (just the title text)."""
    return output.strip().strip('"').strip("'")


def parse_slide_3_output(output: str) -> Dict[str, str]:
    """
    Parse slide 3 output.
    
    Expected format:
    CLIENT_DESCRIPTION | [text]
    CHALLENGE_TEXT | [text]
    APPROACH_TEXT | [text]
    """
    result = {
        "client_description": "",
        "challenge_text": "",
        "approach_text": ""
    }
    
    for line in output.strip().split("\n"):
        if "|" not in line:
            continue
        
        key, _, value = line.partition("|")
        key = key.strip().lower().replace(" ", "_")
        value = value.strip()
        
        if key == "client_description":
            result["client_description"] = value
        elif key == "challenge_text":
            result["challenge_text"] = value
        elif key == "approach_text":
            result["approach_text"] = value
    
    return result


def parse_slide_4_output(output: str) -> Dict[str, List[str]]:
    """
    Parse slide 4 output.
    
    Expected format:
    TOP_LEVERS | [lever 1] || [lever 2] || ...
    DIFFERENTIATORS | [diff 1] || [diff 2]
    """
    result = {
        "top_levers": [],
        "differentiators": []
    }
    
    for line in output.strip().split("\n"):
        if "|" not in line:
            continue
        
        key, _, value = line.partition("|")
        key = key.strip().lower().replace(" ", "_")
        
        # Split by || for multiple items
        items = [item.strip() for item in value.split("||") if item.strip()]
        
        if key == "top_levers":
            result["top_levers"] = items
        elif key == "differentiators":
            result["differentiators"] = items
    
    return result


class PPTXPromptRunner:
    """
    Runner for PPTX slide prompts with validation and retry.
    """
    
    def __init__(self, llm_client: OpenAIClient):
        self.llm_client = llm_client
    
    async def generate_slide_2(
        self,
        client_name: str,
        industry: str,
        business_model: str = "",
        client_description: str = ""
    ) -> SlideContent:
        """
        Generate slide 2 title content.
        
        Returns:
            SlideContent with 'title' key
        """
        prompt_data = load_pptx_prompt("pptx_slide_2")
        variables = {
            "client_name": client_name,
            "industry": industry,
            "business_model": business_model,
            "client_description": client_description,
        }
        
        # Render prompts
        system_prompt = prompt_data["prompt"]["instructions"]
        user_prompt = render_template(prompt_data["prompt"]["user_template"], variables)
        
        validation_rules = prompt_data.get("validation", {})
        
        errors = []
        for attempt in range(MAX_RETRIES):
            try:
                response = self.llm_client.analyze(
                    system_prompt=system_prompt,
                    user_content=user_prompt,
                )
                
                if not response or not response.content:
                    errors.append(f"Attempt {attempt + 1}: Empty response")
                    continue
                
                # Parse output
                title = parse_slide_2_output(response.content)
                
                # Validate
                validation = validate_output(title, validation_rules, variables)
                
                # Additional check: detect redundant root words (e.g., "Retail Retailer")
                redundancy_error = None
                words = title.lower().split()
                for i in range(len(words) - 1):
                    w1, w2 = words[i], words[i + 1]
                    # Check if adjacent words share a root (one starts with the other, min 4 chars)
                    if len(w1) >= 4 and len(w2) >= 4:
                        if w1.startswith(w2[:4]) or w2.startswith(w1[:4]):
                            redundancy_error = f"Redundant words: '{words[i]}' and '{words[i+1]}' are too similar. Rephrase to avoid repetition."
                            break
                
                if validation.valid and not redundancy_error:
                    return SlideContent(
                        success=True,
                        content={"title": title},
                        errors=[],
                        retries_used=attempt
                    )
                else:
                    all_errors = [f"Attempt {attempt + 1}: {e}" for e in validation.errors]
                    if redundancy_error:
                        all_errors.append(f"Attempt {attempt + 1}: {redundancy_error}")
                    errors.extend(all_errors)
                    
                    # Add validation feedback to prompt for retry
                    feedback_errors = validation.errors + ([redundancy_error] if redundancy_error else [])
                    user_prompt += f"\n\nPREVIOUS ATTEMPT FAILED VALIDATION:\n" + "\n".join(feedback_errors)
                    user_prompt += "\n\nPlease fix these issues and try again."
                    
            except Exception as e:
                errors.append(f"Attempt {attempt + 1}: {str(e)}")
        
        # All retries failed
        return SlideContent(
            success=False,
            content={},
            errors=errors,
            retries_used=MAX_RETRIES
        )
    
    async def generate_slide_3(
        self,
        client_name: str,
        industry: str,
        business_model: str = "",
        revenue: str = "",
        employee_count: str = "",
        raw_challenge: str = "",
        raw_approach: str = "",
        additional_context: str = ""
    ) -> SlideContent:
        """
        Generate slide 3 content (client desc, challenge, approach).
        
        Returns:
            SlideContent with 'client_description', 'challenge_text', 'approach_text' keys
        """
        prompt_data = load_pptx_prompt("pptx_slide_3")
        
        # Format raw_approach if it's a list
        if isinstance(raw_approach, list):
            raw_approach = "\n".join(f"- {item}" for item in raw_approach)
        
        variables = {
            "client_name": client_name,
            "industry": industry,
            "business_model": business_model,
            "revenue": revenue,
            "employee_count": employee_count,
            "raw_challenge": raw_challenge,
            "raw_approach": raw_approach,
            "additional_context": additional_context,
        }
        
        # Render prompts
        system_prompt = prompt_data["prompt"]["instructions"]
        user_prompt = render_template(prompt_data["prompt"]["user_template"], variables)
        
        validation_rules = prompt_data.get("validation", {})
        
        errors = []
        for attempt in range(MAX_RETRIES):
            try:
                response = self.llm_client.analyze(
                    system_prompt=system_prompt,
                    user_content=user_prompt,
                )
                
                if not response or not response.content:
                    errors.append(f"Attempt {attempt + 1}: Empty response")
                    continue
                
                # Parse output
                parsed = parse_slide_3_output(response.content)
                
                # Check we got all required fields
                if not parsed["client_description"] or not parsed["challenge_text"]:
                    errors.append(f"Attempt {attempt + 1}: Missing required fields")
                    user_prompt += "\n\nPREVIOUS ATTEMPT: Output format was incorrect. Use exact format:\nCLIENT_DESCRIPTION | [text]\nCHALLENGE_TEXT | [text]\nAPPROACH_TEXT | [text]"
                    continue
                
                # Validate
                validation = validate_slide_3_output(parsed, validation_rules, variables)
                
                if validation.valid:
                    return SlideContent(
                        success=True,
                        content=parsed,
                        errors=[],
                        retries_used=attempt
                    )
                else:
                    errors.extend([f"Attempt {attempt + 1}: {e}" for e in validation.errors])
                    user_prompt += f"\n\nPREVIOUS ATTEMPT FAILED VALIDATION:\n" + "\n".join(validation.errors)
                    user_prompt += "\n\nPlease fix these issues and try again."
                    
            except Exception as e:
                errors.append(f"Attempt {attempt + 1}: {str(e)}")
        
        # All retries failed
        return SlideContent(
            success=False,
            content={},
            errors=errors,
            retries_used=MAX_RETRIES
        )
    
    async def generate_slide_4(
        self,
        industry: str,
        raw_top_levers: str = "",
        raw_differentiators: str = "",
        additional_context: str = ""
    ) -> SlideContent:
        """
        Generate slide 4 content (top levers, differentiators).
        
        Returns:
            SlideContent with 'top_levers' (list) and 'differentiators' (list) keys
        """
        prompt_data = load_pptx_prompt("pptx_slide_4")
        
        # Format lists if provided as lists
        if isinstance(raw_top_levers, list):
            raw_top_levers = "\n".join(f"- {item}" for item in raw_top_levers)
        if isinstance(raw_differentiators, list):
            raw_differentiators = "\n".join(f"- {item}" for item in raw_differentiators)
        
        variables = {
            "industry": industry,
            "raw_top_levers": raw_top_levers,
            "raw_differentiators": raw_differentiators,
            "additional_context": additional_context,
        }
        
        # Render prompts
        system_prompt = prompt_data["prompt"]["instructions"]
        user_prompt = render_template(prompt_data["prompt"]["user_template"], variables)
        
        validation_rules = prompt_data.get("validation", {})
        
        errors = []
        for attempt in range(MAX_RETRIES):
            try:
                response = self.llm_client.analyze(
                    system_prompt=system_prompt,
                    user_content=user_prompt,
                )
                
                if not response or not response.content:
                    errors.append(f"Attempt {attempt + 1}: Empty response")
                    continue
                
                # Parse output
                parsed = parse_slide_4_output(response.content)
                
                # Check we got required fields
                if not parsed["top_levers"]:
                    errors.append(f"Attempt {attempt + 1}: Missing top_levers")
                    user_prompt += "\n\nPREVIOUS ATTEMPT: Output format was incorrect. Use exact format:\nTOP_LEVERS | [lever 1] || [lever 2] || [lever 3] || [lever 4] || [lever 5]\nDIFFERENTIATORS | [diff 1] || [diff 2]"
                    continue
                
                # Validate
                validation = validate_slide_4_output(parsed, validation_rules)
                
                if validation.valid:
                    return SlideContent(
                        success=True,
                        content=parsed,
                        errors=[],
                        retries_used=attempt
                    )
                else:
                    errors.extend([f"Attempt {attempt + 1}: {e}" for e in validation.errors])
                    user_prompt += f"\n\nPREVIOUS ATTEMPT FAILED VALIDATION:\n" + "\n".join(validation.errors)
                    user_prompt += "\n\nPlease fix these issues and try again."
                    
            except Exception as e:
                errors.append(f"Attempt {attempt + 1}: {str(e)}")
        
        # All retries failed
        return SlideContent(
            success=False,
            content={},
            errors=errors,
            retries_used=MAX_RETRIES
        )
    
    async def generate_consistency_check(
        self,
        client_name: str,
        pe_sponsor: str = "",
        all_content_json: str = "",
    ) -> SlideContent:
        """
        Run consistency check on all slide content before PowerPoint generation.
        
        Validates numbers, terminology, and anonymization across all slides.
        Returns corrected content if issues found.
        
        Returns:
            SlideContent with 'issues' (list) and 'corrected' (dict) keys
        """
        prompt_data = load_pptx_prompt("pptx_consistency_check")
        
        variables = {
            "client_name": client_name,
            "pe_sponsor": pe_sponsor or "N/A",
            "all_content_json": all_content_json,
        }
        
        # Render prompts
        system_prompt = prompt_data["prompt"]["instructions"]
        user_prompt = render_template(prompt_data["prompt"]["user_template"], variables)
        
        errors = []
        for attempt in range(MAX_RETRIES):
            try:
                response = self.llm_client.analyze(
                    system_prompt=system_prompt,
                    user_content=user_prompt,
                )
                
                if not response or not response.content:
                    errors.append(f"Attempt {attempt + 1}: Empty response")
                    continue
                
                # Parse JSON from response
                parsed = self._extract_json(response.content)
                
                if parsed is None:
                    errors.append(f"Attempt {attempt + 1}: Could not parse JSON from response")
                    user_prompt += "\n\nPREVIOUS ATTEMPT: Response was not valid JSON. Return ONLY a JSON object with 'issues' and 'corrected' keys."
                    continue
                
                # Validate structure
                if "issues" not in parsed or "corrected" not in parsed:
                    errors.append(f"Attempt {attempt + 1}: Missing 'issues' or 'corrected' keys")
                    user_prompt += "\n\nPREVIOUS ATTEMPT: JSON must have both 'issues' and 'corrected' keys."
                    continue
                
                # Validate corrected has all required fields
                corrected = parsed.get("corrected", {})
                required_fields = ["title", "client_description", "challenge", "approach", "top_levers", "differentiators", "pe_description"]
                missing_fields = [f for f in required_fields if f not in corrected]
                if missing_fields:
                    errors.append(f"Attempt {attempt + 1}: Corrected content missing fields: {missing_fields}")
                    user_prompt += f"\n\nPREVIOUS ATTEMPT: 'corrected' object must contain ALL fields: {required_fields}"
                    continue
                
                # Validate anonymization in corrected content
                corrected_str = json.dumps(corrected).lower()
                
                anonymization_issues = []
                if client_name and len(client_name) > 2 and client_name.lower() in corrected_str:
                    anonymization_issues.append(f"Corrected content still contains client name '{client_name}'")
                if pe_sponsor and pe_sponsor != "N/A" and len(pe_sponsor) > 2 and pe_sponsor.lower() in corrected_str:
                    anonymization_issues.append(f"Corrected content still contains PE firm name '{pe_sponsor}'")
                
                if anonymization_issues:
                    errors.extend([f"Attempt {attempt + 1}: {e}" for e in anonymization_issues])
                    user_prompt += f"\n\nPREVIOUS ATTEMPT FAILED: " + "; ".join(anonymization_issues) + ". Remove ALL references to these names."
                    continue
                
                return SlideContent(
                    success=True,
                    content=parsed,
                    errors=[],
                    retries_used=attempt
                )
                
            except Exception as e:
                errors.append(f"Attempt {attempt + 1}: {str(e)}")
        
        # All retries failed
        return SlideContent(
            success=False,
            content={},
            errors=errors,
            retries_used=MAX_RETRIES
        )
    
    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract JSON from LLM response, handling markdown code blocks."""
        # Try direct parse first
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass
        
        # Try extracting from markdown code block
        json_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except json.JSONDecodeError:
                pass
        
        # Try finding JSON object in text by matching braces
        brace_start = text.find('{')
        if brace_start >= 0:
            depth = 0
            for i in range(brace_start, len(text)):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[brace_start:i + 1])
                        except json.JSONDecodeError:
                            break
        
        return None
    
    async def generate_pe_description(
        self,
        pe_sponsor: str,
        industry: str,
        web_search_results: str = ""
    ) -> SlideContent:
        """
        Generate anonymized PE firm description from web search results.
        
        Args:
            pe_sponsor: Actual PE firm name (not used in output)
            industry: Industry context
            web_search_results: Web search results about the PE firm
            
        Returns:
            SlideContent with 'pe_description' key
        """
        prompt_data = load_pptx_prompt("pptx_pe_description")
        
        variables = {
            "pe_sponsor": pe_sponsor,
            "industry": industry,
            "web_search_results": web_search_results or "No web search results available.",
        }
        
        # Render prompts
        system_prompt = prompt_data["prompt"]["instructions"]
        user_prompt = render_template(prompt_data["prompt"]["user_template"], variables)
        
        validation_rules = prompt_data.get("validation", {})
        
        errors = []
        for attempt in range(MAX_RETRIES):
            try:
                response = self.llm_client.analyze(
                    system_prompt=system_prompt,
                    user_content=user_prompt,
                )
                
                if not response or not response.content:
                    errors.append(f"Attempt {attempt + 1}: Empty response")
                    continue
                
                # Parse output - just clean up the text
                pe_description = response.content.strip().strip('"').strip("'")
                
                # Validate - check it doesn't contain the actual PE name
                if pe_sponsor.lower() in pe_description.lower():
                    errors.append(f"Attempt {attempt + 1}: Contains actual PE firm name")
                    user_prompt += f"\n\nPREVIOUS ATTEMPT FAILED: Output contained the actual firm name '{pe_sponsor}'. Do NOT use this name."
                    continue
                
                # Check length
                max_length = validation_rules.get("max_length", 60)
                if len(pe_description) > max_length:
                    errors.append(f"Attempt {attempt + 1}: Too long ({len(pe_description)} chars, max {max_length})")
                    user_prompt += f"\n\nPREVIOUS ATTEMPT FAILED: Output was {len(pe_description)} chars, max is {max_length}. Be more concise."
                    continue
                
                return SlideContent(
                    success=True,
                    content={"pe_description": pe_description},
                    errors=[],
                    retries_used=attempt
                )
                
            except Exception as e:
                errors.append(f"Attempt {attempt + 1}: {str(e)}")
        
        # All retries failed
        return SlideContent(
            success=False,
            content={},
            errors=errors,
            retries_used=MAX_RETRIES
        )
