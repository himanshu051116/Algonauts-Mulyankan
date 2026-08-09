"""Ollama integration for extraction and reviewer-facing rationales.

The LLM is never the sole scoring authority. It is used only for:

1. Structured-field extraction.
2. Evidence summarisation.
3. Reviewer-facing suggestions.

All generated output is advisory and must not override deterministic rules,
validated proposal data, or a human reviewer's final decision.
"""

from __future__ import annotations

import json
import os
from typing import Any, TypeAlias

import httpx


JsonObject: TypeAlias = dict[str, Any]

OLLAMA_BASE_URL = os.environ.get(
    "OLLAMA_BASE_URL",
    "http://localhost:11434",
).rstrip("/")

DEFAULT_MODEL = os.environ.get(
    "OLLAMA_MODEL",
    "qwen3.5:9b",
)

OLLAMA_TIMEOUT_SECONDS = 120.0
MAX_EXTRACTION_CHARS = 12_000

EXTRACTION_SYSTEM_PROMPT = """
You are a structured field extractor for coal R&D proposal documents.

Extract the requested fields from the supplied proposal text and return one
valid JSON object.

Rules:
- Use null when a field cannot be found reliably.
- Do not invent values.
- Do not infer exact numeric values from vague language.
- Preserve uncertainty by returning null.
- Output only valid JSON.
- Do not include Markdown fences or explanatory text.

Fields:
- project_duration_months (number | null)
- trl_current (number | null)
- trl_target (number | null)
- total_budget (number | null)
- contingency_percentage (number | null)
- overhead_percentage (number | null)
- manpower_percentage (number | null)
- thrust_areas (string[])
- has_dgms_approval (boolean | null)
- has_industry_partner (boolean | null)
- has_milestones (boolean | null)
- has_risk_assessment (boolean | null)
""".strip()

SUMMARISATION_SYSTEM_PROMPT = """
You are a preliminary scrutiny assistant for Ministry of Coal R&D proposals.

Summarise the supplied evidence-based rule and scoring results into a concise
reviewer-facing assessment.

Requirements:
- Use only the evidence supplied in the prompt.
- Do not invent proposal facts.
- Clearly separate supported findings from missing information.
- Mention important eligibility blockers and exceptions.
- Treat scores as preliminary decision-support indicators.
- Do not present the assessment as a final approval or rejection.
- Keep the response below 200 words.
""".strip()


def _normalise_mapping(
    value: object,
    *,
    context: str,
) -> JsonObject:
    """Validate and normalise an externally supplied JSON mapping."""

    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a JSON object")

    return {
        str(key): item
        for key, item in value.items()
    }


def _remove_markdown_fence(text: str) -> str:
    """Remove an optional Markdown code fence from an LLM response."""

    cleaned = text.strip()

    if not cleaned.startswith("```"):
        return cleaned

    lines = cleaned.splitlines()

    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]

    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]

    return "\n".join(lines).strip()


async def _call_ollama(
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.1,
    max_tokens: int = 1024,
) -> str:
    """Call Ollama and return validated response text."""

    request_payload: JsonObject = {
        "model": model,
        "system": system_prompt,
        "prompt": user_prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(OLLAMA_TIMEOUT_SECONDS),
    ) as client:
        response = await client.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json=request_payload,
        )

    response.raise_for_status()

    raw_payload: object = response.json()

    payload = _normalise_mapping(
        raw_payload,
        context="Ollama response",
    )

    raw_response: object = payload.get("response")

    if not isinstance(raw_response, str):
        raise ValueError(
            "Ollama response is missing a string 'response' field"
        )

    response_text = raw_response.strip()

    if not response_text:
        raise ValueError("Ollama returned an empty response")

    return response_text


async def extract_fields_with_llm(
    text: str,
) -> JsonObject:
    """Extract advisory structured fields from proposal text."""

    truncated_text = text[:MAX_EXTRACTION_CHARS]

    response = await _call_ollama(
        EXTRACTION_SYSTEM_PROMPT,
        (
            "Extract the requested fields from this proposal text:\n\n"
            f"{truncated_text}"
        ),
        temperature=0.05,
    )

    cleaned = _remove_markdown_fence(response)

    if not cleaned:
        return {
            "_parse_error": "The LLM returned an empty response",
            "_raw": response,
            "llm_source": f"ollama/{DEFAULT_MODEL}",
        }

    try:
        parsed_value: object = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return {
            "_parse_error": cleaned[:500],
            "_raw": response,
            "_error_detail": str(exc),
            "llm_source": f"ollama/{DEFAULT_MODEL}",
        }

    try:
        parsed = _normalise_mapping(
            parsed_value,
            context="LLM extraction response",
        )
    except ValueError as exc:
        return {
            "_parse_error": str(exc),
            "_raw": response,
            "llm_source": f"ollama/{DEFAULT_MODEL}",
        }

    parsed["llm_source"] = f"ollama/{DEFAULT_MODEL}"
    parsed["advisory_only"] = True

    return parsed


async def generate_rationale(
    rule_results: list[JsonObject],
    scoring_summary: JsonObject,
    proposal_title: str,
) -> str:
    """Generate an advisory reviewer-facing assessment."""

    rules_summary_lines: list[str] = []

    for rule in rule_results[:10]:
        rule_id = str(rule.get("rule_id", "?"))
        result = str(rule.get("result", "?"))
        detail = str(rule.get("detail", ""))[:200]

        rules_summary_lines.append(
            f"- {rule_id}: {result} — {detail}"
        )

    rules_summary = "\n".join(rules_summary_lines)

    raw_categories: object = scoring_summary.get(
        "category_scores",
        [],
    )

    category_summary_lines: list[str] = []

    if isinstance(raw_categories, list):
        for raw_category in raw_categories:
            if not isinstance(raw_category, dict):
                continue

            category = str(
                raw_category.get("category", "?")
            )
            awarded = raw_category.get("awarded", 0)
            maximum = raw_category.get("maximum", 0)

            category_summary_lines.append(
                f"- {category}: {awarded}/{maximum}"
            )

    category_summary = "\n".join(
        category_summary_lines
    )

    total_score = scoring_summary.get(
        "total_score",
        0,
    )
    maximum_score = scoring_summary.get(
        "maximum_score",
        100,
    )
    information_sufficiency = scoring_summary.get(
        "information_sufficiency",
        0,
    )

    prompt = (
        f"Proposal: {proposal_title}\n\n"
        "Rule-evaluation results:\n"
        f"{rules_summary or '- No rule results supplied'}\n\n"
        "Category scores:\n"
        f"{category_summary or '- No category scores supplied'}\n\n"
        f"Total score: {total_score}/{maximum_score}\n"
        "Information sufficiency: "
        f"{information_sufficiency}\n\n"
        "Produce a concise preliminary assessment for a human reviewer."
    )

    return await _call_ollama(
        SUMMARISATION_SYSTEM_PROMPT,
        prompt,
        temperature=0.3,
    )