"""
analyzer.py — Builds the account hierarchy, computes ranges, and detects patterns.

CoAAnalyzer is the most algorithmically complex module. Its key contributions:
  1. build_hierarchy()      — backward-scan to assign parent/children links
  2. compute_account_ranges() — determine the number range each header "owns"
  3. detect_number_patterns() — find dominant sibling spacing (e.g. +100)
  4. build_ferc_usage_map()   — map FERC codes to keywords and number ranges
  5. analyze()              — orchestrates all of the above → AccountHierarchy
"""

from collections import Counter
from typing import List, Optional

from .models import Account, AccountHierarchy, AccountRange, ReferenceData


class CoAAnalyzer:
    """
    Transforms a flat list of Account objects into a fully-linked hierarchy
    with range ownership, pattern detection, and FERC usage mapping.
    """

    # ------------------------------------------------------------------
    # 1. Hierarchy Construction (backward-scan algorithm)
    # ------------------------------------------------------------------

    def build_hierarchy(self, accounts: List[Account]) -> None:
        """
        Assigns parent and children links to every Account in-place.

        Algorithm (backward scan):
          For each account[i] (sorted by account_number):
            Scan backward from i-1 to 0.
            The first account[j] with a strictly lower line_of_detail is the parent.
            This correctly handles level skips (e.g. Level-5 directly under Level-3).

        After this call, every Account has .parent set (or None for root-level
        accounts) and .children populated with direct descendants.
        """
        # Work on a copy sorted by account_number to ensure correct traversal order
        sorted_accounts = sorted(accounts, key=lambda a: a.account_number)

        for i, account in enumerate(sorted_accounts):
            # Scan backwards to find the first account with a lower level number
            for j in range(i - 1, -1, -1):
                candidate = sorted_accounts[j]
                if candidate.line_of_detail < account.line_of_detail:
                    # Found the parent
                    account.parent = candidate
                    candidate.children.append(account)
                    break
            # If no parent found, this is a root-level (Level-1) account

    # ------------------------------------------------------------------
    # 2. Range Ownership
    # ------------------------------------------------------------------

    def compute_account_ranges(self, accounts: List[Account]) -> List[AccountRange]:
        """
        Computes the number range owned by each non-leaf (header) account.

        For each header account h[i] (sorted by account_number):
          range_start = h[i].account_number
          range_end   = (next h[j] where h[j].line_of_detail <= h[i].line_of_detail)
                        .account_number - 1
                        OR 999999 if no such sibling/ancestor exists

        Only accounts with line_of_detail < 5 get ranges (Level-5 accounts are
        leaf/posting accounts — they own no range themselves).
        """
        # Consider only header accounts (not Level-5 posting accounts)
        headers = [a for a in accounts if a.line_of_detail < 5]
        headers.sort(key=lambda a: a.account_number)

        ranges = []
        for i, header in enumerate(headers):
            range_start = header.account_number

            # Search forward for the next account at the same or higher hierarchy level
            range_end = 999999  # default: extends to end of number space
            for j in range(i + 1, len(headers)):
                next_header = headers[j]
                if next_header.line_of_detail <= header.line_of_detail:
                    range_end = next_header.account_number - 1
                    break

            ranges.append(AccountRange(
                owner_account=header,
                range_start=range_start,
                range_end=range_end,
            ))

        return ranges

    # ------------------------------------------------------------------
    # 3. Number Pattern Detection
    # ------------------------------------------------------------------

    def detect_number_patterns(self, accounts: List[Account]) -> dict:
        """
        Analyzes spacing patterns among Level-5 sibling accounts.

        Returns a dict with:
          level_5_step:       Most common gap between consecutive Level-5
                              siblings (int), e.g. 100
          dominant_base:      Most common rounding unit among all account
                              numbers (int), e.g. 100
          section_boundaries: List of account_numbers where a new Level-1
                              section starts
        """
        level5 = sorted(
            [a for a in accounts if a.line_of_detail == 5],
            key=lambda a: a.account_number,
        )

        # Compute gaps between consecutive Level-5 siblings that share a parent
        sibling_gaps = []
        for i in range(1, len(level5)):
            prev = level5[i - 1]
            curr = level5[i]
            # Only count gaps within the same parent (same structural section)
            if prev.parent is not None and curr.parent is not None:
                if prev.parent.account_number == curr.parent.account_number:
                    gap = curr.account_number - prev.account_number
                    if 0 < gap <= 10000:  # Ignore obviously-wrong huge gaps
                        sibling_gaps.append(gap)

        level_5_step = 100  # Default if we can't determine
        if sibling_gaps:
            gap_counts = Counter(sibling_gaps)
            level_5_step = gap_counts.most_common(1)[0][0]

        # Determine the dominant rounding base (100 vs 1000 vs 10, etc.)
        all_numbers = [a.account_number for a in accounts]
        base_candidates = [1000, 100, 10]
        dominant_base = 100  # default
        for base in base_candidates:
            divisible = sum(1 for n in all_numbers if n % base == 0)
            if divisible / max(len(all_numbers), 1) >= 0.3:
                dominant_base = base
                break

        # Identify where Level-1 sections begin (each defines a top-level segment)
        level1 = sorted(
            [a for a in accounts if a.line_of_detail == 1],
            key=lambda a: a.account_number,
        )
        section_boundaries = [a.account_number for a in level1]

        return {
            "level_5_step": level_5_step,
            "dominant_base": dominant_base,
            "section_boundaries": section_boundaries,
        }

    # ------------------------------------------------------------------
    # 4. FERC Usage Map
    # ------------------------------------------------------------------

    def build_ferc_usage_map(self, accounts: List[Account]) -> dict:
        """
        Builds a mapping from each FERC code to the number ranges and
        description keywords where that code appears in the CoA.

        Return structure:
          {
            "314": {
              "ranges": [(102000, 104999), ...],
              "keywords": {"turbine", "generator", "wind", ...},
              "count": 5,
            },
            ...
          }

        This is used by the suggester to make evidence-based FERC suggestions.
        """
        ferc_map = {}

        for account in accounts:
            code = str(account.ferc_code).strip() if account.ferc_code else ""
            if not code:
                continue

            if code not in ferc_map:
                ferc_map[code] = {"ranges": [], "keywords": set(), "count": 0}

            ferc_map[code]["count"] += 1

            # Add account number as a range marker (we store individual numbers;
            # the suggester can expand to ranges if needed)
            ferc_map[code]["ranges"].append(account.account_number)

            # Extract meaningful keywords from the account description
            description = account.account_description.lower()
            # Split on spaces and common separators; keep words longer than 2 chars
            words = set(
                w.strip("(),./\\-") for w in description.split()
                if len(w.strip("(),./\\-")) > 2
            )
            # Filter out generic stop words
            stop_words = {
                "and", "the", "for", "with", "from", "this", "that", "are",
                "not", "all", "any", "can", "has", "but", "its", "was",
                "had", "been", "have", "will", "more", "also", "than",
                "into", "each", "such", "when", "then", "some", "over",
                "other", "account", "accounts",
            }
            ferc_map[code]["keywords"] |= (words - stop_words)

        return ferc_map

    # ------------------------------------------------------------------
    # 5. Main Orchestration Method
    # ------------------------------------------------------------------

    def analyze(
        self,
        accounts: List[Account],
        reference_data: ReferenceData,
        column_mapping: dict,
        file_path: str,
    ) -> AccountHierarchy:
        """
        Runs the full analysis pipeline and returns an AccountHierarchy.

        Steps:
          1. Sort accounts by account_number
          2. Build parent/child links (backward-scan)
          3. Compute range ownership
          4. Detect spacing patterns
          5. Build FERC usage map
          6. Package everything into AccountHierarchy
        """
        # Sort in place by account number — this is the canonical ordering
        accounts.sort(key=lambda a: a.account_number)

        # Link parents and children
        self.build_hierarchy(accounts)

        # Build range ownership for all header accounts
        ranges = self.compute_account_ranges(accounts)

        # Detect numeric spacing patterns used for safe number suggestions
        patterns = self.detect_number_patterns(accounts)

        # Build the FERC usage map for evidence-based code suggestions
        ferc_usage_map = self.build_ferc_usage_map(accounts)

        # Build O(1) lookup table by account number
        accounts_by_number = {a.account_number: a for a in accounts}

        # Find the highest account_id for sequence continuation
        max_account_id = max((a.account_id for a in accounts), default=0)

        return AccountHierarchy(
            accounts=accounts,
            reference_data=reference_data,
            ranges=ranges,
            accounts_by_number=accounts_by_number,
            source_file_path=file_path,
            column_mapping=column_mapping,
            max_account_id=max_account_id,
            patterns=patterns,
            ferc_usage_map=ferc_usage_map,
        )
