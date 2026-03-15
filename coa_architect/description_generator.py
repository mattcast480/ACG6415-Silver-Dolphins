"""
description_generator.py — Converts plain-English account descriptions into
short, professional GL account names.

Usage:
    from .description_generator import generate_description

    generated, reasoning = generate_description(
        plain_english="rent income from cabins the company rents out",
        proposal=proposal,
        hierarchy=hierarchy,
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
    )

When an ANTHROPIC_API_KEY is provided the function calls the Claude API
(claude-haiku-4-5-20251001).  If the key is absent, or if the API call
fails for any reason, it falls back silently to a pure Python rule-based
generator so the session never interrupts.
"""

import re
from typing import Optional

from .models import Account, AccountHierarchy, NewAccountProposal


# ------------------------------------------------------------------
# Public entry point
# ------------------------------------------------------------------

def generate_description(
    plain_english: str,
    proposal: NewAccountProposal,
    hierarchy: AccountHierarchy,
    api_key: Optional[str],
) -> tuple:
    """
    Returns (generated_description, reasoning_str).

    Tries the Claude API when api_key is provided; silently falls back
    to the rule-based generator on any error.
    """
    # Try Claude API first when a key is available
    if api_key:
        try:
            generated = _generate_via_claude(plain_english, proposal, hierarchy, api_key)
            reasoning = f"Claude (claude-haiku-4-5) from: \"{plain_english}\""
            return generated, reasoning
        except Exception:
            # Any failure (network, rate limit, bad key) — fall through silently
            pass

    # Rule-based fallback — always works offline, no dependencies
    generated = _generate_rule_based(plain_english, proposal, hierarchy)
    reasoning = f"Rule-based from: \"{plain_english}\""
    return generated, reasoning


# ------------------------------------------------------------------
# Claude API path
# ------------------------------------------------------------------

def _generate_via_claude(
    plain_english: str,
    proposal: NewAccountProposal,
    hierarchy: AccountHierarchy,
    api_key: str,
) -> str:
    """
    Calls claude-haiku-4-5-20251001 to generate a short professional title.

    The anthropic import is deferred into this function so that import
    errors (package not installed) are isolated and caught by the caller.
    """
    import anthropic  # Deferred — only needed when API key is present

    prompt = _build_claude_prompt(plain_english, proposal, hierarchy)

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=50,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


def _build_claude_prompt(
    plain_english: str,
    proposal: NewAccountProposal,
    hierarchy: AccountHierarchy,
) -> str:
    """
    Builds a compact prompt that gives Claude enough context to produce a
    naming-convention-consistent account description in 2–5 words.
    """
    lines = []

    # The user's raw input
    lines.append(f"User description: {plain_english}")

    # Parent account context
    parent = proposal.suggested_parent
    if parent:
        lines.append(f"Parent account: {parent.account_number} — {parent.account_description}")

    # Walk up to the L1 section ancestor for broader context
    l1 = _find_l1_ancestor(parent) if parent else None
    if l1:
        lines.append(f"Section: {l1.account_description}")

    # BU type label
    bu_type_label = {
        "BS": "Balance Sheet", "IS": "Income Statement"
    }.get(proposal.bu_type or "", proposal.bu_type or "")
    if bu_type_label:
        lines.append(f"Statement type: {bu_type_label}")

    # Sibling naming examples — the most concrete source of naming convention
    siblings = _get_sibling_descriptions(proposal, max_count=5)
    if siblings:
        lines.append("Sibling account names: " + ", ".join(siblings))

    # FERC code description (if one was suggested)
    ferc_code = proposal.ferc_code
    if ferc_code and hierarchy.reference_data.ferc_codes:
        ferc_desc = hierarchy.reference_data.ferc_codes.get(str(ferc_code), "")
        if ferc_desc:
            lines.append(f"Suggested FERC code description: {ferc_desc}")

    # Instruction
    lines.append(
        "\nGenerate a 2–5 word title-case account description following the "
        "sibling naming convention above. "
        "Respond with ONLY the description text — no punctuation, no explanation."
    )

    return "\n".join(lines)


