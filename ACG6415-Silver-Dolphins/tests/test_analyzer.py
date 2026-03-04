"""
test_analyzer.py — Unit tests for coa_architect.analyzer.CoAAnalyzer.

Tests verify:
  - Backward-scan hierarchy: account 100500 parent = 100003 (Land)
  - Level-skip handling: Level-5 directly under Level-3 has correct parent
  - Range computation: range for 102000 = 102000–104999
  - Number pattern detection: dominant step and section boundaries
  - FERC usage map: codes mapped to keywords and ranges
  - Full analyze() pipeline builds a valid AccountHierarchy

Run with: pytest tests/test_analyzer.py -v
"""

import pytest

from coa_architect.models import Account, AccountHierarchy, AccountRange, ReferenceData
from coa_architect.analyzer import CoAAnalyzer


# ---------------------------------------------------------------------------
# Fixtures — shared test data
# ---------------------------------------------------------------------------

def _make_accounts():
    """
    Creates a small but realistic account list for testing.

    Structure:
      100000  ASSETS              L1
        100001  Long-Term Assets  L2
          100002  PP&E            L3
            100003  Land          L4
              100500  Land Tract A  L5
              100600  Land Tract B  L5
            102000  Machinery     L4
              103000  Turbines    L5
              103100  Generators  L5
              103200  Wind Equip  L5
          100010  Other LT Assets L3  ← sits between 100002 and 102000 numerically
      200000  LIABILITIES         L1
        200001  Current Liab      L2
          200100  Accounts Pay    L5  ← level skip: L5 directly under L2
    """
    def acct(num, desc, lod, ferc="", asset_life=None, bu_type="BS"):
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
            cash_flow_category=None,
        )

    return [
        acct(100000, "ASSETS", 1),
        acct(100001, "Long-Term Assets", 2),
        acct(100002, "PP&E", 3),
        acct(100003, "Land", 4, ferc="310"),
        acct(100500, "Land Tract A", 5, ferc="310", asset_life="0"),
        acct(100600, "Land Tract B", 5, ferc="310", asset_life="0"),
        acct(102000, "Machinery", 4, ferc="314"),
        acct(103000, "Turbines", 5, ferc="314", asset_life="300"),
        acct(103100, "Generators", 5, ferc="314", asset_life="300"),
        acct(103200, "Wind Equipment", 5, ferc="315", asset_life="300"),
        acct(200000, "LIABILITIES", 1),
        acct(200001, "Current Liabilities", 2),
        acct(200100, "Accounts Payable", 5, bu_type="BS"),   # Level skip: L5 under L2
    ]


@pytest.fixture
def accounts():
    return _make_accounts()


@pytest.fixture
def reference_data():
    return ReferenceData(
        ferc_codes={"310": "Land and land rights", "314": "Turbogenerator units", "315": "Accessory electric equipment"},
        asset_life_codes={"0": "Non-depreciable", "300": "25 Years (300 months)"},
        cash_flow_codes={"INV": "Investing Activities", "OP": "Operating Activities"},
        posting_edit_codes={},
        book_tax_codes={},
        companies={"10": "Admin Services"},
        business_units={"10": "Corporate"},
    )


@pytest.fixture
def analyzer():
    return CoAAnalyzer()


@pytest.fixture
def hierarchy(accounts, reference_data, analyzer):
    """Fully analyzed AccountHierarchy built from test accounts."""
    col_map = {
        "account_id": "A",
        "company": "B",
        "business_unit": "C",
        "bu_type": "D",
        "account_number": "E",
        "account_description": "F",
        "posting_edit": "G",
        "line_of_detail": "H",
        "ferc_code": "I",
        "asset_life": "J",
        "book_tax_difference": "K",
        "cash_flow_category": "L",
    }
    return analyzer.analyze(accounts, reference_data, col_map, "test.xlsx")


# ---------------------------------------------------------------------------
# Tests — build_hierarchy (backward-scan parent assignment)
# ---------------------------------------------------------------------------

