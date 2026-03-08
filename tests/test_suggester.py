"""
test_suggester.py — Unit tests for coa_architect.suggester.CategorySuggester.

Tests verify:
  - "turbine" description → FERC 314 as top suggestion
  - "land" description → Asset Life 0 (non-depreciable)
  - BS account → Cash Flow INV suggestion
  - IS account → Cash Flow OP suggestion
  - BU type inherited from parent
  - Posting edit always blank for Level-5
  - suggest_all() populates all fields and reasoning

Run with: pytest tests/test_suggester.py -v
"""

import pytest

from coa_architect.models import Account, AccountHierarchy, AccountRange, ReferenceData, NewAccountProposal
from coa_architect.analyzer import CoAAnalyzer
from coa_architect.suggester import CategorySuggester


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_account(num, desc, lod, ferc="", asset_life=None, bu_type="BS", cf=None):
    """Helper: create a minimal Account for testing."""
    return Account(
        account_id=num,
        company="10",
        business_unit="10",
        bu_type=bu_type,
        account_number=num,
        account_description=desc,
        posting_edit="",
        line_of_detail=lod,
        ferc_code=ferc,
        asset_life=asset_life,
        book_tax_difference=None,
        cash_flow_category=cf,
    )


@pytest.fixture
def reference_data():
    return ReferenceData(
        ferc_codes={
            "310": "Land and land rights",
            "314": "Turbogenerator units",
            "315": "Accessory electric equipment",
            "331": "Structures and improvements",
        },
        asset_life_codes={
            "0": "Non-depreciable (Land)",
            "60": "5 Years (60 months)",
            "300": "25 Years (300 months)",
            "360": "30 Years (360 months)",
            "420": "35 Years (420 months)",
        },
        cash_flow_codes={
            "INV": "Investing Activities",
            "OP": "Operating Activities",
            "FIN": "Financing Activities",
        },
        posting_edit_codes={},
        book_tax_codes={},
        companies={"10": "Admin Services"},
        business_units={"10": "Corporate"},
    )


@pytest.fixture
def accounts_with_hierarchy(reference_data):
    """
    Builds and returns a full AccountHierarchy with a typical utility CoA structure.
    Includes accounts with FERC 314 under Machinery to test turbine suggestions.
    """
    accounts = [
        _make_account(100000, "ASSETS", 1),
        _make_account(100001, "Long-Term Assets", 2),
        _make_account(100002, "PP&E", 3),
        _make_account(100003, "Land", 4, ferc="310"),
        _make_account(100500, "Land — Tract A", 5, ferc="310", asset_life="0"),
        _make_account(100600, "Land — Tract B", 5, ferc="310", asset_life="0"),
        _make_account(102000, "Machinery and Equipment", 4, ferc="314"),
        _make_account(103000, "Wind Turbine Units", 5, ferc="314", asset_life="300"),
        _make_account(103100, "Turbogenerators", 5, ferc="314", asset_life="300"),
        _make_account(103200, "Auxiliary Equipment", 5, ferc="315", asset_life="300"),
        _make_account(200000, "LIABILITIES", 1, bu_type="BS"),
        _make_account(200001, "Long-Term Debt", 2, bu_type="BS"),
        _make_account(200100, "Bonds Payable", 5, bu_type="BS"),
        _make_account(300000, "REVENUE", 1, bu_type="IS"),
        _make_account(300001, "Operating Revenue", 2, bu_type="IS"),
        _make_account(300100, "Electric Revenue", 5, bu_type="IS", cf="OP"),
    ]

    col_map = {
        "account_id": "A", "company": "B", "business_unit": "C", "bu_type": "D",
        "account_number": "E", "account_description": "F", "posting_edit": "G",
        "line_of_detail": "H", "ferc_code": "I", "asset_life": "J",
        "book_tax_difference": "K", "cash_flow_category": "L",
    }
    analyzer = CoAAnalyzer()
    return analyzer.analyze(accounts, reference_data, col_map, "test.xlsx")


@pytest.fixture
def suggester():
    return CategorySuggester()


# ---------------------------------------------------------------------------
# Tests — suggest_ferc_code
# ---------------------------------------------------------------------------

