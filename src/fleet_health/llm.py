from __future__ import annotations

import json

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from fleet_health.config import settings


def is_llm_enabled(*, skip_llm: bool = False) -> bool:
    """True when Claude calls should be attempted."""
    if skip_llm or settings.skip_llm:
        return False
    return bool(settings.anthropic_api_key.strip())


def get_llm() -> ChatAnthropic:
    if not is_llm_enabled():
        raise ValueError(
            "LLM is disabled or ANTHROPIC_API_KEY is not set. "
            "Set ANTHROPIC_API_KEY in .env or use SKIP_LLM=true for rule-based-only runs."
        )
    return ChatAnthropic(
        model=settings.llm_model,
        api_key=settings.anthropic_api_key,
        temperature=0.2,
        max_tokens=2048,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )


def claude_json(system: str, user: str) -> dict:
    """Ask Claude for a JSON object response."""
    if not is_llm_enabled():
        raise ValueError("LLM disabled")
    llm = get_llm()
    response = llm.invoke(
        [
            SystemMessage(
                content=system
                + "\nRespond with valid JSON only, no markdown fences."
            ),
            HumanMessage(content=user),
        ]
    )
    text = response.content
    if isinstance(text, list):
        text = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in text
        )
    text = str(text).strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return json.loads(text)
