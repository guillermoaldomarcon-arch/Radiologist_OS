"""
claude_client.py

Provides a single function, call_claude(prompt) -> str, that the
Parser Engine and Quality Engine can use as their `call_claude`
dependency (see parser_engine.py's AI fallback and quality_engine.py's
Layer 2).

Design principle (per project philosophy):
This module is intentionally the ONLY place in the codebase that
knows how to talk to the Anthropic API. Every other engine receives
call_claude as an injected function — they have no idea whether it's
this real implementation or a test fake. This keeps the engines
testable without API access and keeps API/auth concerns out of the
clinical logic entirely.

Portability requirement (per Guille): must work from any terminal
with internet access and Python installed — no dependency on
Railway, Supabase, GuardIA's backend, or any other specific
infrastructure. The only requirement is the ANTHROPIC_API_KEY
environment variable being set wherever this runs.

Setup:
    pip install anthropic --break-system-packages
    export ANTHROPIC_API_KEY="sk-ant-..."   (Linux/Mac)
    set ANTHROPIC_API_KEY=sk-ant-...        (Windows cmd)

Usage from another engine:
    from claude_client import call_claude
    findings = parse(dictation_text, call_claude=call_claude, organ_hints=...)
"""

import os
from typing import Optional

try:
    import anthropic
except ImportError:
    anthropic = None


_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 1000


class ClaudeClientError(Exception):
    """
    Raised when the Claude API cannot be reached or returns an
    unusable response. Callers (Parser/Quality Engine fallbacks)
    should let this propagate rather than silently treating a failed
    call as "no finding" / "supported" — a failed API call is not
    the same as a clear negative result, and conflating the two would
    hide real errors as if they were clinical conclusions.
    """
    pass


_client: Optional["anthropic.Anthropic"] = None


def _get_client() -> "anthropic.Anthropic":
    global _client

    if anthropic is None:
        raise ClaudeClientError(
            "The 'anthropic' package is not installed. "
            "Run: pip install anthropic --break-system-packages"
        )

    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ClaudeClientError(
                "ANTHROPIC_API_KEY environment variable is not set. "
                "Set it before running anything that needs the AI "
                "fallback (export ANTHROPIC_API_KEY=sk-ant-... on "
                "Linux/Mac, or set ANTHROPIC_API_KEY=sk-ant-... on "
                "Windows)."
            )
        _client = anthropic.Anthropic(api_key=api_key)

    return _client


def call_claude(prompt: str) -> str:
    """
    Sends a single user-turn prompt to Claude and returns the text of
    the response. This is the function injected as `call_claude` into
    parser_engine.parse() and quality_engine.apply_quality_check().

    Raises ClaudeClientError on any failure (missing API key, missing
    package, network error, empty response) — callers should not
    catch this and silently continue as if nothing was extracted;
    that decision belongs to whoever orchestrates the pipeline, with
    full visibility that the AI layer failed.
    """
    client = _get_client()

    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        raise ClaudeClientError(f"Anthropic API call failed: {e}")

    text_blocks = [
        block.text for block in response.content if block.type == "text"
    ]

    if not text_blocks:
        raise ClaudeClientError(
            "Anthropic API returned a response with no text content."
        )

    return "".join(text_blocks)
