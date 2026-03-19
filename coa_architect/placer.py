"""
placer.py — Scores parent candidates and suggests safe account numbers.

AccountPlacer is the business-rule engine for "where does a new account go?"

Two responsibilities:
  1. score_parent_candidates() — ranks all Level 1–4 accounts by how well
     they match the user's plain-English description (keyword overlap, BU type,
     FERC consistency, level depth, naming pattern similarity).

  2. find_available_numbers_in_range() — given a chosen parent, returns up to
     5 candidate account numbers that are safe (within range, unused).
"""

import math
import re
from collections import Counter
from typing import List, Optional, Tuple

from .models import Account, AccountHierarchy, AccountRange
from .validator import AccountValidator


# Scoring weights for parent candidate ranking (total = 100 points)
W_KEYWORD = 25    # Keyword overlap between description and account name
W_BU_TYPE = 20   # BU type consistency within section
W_FERC = 20      # FERC code consistency with siblings
W_LEVEL = 15     # Prefer deeper parents (more specific placement)
W_NAMING = 20    # Naming pattern similarity (length, word style)


class AccountPlacer:
    """
    Scores potential parent accounts and finds safe number candidates.
    """

    def __init__(self):
        self._validator = AccountValidator()

    # ------------------------------------------------------------------
    # 1. Parent Candidate Scoring
    # ------------------------------------------------------------------

    def score_parent_candidates(
        self, user_description: str, hierarchy: AccountHierarchy,
        bu_type: Optional[str] = None,
    ) -> List[Tuple[float, Account]]:
        """
        Ranks all Level 1–4 accounts by relevance to the user's description.

        Scoring factors (100 points total):
          25 pts — Keyword overlap between user description and account name
          20 pts — BU type is consistent with the majority in its section
          20 pts — FERC code is consistent with siblings
          15 pts — Account is at a deeper level (more specific parent is better)
          20 pts — Naming pattern similarity (word count, style)

        Only Level 1–4 accounts are candidates; Level-5 posting accounts cannot
        be parents of other posting accounts.

        Returns a list of (score, Account) sorted descending by score.
        """
        user_keywords = self._tokenize(user_description)
        # Hard-filter by BU type when known: IS entries only consider IS accounts,
        # BS entries only consider BS accounts.  When bu_type is unknown (None),
        # no filter is applied and all structural-level accounts remain as candidates.
        candidates = [
            a for a in hierarchy.accounts
            if a.line_of_detail < 5
            and (bu_type is None or not a.bu_type or a.bu_type == bu_type)
        ]

        scored = []
        for account in candidates:
            score = self._score_candidate(account, user_keywords, hierarchy, bu_type=bu_type)
            scored.append((score, account))

        # Sort descending by score, then by account_number for tie-breaking
        scored.sort(key=lambda x: (-x[0], x[1].account_number))
        return scored

    def _score_candidate(
        self,
        account: Account,
        user_keywords: set,
        hierarchy: AccountHierarchy,
        bu_type=None,
    ) -> float:
        """Computes the total score for a single parent candidate."""
        score = 0.0

        # --- Keyword overlap (25 pts) ---
        acct_keywords = self._tokenize(account.account_description)
        if acct_keywords or user_keywords:
            # Jaccard-style: intersection / union
            intersection = len(user_keywords & acct_keywords)
            union = len(user_keywords | acct_keywords)
            kw_ratio = intersection / union if union else 0
            score += W_KEYWORD * kw_ratio

            # Bonus: check if any user keyword appears as a substring in the name
            acct_lower = account.account_description.lower()
            for kw in user_keywords:
                if kw in acct_lower and len(kw) > 3:
                    score += 3  # Substring bonus (caps at W_KEYWORD naturally)

        # --- BU type consistency (20 pts) ---
        # If the user's BU type is known, use exact match (strong signal).
        # Otherwise fall back to global-majority heuristic (original behaviour).
        if bu_type is not None:
            if account.bu_type and account.bu_type == bu_type:
                score += W_BU_TYPE
        else:
            majority_bu_type = self._majority_bu_type(hierarchy)
            if account.bu_type and account.bu_type == majority_bu_type:
                score += W_BU_TYPE

        # --- FERC consistency (20 pts) ---
        # Award points based on how consistently this section uses FERC codes
        # (sections with uniform FERC codes are more informative suggestions)
        ferc_score = self._ferc_consistency_score(account, hierarchy)
        score += W_FERC * ferc_score

        # --- Level depth (15 pts) ---
        # Deeper levels are more specific. Level 4 is best (direct parent of L5).
        # level 1=worst, level 4=best for placing a Level-5 account
        level_score = (account.line_of_detail - 1) / 3  # maps 1→0, 4→1
        score += W_LEVEL * level_score

        # --- Naming pattern similarity (20 pts) ---
        naming_score = self._naming_pattern_score(account, user_keywords)
        score += W_NAMING * naming_score

        # Clamp to [0, 100]
        return round(max(0.0, min(100.0, score)), 1)

    def _tokenize(self, text: str) -> set:
        """Splits text into lowercase alpha tokens, filtering stop words."""
        stop_words = {
            "and", "or", "the", "for", "with", "from", "of", "to",
            "a", "an", "in", "on", "at", "by", "is", "are", "be",
            "not", "as", "up", "was", "were",
        }
        tokens = re.findall(r"[a-zA-Z]{2,}", text.lower())
        return {t for t in tokens if t not in stop_words}

    def _majority_bu_type(self, hierarchy: AccountHierarchy) -> str:
        """Returns the most common BU type across all accounts."""
        types = [a.bu_type for a in hierarchy.accounts if a.bu_type]
        if not types:
            return "BS"
        return Counter(types).most_common(1)[0][0]

    def _ferc_consistency_score(
        self, account: Account, hierarchy: AccountHierarchy
    ) -> float:
        """
        Returns 0.0–1.0 based on how consistent the FERC codes are among
        the children of this account.  High consistency → higher score
        (makes it a more meaningful suggestion target).
        """
        if not account.children:
            # No children yet; score based on whether account itself has a FERC code
            return 0.5 if account.ferc_code else 0.2

        ferc_codes = [c.ferc_code for c in account.children if c.ferc_code]
        if not ferc_codes:
            return 0.2

        most_common_count = Counter(ferc_codes).most_common(1)[0][1]
        return most_common_count / len(ferc_codes)

    def _naming_pattern_score(self, account: Account, user_keywords: set) -> float:
        """
        Returns 0.0–1.0 based on how similar the account's naming style is
        to the user's description (word count, noun style, etc.).
        """
        acct_words = account.account_description.split()
        user_words_count = len(user_keywords)
        acct_words_count = len(acct_words)

        # Prefer accounts with word counts similar to the user's description
        if user_words_count == 0 or acct_words_count == 0:
            return 0.0

        ratio = min(user_words_count, acct_words_count) / max(user_words_count, acct_words_count)
        return ratio

    # ------------------------------------------------------------------
    # 2. Safe Number Suggestion
    # ------------------------------------------------------------------

    def find_available_numbers_in_range(
        self, parent: Account, hierarchy: AccountHierarchy
    ) -> List[Tuple[int, str]]:
        """
        Returns up to 5 candidate account numbers within the parent's range.

        Each candidate is a (number, rationale) tuple where rationale is a
        short human-readable explanation (shown to the user in the menu).

        Strategy:
          A. last_child + dominant_spacing  (follows existing sibling pattern)
          B. ceil to nearest 100 after last child
          C. next unused multiple of 1000 in range
          D. first unused multiple of 100 in range (fallback)

        Constraints:
          - Number must be within [range_start, range_end] of the parent's range
          - Number must not already be in use
          - Number must not be the parent's own account_number
        """
        # Find the AccountRange for this parent
        parent_range = self._get_range_for_account(parent, hierarchy)
        if parent_range is None:
            return []  # Parent has no defined range (shouldn't happen for L1-4)

        range_start = parent_range.range_start
        range_end = parent_range.range_end
        used_numbers = set(hierarchy.accounts_by_number.keys())
        dominant_step = hierarchy.patterns.get("level_5_step", 100)

        # Find the last (highest-numbered) child of this parent
        child_numbers = sorted(
            [c.account_number for c in parent.children]
        )
        last_child = child_numbers[-1] if child_numbers else range_start

        candidates = []
        seen = set()

        def add_candidate(number: int, rationale: str):
            """Validates and adds a candidate if it's safe and not already listed."""
            if number in seen:
                return
            seen.add(number)
            if number <= 0 or number > 999999:
                return
            if not (range_start <= number <= range_end):
                return
            if number in used_numbers:
                return
            candidates.append((number, rationale))

        # Candidate D (promoted to first): earliest available 100-multiples near parent header
        # Scan from range_start upward in steps of 100. Show at most 3 before the
        # dominant-spacing option, so the user sees the "open space" closest to the header.
        near_parent_limit = 3
        near_parent_count = 0
        scan = self._ceil_to_multiple(range_start, 100)
        while scan <= range_end and near_parent_count < near_parent_limit:
            if scan not in used_numbers and scan != parent.account_number:
                add_candidate(
                    scan,
                    f"First unused 100-step in parent range {range_start}–{range_end}"
                )
                near_parent_count += 1
            scan += 100

        # Candidate A (demoted): dominant spacing after last sibling
        candidate_a = last_child + dominant_step
        add_candidate(
            candidate_a,
            f"+{dominant_step} after last sibling {last_child} (dominant spacing)"
        )

        # Candidate B: ceil to next multiple of 100 after last child
        candidate_b = self._ceil_to_multiple(last_child + 1, 100)
        add_candidate(candidate_b, f"Next round hundred after {last_child}")

        # Candidate C: next multiple of 1000 in range
        candidate_c = self._ceil_to_multiple(last_child + 1, 1000)
        add_candidate(candidate_c, "Next round thousand in range")

        # Limit to 5 candidates
        return candidates[:5]

    def validate_number_is_safe(
        self, proposed_number: int, hierarchy: AccountHierarchy
    ) -> Tuple[bool, str]:
        """
        Delegates to AccountValidator for the full 4-rule safety check.
        Exposed here so cli.py has a single placer reference.
        """
        return self._validator.validate_number_is_safe(proposed_number, hierarchy)

    # ------------------------------------------------------------------
    # Helper Methods
    # ------------------------------------------------------------------

    def _get_range_for_account(
        self, account: Account, hierarchy: AccountHierarchy
    ) -> 'AccountRange | None':
        """
        Finds the AccountRange owned by the given account.
        Returns None if the account has no range (Level-5 accounts).
        """
        for ar in hierarchy.ranges:
            if ar.owner_account.account_number == account.account_number:
                return ar
        return None

    @staticmethod
    def _ceil_to_multiple(n: int, multiple: int) -> int:
        """Returns the smallest multiple of 'multiple' that is >= n."""
        if multiple <= 0:
            return n
        return math.ceil(n / multiple) * multiple
