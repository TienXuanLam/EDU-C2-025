"""AgentCore Platform v1.0"""

# Thin adapter over BaseLLM.complete() (shared.services.llm.base_llm) for the
# single LLM-calling node in this agent (ReportDraftNode). The real interface
# takes a message list and returns the canonical {"content": str,
# "tool_calls": list, "model": str, ...} dict — not the simplified
# complete(prompt: str) -> str shown in some sdk/ how-to examples.

from __future__ import annotations

from typing import Any

DEFAULT_SYSTEM_PROMPT = (
    "You are drafting a compliance training completion gap report for HR/legal "
    "officers at a Japanese company. Use only the aggregated data provided — "
    "never invent completion rates, business unit names, or severity "
    "classifications not present in the input. Do not include any individual "
    "employee names, IDs, or other personally identifiable information. "
    "Respond concisely in the format requested."
)


def complete_text(llm: Any, prompt: str, system_prompt: str | None = None) -> str:
    """Send a prompt (with an optional system instruction) and return the text content.

    system_prompt defaults to DEFAULT_SYSTEM_PROMPT — pass "" explicitly to
    omit the system turn entirely.
    """
    system = DEFAULT_SYSTEM_PROMPT if system_prompt is None else system_prompt
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    response = llm.complete(messages)
    if isinstance(response, dict):
        content = response.get("content")
        return content if isinstance(content, str) else ""
    return str(response)