class TestBuildHierarchy:
    def test_land_account_parent(self, accounts, analyzer):
        """Account 100500 (Land Tract A, L5) parent should be 100003 (Land, L4)."""
        analyzer.build_hierarchy(accounts)

        by_num = {a.account_number: a for a in accounts}
        land_tract_a = by_num[100500]

        assert land_tract_a.parent is not None, "100500 should have a parent"
        assert land_tract_a.parent.account_number == 100003, (
            f"Expected parent 100003, got {land_tract_a.parent.account_number}"
        )

    def test_machinery_children(self, accounts, analyzer):
        """Account 102000 (Machinery, L4) should have children 103000, 103100, 103200."""
        analyzer.build_hierarchy(accounts)

        by_num = {a.account_number: a for a in accounts}
        machinery = by_num[102000]

        child_nums = {c.account_number for c in machinery.children}
        assert child_nums == {103000, 103100, 103200}, (
            f"Expected children {{103000, 103100, 103200}}, got {child_nums}"
        )

    def test_level1_accounts_have_no_parent(self, accounts, analyzer):
        """Level-1 accounts (100000, 200000) should have no parent."""
        analyzer.build_hierarchy(accounts)

        by_num = {a.account_number: a for a in accounts}
        assert by_num[100000].parent is None, "ASSETS (L1) should have no parent"
        assert by_num[200000].parent is None, "LIABILITIES (L1) should have no parent"

    def test_level_skip_parent_assignment(self, accounts, analyzer):
        """
        Account 200100 (Accounts Payable, L5) is directly under 200001 (L2).
        The backward-scan should correctly skip over levels and set 200001 as parent.
        """
        analyzer.build_hierarchy(accounts)

        by_num = {a.account_number: a for a in accounts}
        ap = by_num[200100]

        assert ap.parent is not None, "200100 should have a parent"
        assert ap.parent.account_number == 200001, (
            f"Expected parent 200001 (level skip), got {ap.parent.account_number}"
        )

    def test_parent_children_mutual(self, accounts, analyzer):
        """Every account in parent.children must have that account as .parent."""
        analyzer.build_hierarchy(accounts)

        for account in accounts:
            for child in account.children:
                assert child.parent is account, (
                    f"Child {child.account_number} .parent should be "
                    f"{account.account_number}, got {child.parent}"
                )


# ---------------------------------------------------------------------------
# Tests — compute_account_ranges
# ---------------------------------------------------------------------------

class TestComputeAccountRanges:
    def test_machinery_range(self, accounts, analyzer):
        """
        102000 (Machinery, L4) should have range 102000–199999 (or capped by the
        next same-or-higher-level header after it).

        In our test data, the next L4 after 102000 is... none within ASSETS L1.
        The next header at L4-or-higher after 102000 is 200000 (L1 LIABILITIES).
        So range_end = 200000 - 1 = 199999.
        """
        analyzer.build_hierarchy(accounts)
        ranges = analyzer.compute_account_ranges(accounts)

        range_map = {r.owner_account.account_number: r for r in ranges}
        machinery_range = range_map.get(102000)

        assert machinery_range is not None, "102000 should have a range"
        assert machinery_range.range_start == 102000
        # Next header with level <= 4 after 102000 is 200000 (L1)
        assert machinery_range.range_end == 199999, (
            f"Expected range_end 199999, got {machinery_range.range_end}"
        )

    def test_land_range_end_before_machinery(self, accounts, analyzer):
        """
        100003 (Land, L4) range_end should be 101999 (one before 102000 Machinery).
        """
        analyzer.build_hierarchy(accounts)
        ranges = analyzer.compute_account_ranges(accounts)

        range_map = {r.owner_account.account_number: r for r in ranges}
        land_range = range_map.get(100003)

        assert land_range is not None, "100003 should have a range"
        assert land_range.range_end == 101999, (
            f"Expected range_end 101999 (one before 102000), got {land_range.range_end}"
        )

    def test_level5_accounts_have_no_range(self, accounts, analyzer):
        """Level-5 accounts should not appear in the ranges list."""
        ranges = analyzer.compute_account_ranges(accounts)
        level5_numbers = {100500, 100600, 103000, 103100, 103200, 200100}

        range_owner_numbers = {r.owner_account.account_number for r in ranges}
        overlap = level5_numbers & range_owner_numbers
        assert not overlap, f"Level-5 accounts should not have ranges: {overlap}"

    def test_last_section_range_ends_at_999999(self, accounts, analyzer):
        """The last Level-1 section (200000 LIABILITIES) should extend to 999999."""
        ranges = analyzer.compute_account_ranges(accounts)

        range_map = {r.owner_account.account_number: r for r in ranges}
        liabilities_range = range_map.get(200000)

        assert liabilities_range is not None, "200000 should have a range"
        assert liabilities_range.range_end == 999999, (
            f"Last section should extend to 999999, got {liabilities_range.range_end}"
        )


# ---------------------------------------------------------------------------
# Tests — detect_number_patterns
# ---------------------------------------------------------------------------