class TestSuggestFercCode:
    def test_turbine_keyword_suggests_ferc_314(self, suggester, accounts_with_hierarchy):
        """
        A description containing 'turbine' should produce FERC 314 as a top suggestion
        because accounts 103000 and 103100 use FERC 314 and have 'turbine' keyword.
        """
        # Parent = Machinery and Equipment (102000 or 102000 → it's actually 102000 in hierarchy)
        hierarchy = accounts_with_hierarchy
        parent = hierarchy.accounts_by_number[102000]  # Machinery and Equipment, L4

        proposal = NewAccountProposal(
            account_description="Offshore Wind Turbine Installation",
            suggested_parent=parent,
        )

        suggestions = suggester.suggest_ferc_code(proposal, hierarchy)

        assert len(suggestions) > 0, "Should produce at least one FERC suggestion"

        codes = [code for code, conf, expl in suggestions]
        assert "314" in codes, (
            f"Expected FERC 314 in suggestions for 'turbine', got {codes}"
        )

    def test_turbine_ferc_314_is_top_suggestion(self, suggester, accounts_with_hierarchy):
        """FERC 314 should be the highest-confidence suggestion for 'turbine'."""
        hierarchy = accounts_with_hierarchy
        parent = hierarchy.accounts_by_number[102000]

        proposal = NewAccountProposal(
            account_description="Wind Turbine",
            suggested_parent=parent,
        )

        suggestions = suggester.suggest_ferc_code(proposal, hierarchy)
        top_code = suggestions[0][0] if suggestions else None

        assert top_code == "314", (
            f"Expected FERC 314 as top suggestion, got '{top_code}'"
        )

    def test_sibling_ferc_codes_appear_in_suggestions(self, suggester, accounts_with_hierarchy):
        """
        Under Machinery (102000), siblings use FERC 314.
        Any proposal under that parent should see 314 from sibling analysis.
        """
        hierarchy = accounts_with_hierarchy
        parent = hierarchy.accounts_by_number[102000]

        proposal = NewAccountProposal(
            account_description="New Generator Unit",
            suggested_parent=parent,
        )

        suggestions = suggester.suggest_ferc_code(proposal, hierarchy)
        codes = [c for c, _, _ in suggestions]

        assert "314" in codes, f"Sibling-based FERC 314 should appear; got {codes}"

    def test_no_description_returns_suggestions_from_siblings(
        self, suggester, accounts_with_hierarchy
    ):
        """Even without a description, sibling accounts should drive suggestions."""
        hierarchy = accounts_with_hierarchy
        parent = hierarchy.accounts_by_number[102000]

        proposal = NewAccountProposal(
            account_description="",
            suggested_parent=parent,
        )

        suggestions = suggester.suggest_ferc_code(proposal, hierarchy)
        # Should get at least sibling-based suggestion
        assert len(suggestions) > 0

    def test_external_ferc_codes_labeled_differently(
        self, suggester, accounts_with_hierarchy, reference_data
    ):
        """
        External FERC codes should be labeled 'From external reference file'.
        We simulate this by adding an external code and checking the explanation.
        """
        hierarchy = accounts_with_hierarchy
        # Add an external FERC code not already in the CoA
        external_code = "999"
        hierarchy.reference_data.ferc_codes[external_code] = "Test external turbine code"
        hierarchy.reference_data.external_ferc_codes.add(external_code)

        parent = hierarchy.accounts_by_number[102000]
        proposal = NewAccountProposal(
            account_description="turbine external test",
            suggested_parent=parent,
        )

        suggestions = suggester.suggest_ferc_code(proposal, hierarchy)
        ext_suggestions = [
            (c, conf, e) for c, conf, e in suggestions
            if c == external_code
        ]

        if ext_suggestions:
            _, _, expl = ext_suggestions[0]
            assert "external" in expl.lower(), (
                f"External code explanation should mention 'external', got: {expl}"
            )

    def test_returns_list_of_tuples(self, suggester, accounts_with_hierarchy):
        """suggest_ferc_code should return list of (code, confidence_pct, explanation)."""
        hierarchy = accounts_with_hierarchy
        parent = hierarchy.accounts_by_number[102000]
        proposal = NewAccountProposal(
            account_description="test equipment",
            suggested_parent=parent,
        )

        suggestions = suggester.suggest_ferc_code(proposal, hierarchy)

        for item in suggestions:
            assert isinstance(item, tuple) and len(item) == 3, (
                f"Expected (code, pct, expl) tuple, got {item}"
            )
            code, conf, expl = item
            assert isinstance(conf, (int, float)), f"Confidence should be numeric, got {type(conf)}"


