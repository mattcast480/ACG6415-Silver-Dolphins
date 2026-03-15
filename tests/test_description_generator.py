"""
test_description_generator.py — Unit tests for description_generator.py.

Tests do NOT require a live API key.  Claude API calls are mocked where needed.

Covers:
  - Rule-based generator produces a non-empty string
  - Rule-based output is title-cased
  - Very short / stop-word-only input does not crash
  - generate_description() uses rule-based path when api_key=None
  - generate_description() falls back to rule-based when API raises an exception
  - generate_description() returns Claude's result when API succeeds (mocked)

Run with: pytest tests/test_description_generator.py -v
"""

from unittest.mock import MagicMock, patch

import pytest

from coa_architect.models import (
    Account,
    AccountHierarchy,
    AccountRange,
    NewAccountProposal,
    ReferenceData,
)
from coa_architect.description_generator import (
    _generate_rule_based,
    generate_description,
)


# ---------------------------------------------------------------------------
# Fixtures — minimal objects required by the generator
# ---------------------------------------------------------------------------

def _make_account(num, desc, lod, bu_type="IS"):
    """Create a minimal Account for testing."""
    return Account(
        account_id=num,
        company="10",
        business_unit="10",
        bu_type=bu_type,
        account_number=num,
        account_description=desc,
        posting_edit="",
        line_of_detail=lod,
        ferc_code="",
        asset_life=None,
        book_tax_difference=None,
        cash_flow_category=None,
    )


def _make_hierarchy():
    """Build a minimal AccountHierarchy with a few accounts."""
    ref = ReferenceData(
        ferc_codes={},
        asset_life_codes={},
        cash_flow_codes={},
        posting_edit_codes={},
        book_tax_codes={},
        companies={"10": "Company A"},
        business_units={"10": "BU A"},
    )
    l1 = _make_account(400000, "Revenue", 1)
    parent = _make_account(401000, "Operating Revenue", 3)
    child1 = _make_account(401010, "Service Revenue", 5)
    child2 = _make_account(401020, "Product Revenue", 5)

    # Wire up relationships
    parent.parent = l1
    child1.parent = parent
    child2.parent = parent
    parent.children = [child1, child2]
    l1.children = [parent]

    accounts = [l1, parent, child1, child2]
    accounts_by_number = {a.account_number: a for a in accounts}
    accounts_by_number_and_bu = {(a.account_number, a.business_unit) for a in accounts}

    return AccountHierarchy(
        accounts=accounts,
        reference_data=ref,
        ranges=[],
        accounts_by_number=accounts_by_number,
        accounts_by_number_and_bu=accounts_by_number_and_bu,
        source_file_path="fake_path.xlsx",
        column_mapping={},
        max_account_id=4,
    )


def _make_proposal(parent_account=None):
    """Create a minimal NewAccountProposal with an optional parent."""
    p = NewAccountProposal()
    p.suggested_parent = parent_account
    p.bu_type = "IS"
    return p


# ---------------------------------------------------------------------------
# Tests — rule-based generator
# ---------------------------------------------------------------------------

def test_rule_based_returns_nonempty_string():
    """Input with clear keywords should produce a non-empty result."""
    hierarchy = _make_hierarchy()
    parent = hierarchy.accounts_by_number[401000]
    proposal = _make_proposal(parent_account=parent)

    result = _generate_rule_based(
        "rent income from cabins the company rents out",
        proposal,
        hierarchy,
    )

    assert isinstance(result, str)
    assert len(result.strip()) > 0


def test_rule_based_title_cases_output():
    """Rule-based output should be in title case (each word capitalized)."""
    hierarchy = _make_hierarchy()
    proposal = _make_proposal()

    result = _generate_rule_based("maintenance costs for vehicles", proposal, hierarchy)

    # Every word should start with an uppercase letter (title case)
    words = result.split()
    assert all(w[0].isupper() for w in words if w), (
        f"Expected title case but got: {result!r}"
    )


def test_rule_based_fallback_on_minimal_input():
    """A very short or stop-word-heavy input should not raise an exception."""
    hierarchy = _make_hierarchy()
    proposal = _make_proposal()

    # These inputs have almost no meaningful tokens
    for text in ["a", "an the", "  ", "or and"]:
        result = _generate_rule_based(text, proposal, hierarchy)
        # Should return something (may fall back to original words)
        assert isinstance(result, str)


def test_rule_based_strips_noise_phrases():
    """Common noise phrases at the start should be removed before titling."""
    hierarchy = _make_hierarchy()
    proposal = _make_proposal()

    # "account for" is a noise phrase; the meaningful word is "depreciation"
    result = _generate_rule_based("account for depreciation expense", proposal, hierarchy)

    # The result should not start with the word "account" since it was stripped
    assert not result.lower().startswith("account for"), (
        f"Noise phrase not stripped; got: {result!r}"
    )


# ---------------------------------------------------------------------------
# Tests — generate_description() routing
# ---------------------------------------------------------------------------

def test_generate_uses_rule_based_when_no_api_key():
    """With api_key=None the function should use the rule-based path and not raise."""
    hierarchy = _make_hierarchy()
    proposal = _make_proposal()

    result, reasoning = generate_description(
        "rental income from cabin properties",
        proposal,
        hierarchy,
        api_key=None,
    )

    assert isinstance(result, str)
    assert len(result.strip()) > 0
    # Reasoning should indicate rule-based was used
    assert "rule-based" in reasoning.lower() or "Rule-based" in reasoning


def test_generate_falls_back_to_rule_based_on_api_failure():
    """
    When the anthropic client raises any exception the function should
    silently fall back to rule-based and still return a valid string.
    """
    hierarchy = _make_hierarchy()
    proposal = _make_proposal()

    # Patch anthropic.Anthropic so its constructor raises an exception
    with patch.dict("sys.modules", {"anthropic": MagicMock(
        Anthropic=MagicMock(side_effect=Exception("simulated network error"))
    )}):
        result, reasoning = generate_description(
            "utility costs for the main office building",
            proposal,
            hierarchy,
            api_key="fake-key-for-testing",
        )

    assert isinstance(result, str)
    assert len(result.strip()) > 0
    # Must have fallen back to rule-based
    assert "rule-based" in reasoning.lower() or "Rule-based" in reasoning


def test_generate_via_claude_called_when_api_key_present():
    """
    When an API key is present and the client succeeds, generate_description()
    should return the text from the Claude response.
    """
    hierarchy = _make_hierarchy()
    proposal = _make_proposal()

    # Build a mock response that looks like an anthropic messages response
    mock_response_content = MagicMock()
    mock_response_content.text = "Rental Income — Cabin"
    mock_message = MagicMock()
    mock_message.content = [mock_response_content]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message

    mock_anthropic_module = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_client

    with patch.dict("sys.modules", {"anthropic": mock_anthropic_module}):
        result, reasoning = generate_description(
            "rent income from cabins the company rents out",
            proposal,
            hierarchy,
            api_key="test-api-key",
        )

    assert result == "Rental Income — Cabin"
    # Reasoning should mention Claude
    assert "claude" in reasoning.lower() or "Claude" in reasoning