# ------------------------------------------------------------------
# Rule-based fallback
# ------------------------------------------------------------------

# Noise phrases to strip from the start of plain-English input before tokenizing.
# Listed longest-first so that multi-word phrases are matched before substrings.
_NOISE_PHRASES = [
    "i want an account for",
    "i want a new account for",
    "i want an account that is used for",
    "a new account for",
    "account for",
    "an account for",
    "that is used for",
    "this is for",
    "i want",
    "a new account",
    "an account",
]

# Stop words — same set used in placer.py (copied here to avoid coupling)
_STOP_WORDS = {
    "and", "or", "the", "for", "with", "from", "of", "to",
    "a", "an", "in", "on", "at", "by", "is", "are", "be",
    "not", "as", "up", "was", "were",
}


def _generate_rule_based(
    plain_english: str,
    proposal: NewAccountProposal,
    hierarchy: AccountHierarchy,
) -> str:
    """
    Pure Python fallback description generator.

    Algorithm:
    1. Strip common noise phrases from the start of the input.
    2. Tokenize the remaining text (alpha words, no stop words).
    3. Keep the first 3–4 meaningful tokens in original order.
    4. Detect separator style from siblings; apply if input has a clear qualifier.
    5. Title-case the result.
    6. If fewer than 2 tokens survive, use the first 4 words of the original.
    """
    # Step 1 — remove noise phrases
    cleaned = plain_english.strip().lower()
    for phrase in _NOISE_PHRASES:
        if cleaned.startswith(phrase):
            cleaned = cleaned[len(phrase):].strip()
            break  # Only remove one prefix

    # Step 2 — find meaningful tokens in their original order
    all_words = re.findall(r"[a-zA-Z]{2,}", cleaned)
    meaningful = [w for w in all_words if w.lower() not in _STOP_WORDS]

    if len(meaningful) < 2:
        # Step 6 fallback — take first 4 words of the original input as-is
        fallback_words = re.findall(r"\S+", plain_english)[:4]
        return " ".join(fallback_words).title()

    # Step 3 — keep first 3–4 tokens
    kept = meaningful[:4]

    # Step 4 — detect separator style from siblings
    siblings = _get_sibling_descriptions(proposal, max_count=5)
    use_dash_separator = _majority_use_dash_separator(siblings)

    # Only apply separator if we have a clear main term and at least one qualifier
    if use_dash_separator and len(kept) >= 2:
        # Treat the first token as the main term, the rest as qualifier
        main_term = kept[0].title()
        qualifier = " ".join(w.title() for w in kept[1:])
        return f"{main_term} \u2014 {qualifier}"

    # Step 5 — simple title-cased join
    return " ".join(w.title() for w in kept)


def _majority_use_dash_separator(sibling_descriptions: list) -> bool:
    """
    Returns True when the majority of sibling account descriptions
    contain the em-dash separator pattern ' — '.
    """
    if not sibling_descriptions:
        return False
    count_with_dash = sum(1 for d in sibling_descriptions if " \u2014 " in d)
    return count_with_dash > len(sibling_descriptions) / 2


# ------------------------------------------------------------------
# Shared helpers
# ------------------------------------------------------------------

def _get_sibling_descriptions(
    proposal: NewAccountProposal, max_count: int = 5
) -> list:
    """
    Returns up to max_count account descriptions from the children of
    the suggested parent account.
    """
    parent = proposal.suggested_parent
    if parent is None or not parent.children:
        return []
    # Filter out children with no description; return up to max_count
    descs = [
        c.account_description
        for c in parent.children
        if c.account_description
    ]
    return descs[:max_count]


def _find_l1_ancestor(account: Optional[Account]) -> Optional[Account]:
    """
    Walks the parent chain upward and returns the first account whose
    line_of_detail == 1 (the L1 section header).

    Returns None if no L1 ancestor exists (e.g., account is already L1).
    """
    node = account
    while node is not None:
        if node.line_of_detail == 1:
            return node
        node = node.parent
    return None