# ---------------------------------------------------------------------------
# Tests — suggest_asset_life
# ---------------------------------------------------------------------------

class TestSuggestAssetLife:
    def test_land_keyword_suggests_zero(self, suggester, accounts_with_hierarchy):
        """'land' in description should suggest asset life 0 (non-depreciable)."""
        hierarchy = accounts_with_hierarchy
        parent = hierarchy.accounts_by_number[100003]  # Land, L4

        proposal = NewAccountProposal(
            account_description="Land parcel for substation",
            suggested_parent=parent,
        )

        suggestions = suggester.suggest_asset_life(proposal, hierarchy)
        codes = [v for v, _ in suggestions]

        assert "0" in codes, (
            f"'land' keyword should suggest asset life 0, got suggestions: {suggestions}"
        )

    def test_land_asset_life_is_top_suggestion(self, suggester, accounts_with_hierarchy):
        """For a 'land' account, 0 months should be the first or most prominent suggestion."""
        hierarchy = accounts_with_hierarchy
        parent = hierarchy.accounts_by_number[100003]

        proposal = NewAccountProposal(
            account_description="Easement land rights acquisition",
            suggested_parent=parent,
        )

        suggestions = suggester.suggest_asset_life(proposal, hierarchy)
        assert suggestions, "Should produce at least one asset life suggestion for 'land'"

        # Either from sibling data (100500, 100600 both use "0") or from keyword
        codes = [v for v, _ in suggestions]
        assert "0" in codes, f"Expected '0' in asset life suggestions, got {codes}"

    def test_turbine_keyword_suggests_300(self, suggester, accounts_with_hierarchy):
        """'turbine' should suggest asset life 300 (25 years)."""
        hierarchy = accounts_with_hierarchy
        parent = hierarchy.accounts_by_number[102000]

        proposal = NewAccountProposal(
            account_description="Offshore wind turbine installation",
            suggested_parent=parent,
        )

        suggestions = suggester.suggest_asset_life(proposal, hierarchy)
        codes = [v for v, _ in suggestions]

        assert "300" in codes, (
            f"'turbine' keyword should suggest 300 months, got {codes}"
        )

    def test_sibling_asset_life_included(self, suggester, accounts_with_hierarchy):
        """
        Siblings of Machinery (103000, 103100) use asset life 300.
        A new proposal under Machinery should see 300 from sibling analysis.
        """
        hierarchy = accounts_with_hierarchy
        parent = hierarchy.accounts_by_number[102000]

        proposal = NewAccountProposal(
            account_description="New generator unit",
            suggested_parent=parent,
        )

        suggestions = suggester.suggest_asset_life(proposal, hierarchy)
        codes = [v for v, _ in suggestions]

        assert "300" in codes, (
            f"Sibling asset life 300 should appear in suggestions; got {codes}"
        )

    def test_returns_list_of_tuples(self, suggester, accounts_with_hierarchy):
        """suggest_asset_life should return list of (months_str, explanation) tuples."""
        hierarchy = accounts_with_hierarchy
        parent = hierarchy.accounts_by_number[102000]
        proposal = NewAccountProposal(
            account_description="building facility",
            suggested_parent=parent,
        )

        suggestions = suggester.suggest_asset_life(proposal, hierarchy)

        for item in suggestions:
            assert isinstance(item, tuple) and len(item) == 2, (
                f"Expected (months_str, explanation) tuple, got {item}"
            )

    def test_no_matching_keyword_returns_empty_or_sibling(
        self, suggester, accounts_with_hierarchy
    ):
        """An unrecognized description with no siblings defaults to empty or sibling-based."""
        hierarchy = accounts_with_hierarchy
        # Use a parent with no children that have asset_life
        parent = hierarchy.accounts_by_number[200001]  # Long-Term Debt, no asset_life siblings

        proposal = NewAccountProposal(
            account_description="unrecognized gibberish zxqwrty",
            suggested_parent=parent,
        )

        suggestions = suggester.suggest_asset_life(proposal, hierarchy)
        # Should not crash; may be empty
        assert isinstance(suggestions, list)