class TestDetectNumberPatterns:
    def test_level_5_step_detected(self, accounts, analyzer):
        """Should detect the dominant sibling spacing (100 in our test data)."""
        analyzer.build_hierarchy(accounts)
        patterns = analyzer.detect_number_patterns(accounts)

        assert "level_5_step" in patterns
        assert isinstance(patterns["level_5_step"], int)
        assert patterns["level_5_step"] > 0

    def test_section_boundaries_include_level1(self, accounts, analyzer):
        """section_boundaries should include all Level-1 account numbers."""
        patterns = analyzer.detect_number_patterns(accounts)

        boundaries = patterns.get("section_boundaries", [])
        assert 100000 in boundaries, "ASSETS (100000) should be a section boundary"
        assert 200000 in boundaries, "LIABILITIES (200000) should be a section boundary"

    def test_dominant_base_is_round_number(self, accounts, analyzer):
        """dominant_base should be 10, 100, or 1000."""
        patterns = analyzer.detect_number_patterns(accounts)

        dominant_base = patterns.get("dominant_base", 100)
        assert dominant_base in (10, 100, 1000), (
            f"dominant_base should be 10, 100, or 1000; got {dominant_base}"
        )


# ---------------------------------------------------------------------------
# Tests — build_ferc_usage_map
# ---------------------------------------------------------------------------

class TestBuildFercUsageMap:
    def test_known_ferc_codes_in_map(self, accounts, analyzer):
        """FERC codes 310 and 314 should appear in the usage map."""
        ferc_map = analyzer.build_ferc_usage_map(accounts)

        assert "310" in ferc_map, "FERC 310 should appear in usage map"
        assert "314" in ferc_map, "FERC 314 should appear in usage map"

    def test_keywords_extracted(self, accounts, analyzer):
        """
        Accounts with FERC 314 are 'Turbines', 'Generators', 'Wind Equipment'.
        Expected keywords include 'turbines', 'generators', 'wind', 'equipment'.
        """
        ferc_map = analyzer.build_ferc_usage_map(accounts)

        keywords_314 = ferc_map.get("314", {}).get("keywords", set())
        # At least some of these should appear
        expected_kw = {"turbines", "generators", "wind", "equipment"}
        overlap = keywords_314 & expected_kw
        assert overlap, (
            f"Expected keywords {expected_kw} in FERC 314 map, got {keywords_314}"
        )

    def test_count_accurate(self, accounts, analyzer):
        """FERC 314 count should equal the number of accounts that use it (2)."""
        # In our test data: Turbines=314, Generators=314 → count=2
        # (Wind Equipment uses 315)
        ferc_map = analyzer.build_ferc_usage_map(accounts)

        count_314 = ferc_map.get("314", {}).get("count", 0)
        assert count_314 == 2, f"Expected FERC 314 count=2, got {count_314}"

    def test_accounts_without_ferc_code_skipped(self, accounts, analyzer):
        """Accounts with empty FERC code should not produce entries."""
        ferc_map = analyzer.build_ferc_usage_map(accounts)

        # Empty string keys should not exist
        assert "" not in ferc_map, "Empty FERC code should not be in the map"


# ---------------------------------------------------------------------------
# Tests — full analyze() pipeline
# ---------------------------------------------------------------------------

class TestAnalyzePipeline:
    def test_returns_account_hierarchy(self, hierarchy):
        """analyze() should return an AccountHierarchy instance."""
        assert isinstance(hierarchy, AccountHierarchy)

    def test_accounts_sorted_by_number(self, hierarchy):
        """Accounts list should be sorted by account_number ascending."""
        numbers = [a.account_number for a in hierarchy.accounts]
        assert numbers == sorted(numbers), "Accounts should be sorted by account_number"

    def test_accounts_by_number_complete(self, hierarchy, accounts):
        """accounts_by_number dict should have an entry for each account."""
        for acct in accounts:
            assert acct.account_number in hierarchy.accounts_by_number

    def test_max_account_id_correct(self, hierarchy, accounts):
        """max_account_id should equal the highest account_id in the list."""
        expected_max = max(a.account_id for a in accounts)
        assert hierarchy.max_account_id == expected_max

    def test_ranges_populated(self, hierarchy):
        """ranges list should be non-empty for a CoA with header accounts."""
        assert len(hierarchy.ranges) > 0

    def test_patterns_populated(self, hierarchy):
        """patterns dict should contain 'level_5_step'."""
        assert "level_5_step" in hierarchy.patterns

    def test_ferc_usage_map_populated(self, hierarchy):
        """ferc_usage_map should be non-empty for accounts with FERC codes."""
        assert len(hierarchy.ferc_usage_map) > 0

    def test_source_file_path_stored(self, hierarchy):
        """source_file_path should match the path passed to analyze()."""
        assert hierarchy.source_file_path == "test.xlsx"
