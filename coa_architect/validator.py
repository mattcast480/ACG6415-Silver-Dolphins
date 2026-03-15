"""
validator.py — Stateless validation rules for the CoA Architect.

AccountValidator enforces four hard safety rules on account numbers:
  1. Must be a 6-digit integer (100000–999999)
  2. Must not already be in use
  3. Must fall inside an owned AccountRange (not in a gap between ranges)
  4. Must not coincide with an existing header account boundary

It also validates reference-data codes (FERC, asset life) and can expose
the list of gap ranges for explanatory error messages.
"""

from typing import List, Optional, Tuple

from .models import AccountHierarchy, ReferenceData


class AccountValidator:
    """
    Provides stateless validation methods.  Each method returns (bool, str)
    where the bool is True on success and the str explains any failure.
    """

    # ------------------------------------------------------------------
    # Account Number Validation
    # ------------------------------------------------------------------

    def validate_account_number(
        self, number: int, hierarchy: AccountHierarchy,
        business_unit: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Enforces all four safety rules for a proposed account number.

        Rule 1 — Must be 6 digits (100000 through 999999).
        Rule 2 — Must not already be in use for the same business unit.
                 If business_unit is provided, checks the composite key
                 (account_number, business_unit) so the same number is
                 allowed across different business units.
        Rule 3 — Must fall inside an owned AccountRange (no gaps).
        Rule 4 — Must not equal an existing header account's number.
        """
        # Rule 1: 6-digit range check
        if not isinstance(number, int) or not (100000 <= number <= 999999):
            return False, (
                f"{number} is not a valid 6-digit account number. "
                "Must be between 100000 and 999999."
            )

        # Rule 2: Already in use for this business unit?
        if business_unit is not None:
            # Same number is allowed if the business unit differs
            if (number, business_unit) in hierarchy.accounts_by_number_and_bu:
                existing = hierarchy.accounts_by_number.get(number)
                desc = existing.account_description if existing else "unknown"
                return False, (
                    f"Account number {number} is already in use for business unit "
                    f"'{business_unit}': '{desc}'. Choose a different number."
                )
        else:
            # No BU provided — fall back to number-only check
            if number in hierarchy.accounts_by_number:
                existing = hierarchy.accounts_by_number[number]
                return False, (
                    f"Account number {number} is already in use: "
                    f"'{existing.account_description}' (Level {existing.line_of_detail})."
                )

        # Rule 3: Falls inside an owned range?
        owning_range = self._find_owning_range(number, hierarchy)
        if owning_range is None:
            gaps = self.identify_gap_ranges(hierarchy)
            gap_msg = ""
            for gap_start, gap_end in gaps:
                if gap_start <= number <= gap_end:
                    gap_msg = (
                        f" {number} falls in the unowned gap "
                        f"{gap_start}–{gap_end}, which has no parent account."
                    )
                    break
            return False, (
                f"Account number {number} does not fall inside any defined range.{gap_msg} "
                "Please choose a number within an existing parent account's range."
            )

        # Rule 4: Coincides with an existing header?
        # (This is already covered by Rule 2, but we add a clearer message here
        #  for the case where someone proposes a number matching a header exactly.)
        owner = owning_range.owner_account
        if number == owner.account_number:
            return False, (
                f"{number} is the boundary number of header account "
                f"'{owner.account_description}'. Choose a different number."
            )

        return True, "OK"

    def validate_number_is_safe(
        self, proposed_number: int, hierarchy: AccountHierarchy
    ) -> Tuple[bool, str]:
        """
        Alias that matches the interface described in the plan.
        Delegates to validate_account_number.
        """
        return self.validate_account_number(proposed_number, hierarchy)

    def _find_owning_range(self, number: int, hierarchy: AccountHierarchy):
        """
        Returns the AccountRange that contains the given number,
        or None if the number falls in a gap.
        """
        for ar in hierarchy.ranges:
            if ar.range_start <= number <= ar.range_end:
                return ar
        return None

    def identify_gap_ranges(self, hierarchy: AccountHierarchy) -> List[Tuple[int, int]]:
        """
        Returns a list of (gap_start, gap_end) tuples representing number
        ranges that are not owned by any account.

        These are the "forbidden zones" — any proposed number in these
        ranges will be rejected with a clear explanation.
        """
        # Collect all owned intervals, sorted by start
        owned = sorted(
            [(ar.range_start, ar.range_end) for ar in hierarchy.ranges],
            key=lambda x: x[0],
        )

        # Merge overlapping or adjacent intervals (a child's range is
        # fully contained within its parent's range, so overlaps are normal)
        merged = []
        for start, end in owned:
            if merged and start <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append([start, end])

        # The gaps are the spaces between merged intervals
        gaps = []
        for i in range(1, len(merged)):
            gap_start = merged[i - 1][1] + 1
            gap_end = merged[i][0] - 1
            if gap_start <= gap_end:
                gaps.append((gap_start, gap_end))

        return gaps

    # ------------------------------------------------------------------
    # Reference Code Validation
    # ------------------------------------------------------------------

    def validate_ferc_code(
        self, code: str, reference_data: ReferenceData
    ) -> Tuple[bool, str]:
        """
        Checks that the given FERC code exists in the reference data.
        Allows blank/empty codes (some accounts legitimately have no FERC code).
        """
        if not code or not str(code).strip():
            return True, "Blank FERC code is acceptable."

        code_str = str(code).strip()
        if reference_data.ferc_codes and code_str not in reference_data.ferc_codes:
            available = sorted(reference_data.ferc_codes.keys())[:10]
            return False, (
                f"FERC code '{code_str}' is not in the reference list. "
                f"Sample valid codes: {', '.join(available)} ..."
            )

        return True, "OK"

    def validate_asset_life(
        self, value: str, reference_data: ReferenceData
    ) -> Tuple[bool, str]:
        """
        Checks that the given asset life value exists in the reference data.
        Allows blank/None (non-depreciable accounts have no asset life).
        """
        if not value or not str(value).strip():
            return True, "Blank asset life is acceptable for non-depreciable accounts."

        value_str = str(value).strip()
        if reference_data.asset_life_codes and value_str not in reference_data.asset_life_codes:
            available = sorted(reference_data.asset_life_codes.keys())
            return False, (
                f"Asset life '{value_str}' is not in the reference list. "
                f"Valid values: {', '.join(available)}"
            )

        return True, "OK"

    def validate_cash_flow_category(
        self, code: str, reference_data: ReferenceData
    ) -> Tuple[bool, str]:
        """
        Checks that the given cash flow category code exists in the reference data.
        Allows blank (many accounts have no cash flow classification).
        """
        if not code or not str(code).strip():
            return True, "Blank cash flow category is acceptable."

        code_str = str(code).strip()
        if reference_data.cash_flow_codes and code_str not in reference_data.cash_flow_codes:
            available = sorted(reference_data.cash_flow_codes.keys())
            return False, (
                f"Cash flow category '{code_str}' is not in the reference list. "
                f"Valid values: {', '.join(available)}"
            )

        return True, "OK"