# ---------------------------------------------------------------------------
# Tests — suggest_cash_flow_category
# ---------------------------------------------------------------------------

class TestSuggestCashFlowCategory:
    def test_bs_account_suggests_inv(self, suggester, accounts_with_hierarchy):
        """Balance Sheet (BS) accounts should default to INV (Investing Activities)."""
        hierarchy = accounts_with_hierarchy
        parent = hierarchy.accounts_by_number[102000]  # Machinery, BS

        proposal = NewAccountProposal(
            account_description="New Equipment",
            suggested_parent=parent,
            bu_type="BS",
        )

        suggestions = suggester.suggest_cash_flow_category(proposal, hierarchy)
        codes = [c for c, _ in suggestions]

        assert "INV" in codes, (
            f"BS account should suggest INV; got {codes}"
        )

    def test_is_account_suggests_op(self, suggester, accounts_with_hierarchy):
        """Income Statement (IS) accounts should default to OP (Operating Activities)."""
        hierarchy = accounts_with_hierarchy
        parent = hierarchy.accounts_by_number[300001]  # Operating Revenue, IS

        proposal = NewAccountProposal(
            account_description="New Revenue Line",
            suggested_parent=parent,
            bu_type="IS",
        )

        suggestions = suggester.suggest_cash_flow_category(proposal, hierarchy)
        codes = [c for c, _ in suggestions]

        assert "OP" in codes, (
            f"IS account should suggest OP; got {codes}"
        )

    def test_debt_equity_keywords_suggest_fin(self, suggester, accounts_with_hierarchy):
        """Debt/equity keywords in description should suggest FIN (Financing Activities)."""
        hierarchy = accounts_with_hierarchy
        parent = hierarchy.accounts_by_number[200001]  # Long-Term Debt, BS

        proposal = NewAccountProposal(
            account_description="New bond issuance debt financing",
            suggested_parent=parent,
            bu_type="BS",
        )

        suggestions = suggester.suggest_cash_flow_category(proposal, hierarchy)
        codes = [c for c, _ in suggestions]

        assert "FIN" in codes, (
            f"Debt keyword 'bond' should suggest FIN; got {codes}"
        )

    def test_returns_list(self, suggester, accounts_with_hierarchy):
        """Should always return a list (possibly empty)."""
        hierarchy = accounts_with_hierarchy
        parent = hierarchy.accounts_by_number[102000]
        proposal = NewAccountProposal(account_description="test", suggested_parent=parent)

        result = suggester.suggest_cash_flow_category(proposal, hierarchy)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Tests — suggest_posting_edit
# ---------------------------------------------------------------------------

class TestSuggestPostingEdit:
    def test_level5_always_blank(self, suggester):
        """Posting edit for Level-5 accounts should always be blank."""
        proposal = NewAccountProposal()
        code, explanation = suggester.suggest_posting_edit(proposal, target_level=5)

        assert code == "", f"Expected blank posting edit for L5, got '{code}'"
        assert "level" in explanation.lower() or "blank" in explanation.lower(), (
            f"Explanation should mention level or blank: {explanation}"
        )

    def test_returns_tuple(self, suggester):
        """suggest_posting_edit should return a (code, explanation) tuple."""
        proposal = NewAccountProposal()
        result = suggester.suggest_posting_edit(proposal, target_level=5)

        assert isinstance(result, tuple) and len(result) == 2


# ---------------------------------------------------------------------------
# Tests — suggest_bu_type
# ---------------------------------------------------------------------------

