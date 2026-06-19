"""Prompt-injection guard — lightweight pre-LLM filter.

Checks user input against known injection patterns *before* the message reaches
the LLM context window. This is defense-in-depth: even if an attacker gets
past this filter, the deterministic policy engine still makes the final
decision, so injection can change the LLM's *words* but not the refund verdict.

The patterns are conservative: false positives are acceptable (worst case, the
customer is asked to rephrase), but false negatives are dangerous.
"""

from __future__ import annotations

import re
from typing import Optional


# Canonical injection patterns (lowercase comparison).
# These cover: role-play overrides, system prompt leaks, delimiter attacks,
# "ignore previous instructions", and common jailbreak fragments.
_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+(instructions?|prompts?|rules?)", re.I),
    re.compile(r"ignore\s+(the\s+)?(above|below|your)\s+(instructions?|prompt|system)", re.I),
    re.compile(r"you\s+are\s+now\s+(a|an|the)\b", re.I),
    re.compile(r"new\s+instructions?\s*:", re.I),
    re.compile(r"system\s*prompt\s*:", re.I),
    re.compile(r"from\s+now\s+on\b.*?(respond|act|behave|pretend)", re.I),
    re.compile(r"<\|im_start\|>\s*system", re.I),
    re.compile(r"\[INST\].*?<<(?:SYS|SYSTEM)>>", re.I),
    re.compile(r"(?:jailbreak|dan\b|dev\s*mode)\b", re.I),
    re.compile(r"override\s+(the\s+)?policy", re.I),
    re.compile(r"disregard\s+(all\s+)?rules?", re.I),
    re.compile(r"approve\s+(this|the)\s*(refund|request)\s*(regardless|anyway)", re.I),
    re.compile(r"you\s*must\s*(not|never)\s*(deny|reject|block)\s*(the\s+)?refund", re.I),
    re.compile(r"pretend\s+(you\s+are|to\s+be)\b", re.I),
]


def check_injection(text: str) -> tuple[bool, str]:
    """
    Check a user message for prompt-injection patterns.

    Returns:
        (blocked: bool, matched_pattern: str)
        If blocked is True, the message should not reach the LLM.
    """
    lower = text.lower()
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(lower):
            return True, pattern.pattern
    return False, ""