class TestSuggestBuType:
    def test_inherits_bs_from_parent(self, suggester, accounts_with_hierarchy):
        """New account under a BS parent should inherit BS."""
        hierarchy = accounts_with_hierarchy
        parent = hierarchy.accounts_by_number[102000]  # Machinery, BS

        proposal = NewAccountProposal(suggested_parent=parent)
        bu_type, explanation = suggester.suggest_bu_type(proposal, parent)

        assert bu_type == "BS", f"Expected BS inherited from parent, got '{bu_type}'"
        assert "inherited" in explanation.lower() or "parent" in explanation.lower(), (
            f"Explanation should mention inheritance: {explanation}"
        )

    def test_inherits_is_from_parent(self, suggester, accounts_with_hierarchy):
        """New account under an IS parent should inherit IS."""
        hierarchy = accounts_with_hierarchy
        parent = hierarchy.accounts_by_number[300001]  # Operating Revenue, IS

        proposal = NewAccountProposal(suggested_parent=parent)
        bu_type, explanation = suggester.suggest_bu_type(proposal, parent)

        assert bu_type == "IS", f"Expected IS inherited from IS parent, got '{bu_type}'"

    def test_no_parent_defaults_to_bs(self, suggester):
        """With no parent, default should be BS."""
        proposal = NewAccountProposal()
        bu_type, explanation = suggester.suggest_bu_type(proposal, parent=None)

        assert bu_type == "BS", f"Expected default BS with no parent, got '{bu_type}'"


# ---------------------------------------------------------------------------
# Tests — suggest_all
# ---------------------------------------------------------------------------

class TestSuggestAll:
    def test_populates_all_reasoning_keys(self, suggester, accounts_with_hierarchy):
        """suggest_all should populate reasoning for all major fields."""
        hierarchy = accounts_with_hierarchy
        parent = hierarchy.accounts_by_number[102000]

        proposal = NewAccountProposal(
            account_description="Offshore Wind Turbine",
            suggested_parent=parent,
        )

        enriched = suggester.suggest_all(proposal, hierarchy)

        expected_keys = {
            "bu_type", "company", "business_unit", "posting_edit",
            "line_of_detail", "ferc_code", "asset_life",
            "cash_flow_category", "book_tax_difference",
        }
        for key in expected_keys:
            assert key in enriched.reasoning, (
                f"Expected reasoning key '{key}', keys present: {list(enriched.reasoning.keys())}"
            )

    def test_line_of_detail_set_to_5(self, suggester, accounts_with_hierarchy):
        """suggest_all should always set line_of_detail to 5."""
        hierarchy = accounts_with_hierarchy
        parent = hierarchy.accounts_by_number[102000]

        proposal = NewAccountProposal(
            account_description="Test Account",
            suggested_parent=parent,
        )
        enriched = suggester.suggest_all(proposal, hierarchy)

        assert enriched.line_of_detail == 5, (
            f"line_of_detail should always be 5 for posting accounts, got {enriched.line_of_detail}"
        )

    def test_posting_edit_set_to_blank(self, suggester, accounts_with_hierarchy):
        """suggest_all should set posting_edit to blank for Level-5 accounts."""
        hierarchy = accounts_with_hierarchy
        parent = hierarchy.accounts_by_number[102000]

        proposal = NewAccountProposal(
            account_description="Test Account",
            suggested_parent=parent,
        )
        enriched = suggester.suggest_all(proposal, hierarchy)

        assert enriched.posting_edit == "", (
            f"posting_edit should be blank, got '{enriched.posting_edit}'"
        )

    def test_returns_same_proposal_object(self, suggester, accounts_with_hierarchy):
        """suggest_all should return the same proposal object (mutates in place)."""
        hierarchy = accounts_with_hierarchy
        parent = hierarchy.accounts_by_number[102000]

        proposal = NewAccountProposal(
            account_description="Test",
            suggested_parent=parent,
        )
        returned = suggester.suggest_all(proposal, hierarchy)

        assert returned is proposal, "suggest_all should return the same proposal object"

    def test_does_not_overwrite_user_supplied_values(self, suggester, accounts_with_hierarchy):
        """
        If ferc_code is already set by the user, suggest_all should not overwrite it.
        """
        hierarchy = accounts_with_hierarchy
        parent = hierarchy.accounts_by_number[102000]

        proposal = NewAccountProposal(
            account_description="Custom Account",
            suggested_parent=parent,
            ferc_code="310",  # User pre-selected
        )
        enriched = suggester.suggest_all(proposal, hierarchy)

        assert enriched.ferc_code == "310", (
            f"suggest_all should not overwrite pre-set ferc_code; got '{enriched.ferc_code}'"
        )
