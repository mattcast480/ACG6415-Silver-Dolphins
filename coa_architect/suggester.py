"""
suggester.py — Suggests field values for a new account using evidence from the CoA.

CategorySuggester generates evidence-based recommendations for:
  - FERC code        (based on sibling accounts and description keywords)
  - Asset life       (keyword-driven lookup table)
  - Cash flow category (based on BU type and account type conventions)
  - Posting edit     (always blank for Level-5 accounts)
  - BU type          (inherited from the parent account)

All suggestions include a confidence percentage and a plain-English explanation
so the accountant can make an informed accept/modify/skip decision.
"""

import re
from collections import Counter
from typing import List, Optional, Tuple

from .models import Account, AccountHierarchy, NewAccountProposal


# ---------------------------------------------------------------------------
# Keyword → Asset Life mapping (months as strings matching reference data)
# ---------------------------------------------------------------------------
ASSET_LIFE_KEYWORDS = [
    # Each entry: (keywords_set, months_str, human_label)
    ({"land", "easement", "right-of-way", "right of way"}, "0", "Land — non-depreciable"),
    ({"software", "erp", "saas", "application", "system", "program", "license"}, "36", "Software (3 years)"),
    ({"computer", "laptop", "server", "workstation", "hardware", "it equipment"}, "60", "Computer equipment (5 years)"),
    ({"vehicle", "truck", "car", "fleet", "automobile", "trailer"}, "60", "Vehicle (5 years)"),
    ({"furniture", "fixture", "office equipment", "desk", "chair"}, "84", "Furniture & fixtures (7 years)"),
    ({"pipeline", "pipe", "transmission line", "distribution line", "main"}, "240", "Pipeline (20 years)"),
    ({"turbine", "generator", "wind", "turbogenerator", "rotor", "blade",
      "offshore", "onshore", "installation"}, "300", "Wind turbine / generator (25 years)"),
    ({"transmission", "substation", "transformer", "switchgear", "relay",
      "circuit breaker", "conductor"}, "360", "Transmission equipment (30 years)"),
    ({"building", "structure", "facility", "office building", "plant", "warehouse"}, "420", "Building / facility (35 years)"),
]

# ---------------------------------------------------------------------------
# Cash flow category inference rules
# ---------------------------------------------------------------------------
# BU type BS (Balance Sheet) → investing activities (INV) unless debt/equity
# BU type IS (Income Statement) → operating activities (OP)
CASH_FLOW_DEBT_EQUITY_KEYWORDS = {
    "debt", "loan", "bond", "note payable", "credit", "financing",
    "dividend", "equity", "stock", "capital", "retained earnings",
}


class CategorySuggester:
    """
    Generates evidence-based field suggestions for a new account proposal.
    """

    def suggest_ferc_code(
        self,
        proposal: NewAccountProposal,
        hierarchy: AccountHierarchy,
    ) -> List[Tuple[str, int, str]]:
        """
        Suggests FERC codes ranked by confidence.

        Returns list of (code, confidence_pct, explanation) sorted by confidence desc.

        Sources (in order of reliability):
          1. Sibling accounts under the same parent (highest confidence)
          2. Keyword match against the FERC usage map built from the entire CoA
          3. Section-level frequency (which codes are most common in this L1 section)
          4. External reference file codes (if loaded) — labeled as such, lower confidence
        """
        suggestions = {}  # code → (confidence, explanation)

        parent = proposal.suggested_parent
        description = (proposal.account_description or "").lower()
        desc_keywords = set(re.findall(r"[a-zA-Z]{3,}", description))

        # --- Source 1: Sibling accounts ---
        if parent and parent.children:
            sibling_fercs = [
                c.ferc_code for c in parent.children
                if c.ferc_code and str(c.ferc_code).strip()
            ]
            if sibling_fercs:
                code_counts = Counter(sibling_fercs)
                total_siblings = len(sibling_fercs)
                for code, count in code_counts.most_common(3):
                    pct = round((count / total_siblings) * 85)  # max 85% from siblings
                    desc = hierarchy.reference_data.ferc_codes.get(str(code), "")
                    explanation = (
                        f"{count} of {total_siblings} sibling accounts use FERC {code}"
                        + (f" — {desc}" if desc else "")
                    )
                    suggestions[str(code)] = (pct, explanation)

        # --- Source 2: Keyword match against FERC usage map ---
        if desc_keywords:
            for ferc_code, usage in hierarchy.ferc_usage_map.items():
                usage_keywords = usage.get("keywords", set())
                overlap = desc_keywords & usage_keywords
                if overlap:
                    # Confidence from keyword match: up to 75%
                    kw_confidence = min(75, len(overlap) * 20)
                    existing_conf, existing_expl = suggestions.get(ferc_code, (0, ""))
                    if kw_confidence > existing_conf:
                        desc = hierarchy.reference_data.ferc_codes.get(ferc_code, "")
                        explanation = (
                            f"Keyword match: '{', '.join(sorted(overlap))}' → FERC {ferc_code}"
                            + (f" — {desc}" if desc else "")
                        )
                        suggestions[ferc_code] = (kw_confidence, explanation)

        # --- Source 3: Section-level frequency ---
        if parent:
            # Find the Level-1 ancestor
            l1_ancestor = self._find_level1_ancestor(parent)
            if l1_ancestor:
                section_accounts = [
                    a for a in hierarchy.accounts
                    if a.account_number >= l1_ancestor.account_number
                    and a.ferc_code and str(a.ferc_code).strip()
                ]
                if section_accounts:
                    section_fercs = Counter(a.ferc_code for a in section_accounts)
                    for code, count in section_fercs.most_common(2):
                        if str(code) not in suggestions:
                            total = len(section_accounts)
                            pct = round((count / total) * 50)  # max 50% from section freq
                            desc = hierarchy.reference_data.ferc_codes.get(str(code), "")
                            explanation = (
                                f"Most frequent in this section ({count}/{total} accounts)"
                                + (f" — FERC {code}: {desc}" if desc else f" — FERC {code}")
                            )
                            suggestions[str(code)] = (pct, explanation)

        # --- Source 4: Advisory context (richer FERC code descriptions) ---
        # The advisory context dict maps code → richer description text from an
        # external reference (e.g., 18 CFR Part 101 PDF in 1.code_tables/).
        # We only suggest codes that already exist in the workbook's ferc_codes tab;
        # codes present only in the advisory file are silently ignored.
        advisory_ferc = hierarchy.advisory_context.get("FERC Code", {})
        if isinstance(advisory_ferc, dict) and desc_keywords:
            for adv_code, adv_desc in advisory_ferc.items():
                if adv_code in suggestions:
                    continue  # Already suggested with higher confidence
                if adv_code not in hierarchy.reference_data.ferc_codes:
                    continue  # Code not in workbook — do not suggest
                adv_keywords = set(re.findall(r"[a-zA-Z]{3,}", adv_desc.lower()))
                if desc_keywords & adv_keywords:
                    suggestions[adv_code] = (
                        30,
                        f"From advisory reference — FERC {adv_code}: {adv_desc}",
                    )

        # Sort by confidence descending, return top 5
        sorted_suggestions = sorted(
            [(code, conf, expl) for code, (conf, expl) in suggestions.items()],
            key=lambda x: -x[1],
        )
        return sorted_suggestions[:5]

    def suggest_asset_life(
        self,
        proposal: NewAccountProposal,
        hierarchy: AccountHierarchy,
    ) -> List[Tuple[str, str]]:
        """
        Suggests asset life values based on keywords in the account description.

        Returns list of (months_str, explanation) sorted by confidence.

        Also checks sibling accounts for the most common asset life in use.
        """
        description = (proposal.account_description or "").lower()
        results = []

        # --- Step 1: Advisory context (PDF) — PRIMARY source ---
        # The asset life PDF is authoritative for this organization's depreciation schedule.
        # We check the PDF-extracted table first so it takes precedence over the hardcoded
        # keyword table.  Each entry in advisory_life maps a month code (str) to a
        # concatenated description of all assets assigned that life.
        advisory_life = hierarchy.advisory_context.get("Asset Life", {})
        if isinstance(advisory_life, dict) and description:
            desc_words = set(re.findall(r"[a-zA-Z]{3,}", description))

            # Collect all matches with their overlap count so we can rank by specificity.
            # Without sorting, a code like "0" (Transmission Rights) could beat "300"
            # (Transmission Lines) simply because it appears first in the dict — even
            # though "300" shares more words with the user's description.
            advisory_matches = []
            for adv_code, adv_desc in advisory_life.items():
                if any(r[0] == adv_code for r in results):
                    continue  # Already suggested (shouldn't happen here, but defensive)
                adv_keywords = set(re.findall(r"[a-zA-Z]{3,}", adv_desc.lower()))
                overlap = desc_words & adv_keywords
                if overlap:
                    ref_desc = hierarchy.reference_data.asset_life_codes.get(
                        adv_code, f"{adv_code} months"
                    )
                    advisory_matches.append((
                        len(overlap),
                        adv_code,
                        f"Advisory reference suggests {adv_code} months ({ref_desc})"
                    ))

            # Sort descending by overlap count — most specific match comes first.
            advisory_matches.sort(key=lambda x: -x[0])
            for _, adv_code, explanation in advisory_matches:
                results.append((adv_code, explanation))

        # --- Step 2: Hardcoded keyword table — FALLBACK (only when PDF produced nothing) ---
        # The keyword table is only consulted when the advisory context is empty or produced
        # no matches.  This prevents keyword entries from overriding the authoritative PDF.
        if not results:
            for keywords, months, label in ASSET_LIFE_KEYWORDS:
                for kw in keywords:
                    if kw in description:
                        # Retrieve the human-readable label from reference data if available
                        ref_desc = hierarchy.reference_data.asset_life_codes.get(months, label)
                        results.append((months, f"Keyword '{kw}' suggests {label} ({months} months)"))
                        break  # Only add each asset life bucket once

        # --- Sibling accounts ---
        parent = proposal.suggested_parent
        if parent and parent.children:
            sibling_lives = [
                c.asset_life for c in parent.children
                if c.asset_life and str(c.asset_life).strip()
            ]
            if sibling_lives:
                most_common_life = Counter(sibling_lives).most_common(1)[0][0]
                if not any(r[0] == most_common_life for r in results):
                    count = sibling_lives.count(most_common_life)
                    ref_desc = hierarchy.reference_data.asset_life_codes.get(
                        most_common_life, f"{most_common_life} months"
                    )
                    # Append (not insert at 0) so PDF/keyword suggestions keep top rank;
                    # sibling is still top suggestion when no other match was found.
                    results.append(
                        (most_common_life, f"{count} sibling(s) use {most_common_life} months ({ref_desc})")
                    )

        return results[:3]

    def suggest_cash_flow_category(
        self,
        proposal: NewAccountProposal,
        hierarchy: AccountHierarchy,
    ) -> List[Tuple[str, str]]:
        """
        Suggests a cash flow category based on BU type and account description.

        Rules:
          - IS (Income Statement) accounts → OP (Operating Activities)
          - BS (Balance Sheet) accounts:
              - Debt/equity keywords → FIN (Financing Activities)
              - Default → INV (Investing Activities)
          - Many accounts have no cash flow classification (returns empty list)
        """
        bu_type = proposal.bu_type or (
            proposal.suggested_parent.bu_type if proposal.suggested_parent else ""
        )
        description = (proposal.account_description or "").lower()

        # Check for debt/equity keywords first
        desc_words = set(description.split())
        is_debt_equity = bool(desc_words & CASH_FLOW_DEBT_EQUITY_KEYWORDS)

        suggestions = []

        if bu_type == "IS":
            code = "OP"
            desc = hierarchy.reference_data.cash_flow_codes.get("OP", "Operating Activities")
            suggestions.append((code, f"Income Statement account → {desc}"))
        elif bu_type == "BS":
            if is_debt_equity:
                code = "FIN"
                desc = hierarchy.reference_data.cash_flow_codes.get("FIN", "Financing Activities")
                suggestions.append((code, f"Debt/equity keyword in description → {desc}"))
            else:
                code = "INV"
                desc = hierarchy.reference_data.cash_flow_codes.get("INV", "Investing Activities")
                suggestions.append((code, f"Balance Sheet asset account → {desc}"))

        # --- Advisory context: keyword-based augmentation ---
        # The advisory file for 'Cash Flow Category' may map codes to richer descriptions
        # that help identify the right category for accounts not covered by the rule set above.
        advisory_cf = hierarchy.advisory_context.get("Cash Flow Category", {})
        if isinstance(advisory_cf, dict) and description:
            desc_words_adv = set(re.findall(r"[a-zA-Z]{3,}", description))
            for adv_code, adv_desc in advisory_cf.items():
                if any(s[0] == adv_code for s in suggestions):
                    continue  # Already suggested by rule-based logic
                if adv_code not in hierarchy.reference_data.cash_flow_codes:
                    continue  # Code not in workbook — do not suggest
                adv_keywords = set(re.findall(r"[a-zA-Z]{3,}", adv_desc.lower()))
                if desc_words_adv & adv_keywords:
                    cf_desc = hierarchy.reference_data.cash_flow_codes.get(adv_code, adv_code)
                    suggestions.append(
                        (adv_code, f"Advisory reference: {adv_code} — {cf_desc}")
                    )

        # Also check sibling cash flow codes
        parent = proposal.suggested_parent
        if parent and parent.children:
            sibling_cfs = [
                c.cash_flow_category for c in parent.children
                if c.cash_flow_category and str(c.cash_flow_category).strip()
            ]
            if sibling_cfs:
                most_common = Counter(sibling_cfs).most_common(1)[0][0]
                if not any(s[0] == most_common for s in suggestions):
                    ref_desc = hierarchy.reference_data.cash_flow_codes.get(most_common, most_common)
                    suggestions.insert(0, (most_common, f"Sibling accounts use '{most_common}' — {ref_desc}"))

        return suggestions[:3]

    def suggest_posting_edit(
        self,
        proposal: NewAccountProposal,
        target_level: int = 5,
    ) -> Tuple[str, str]:
        """
        Suggests the posting edit code.

        For Level-5 (posting/leaf) accounts: always blank.
        For header accounts: B (Balance), L (Ledger), I (Individual) may apply.
        """
        if target_level == 5:
            return ("", "All Level-5 posting accounts use blank posting edit.")
        return ("", "Posting edit is typically blank for new accounts.")

    def suggest_book_tax_difference(
        self,
        proposal: NewAccountProposal,
        hierarchy: AccountHierarchy,
    ) -> Tuple[Optional[str], int, str]:
        """
        Suggests a book-tax difference code using keyword matching against
        the advisory CSV loaded from 1.code_tables/Book-Tax Difference.csv.

        The CSV maps codes (e.g. L274, T+, P-) to description text that includes
        example account names.  We tokenize both the new account's description and
        each advisory entry, then rank by the number of overlapping keywords.

        Returns (code, confidence_pct, reasoning).
          - code: best-matching code string, or None if no match
          - confidence_pct: capped at 40 % (book-tax is judgment-driven)
          - reasoning: explanation shown to the user
        """
        # Pull the advisory context loaded from the CSV
        advisory_btd = hierarchy.advisory_context.get("Book-Tax Difference", {})

        if not isinstance(advisory_btd, dict) or not advisory_btd:
            # No advisory file loaded — fall back to manual review message
            return None, 0, "Review with tax team — no automatic suggestion."

        description = proposal.account_description or ""
        if not description.strip():
            return None, 0, "Review with tax team — no automatic suggestion."

        # Tokenize the account description: extract words of 3+ letters, lowercased.
        # Short words (a, of, to…) rarely carry semantic meaning, so we skip them.
        desc_words = set(re.findall(r"[a-zA-Z]{3,}", description.lower()))

        # Score each advisory code by counting keyword overlaps with its description.
        matches = []
        for code, adv_desc in advisory_btd.items():
            adv_keywords = set(re.findall(r"[a-zA-Z]{3,}", adv_desc.lower()))
            overlap = desc_words & adv_keywords
            if overlap:
                matches.append((len(overlap), code, sorted(overlap)))

        if not matches:
            return None, 0, "Review with tax team — no automatic suggestion."

        # Sort descending by overlap count; most specific match wins
        matches.sort(key=lambda x: -x[0])
        best_overlap_count, best_code, matched_words = matches[0]

        # Confidence scales with overlap count but is capped at 40 %
        # (book-tax difference requires professional judgment; we never claim certainty)
        confidence = min(10 * best_overlap_count, 40)
        reasoning = (
            f"[{confidence}%] Advisory reference suggests {best_code} — "
            f"matched keyword(s): {', '.join(matched_words)}"
        )
        return best_code, confidence, reasoning

    def suggest_bu_type(
        self,
        proposal: NewAccountProposal,
        parent: Optional[Account],
    ) -> Tuple[str, str]:
        """
        Suggests BU type by inheriting from the parent account.

        BU type is always inherited — a new posting account under a Balance
        Sheet parent is always a Balance Sheet account.
        """
        if parent and parent.bu_type:
            type_name = {
                "BS": "Balance Sheet",
                "IS": "Income Statement",
            }.get(parent.bu_type, parent.bu_type)
            return (
                parent.bu_type,
                f"Inherited from parent '{parent.account_description}' ({type_name})",
            )
        return ("BS", "Default: Balance Sheet (no parent BU type found)")

    def suggest_company(
        self,
        proposal: NewAccountProposal,
        hierarchy: AccountHierarchy,
    ) -> Tuple[str, str]:
        """
        Suggests a company code.  If all accounts use one company, that's obvious.
        """
        companies = [a.company for a in hierarchy.accounts if a.company]
        if not companies:
            return ("", "No company information found in the CoA.")

        company_counts = Counter(companies)
        most_common_company, count = company_counts.most_common(1)[0]
        total = len(companies)
        pct = round(count / total * 100)
        desc = hierarchy.reference_data.companies.get(most_common_company, "")
        label = f"{most_common_company}" + (f" — {desc}" if desc else "")
        return (
            most_common_company,
            f"{pct}% of accounts ({count}/{total}) use company {label}",
        )

    def suggest_business_unit(
        self,
        proposal: NewAccountProposal,
        parent: Optional[Account],
        hierarchy: AccountHierarchy,
    ) -> Tuple[str, str]:
        """
        Suggests a business unit code.  Inherits from parent if available.
        """
        if parent and parent.business_unit:
            desc = hierarchy.reference_data.business_units.get(parent.business_unit, "")
            label = parent.business_unit + (f" — {desc}" if desc else "")
            return (
                parent.business_unit,
                f"Inherited from parent '{parent.account_description}' (BU {label})",
            )

        # Fallback: most common BU in the CoA
        bus = [a.business_unit for a in hierarchy.accounts if a.business_unit]
        if bus:
            most_common, count = Counter(bus).most_common(1)[0]
            desc = hierarchy.reference_data.business_units.get(most_common, "")
            return (
                most_common,
                f"Most common business unit in CoA ({count} accounts) — {desc}",
            )
        return ("", "No business unit information found in the CoA.")

    def suggest_all(
        self,
        proposal: NewAccountProposal,
        hierarchy: AccountHierarchy,
    ) -> NewAccountProposal:
        """
        Populates all suggestion fields on the proposal in one call.

        Sets .reasoning for each field with a human-readable explanation.
        Returns the enriched proposal (mutates in place and also returns it).
        """
        parent = proposal.suggested_parent

        # BU type — inherit from parent
        bu_type, bu_reasoning = self.suggest_bu_type(proposal, parent)
        if proposal.bu_type is None:
            proposal.bu_type = bu_type
            proposal.reasoning["bu_type"] = bu_reasoning
        elif "bu_type" not in proposal.reasoning:
            proposal.reasoning["bu_type"] = bu_reasoning

        # Company — use most common
        company, co_reasoning = self.suggest_company(proposal, hierarchy)
        if proposal.company is None:
            proposal.company = company
            proposal.reasoning["company"] = co_reasoning
        elif "company" not in proposal.reasoning:
            proposal.reasoning["company"] = co_reasoning

        # Business unit — inherit from parent
        bu, bu_unit_reasoning = self.suggest_business_unit(proposal, parent, hierarchy)
        if proposal.business_unit is None:
            proposal.business_unit = bu
            proposal.reasoning["business_unit"] = bu_unit_reasoning
        elif "business_unit" not in proposal.reasoning:
            proposal.reasoning["business_unit"] = bu_unit_reasoning

        # Posting edit — always blank for L5
        pe_code, pe_reasoning = self.suggest_posting_edit(proposal, target_level=5)
        if proposal.posting_edit is None:
            proposal.posting_edit = pe_code
        proposal.reasoning["posting_edit"] = pe_reasoning

        # Line of detail — always 5 for posting accounts
        if proposal.line_of_detail is None:
            proposal.line_of_detail = 5
        proposal.reasoning["line_of_detail"] = "New posting accounts are always Level 5."

        # FERC code
        ferc_suggestions = self.suggest_ferc_code(proposal, hierarchy)
        if ferc_suggestions:
            top_code, top_conf, top_expl = ferc_suggestions[0]
            if proposal.ferc_code is None:
                proposal.ferc_code = top_code
            proposal.reasoning["ferc_code"] = f"[{top_conf}%] {top_expl}"
        else:
            proposal.reasoning["ferc_code"] = "No FERC code suggestion — review manually."

        # Asset life
        life_suggestions = self.suggest_asset_life(proposal, hierarchy)
        if life_suggestions:
            top_life, top_life_expl = life_suggestions[0]
            if proposal.asset_life is None:
                proposal.asset_life = top_life
            proposal.reasoning["asset_life"] = top_life_expl
        else:
            proposal.reasoning["asset_life"] = "No asset life suggestion — review manually."

        # Cash flow category
        cf_suggestions = self.suggest_cash_flow_category(proposal, hierarchy)
        if cf_suggestions:
            top_cf, top_cf_expl = cf_suggestions[0]
            if proposal.cash_flow_category is None:
                proposal.cash_flow_category = top_cf
            proposal.reasoning["cash_flow_category"] = top_cf_expl
        else:
            proposal.reasoning["cash_flow_category"] = "No cash flow category suggested (leave blank)."

        # Book-tax difference — suggest using advisory CSV keyword matching
        btd_code, _btd_conf, btd_reasoning = self.suggest_book_tax_difference(proposal, hierarchy)
        if btd_code is not None and proposal.book_tax_difference is None:
            proposal.book_tax_difference = btd_code
        proposal.reasoning["book_tax_difference"] = btd_reasoning

        return proposal

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _find_level1_ancestor(self, account: Account) -> Optional[Account]:
        """Walks up the parent chain to find the Level-1 ancestor."""
        node = account
        while node is not None:
            if node.line_of_detail == 1:
                return node
            node = node.parent
        return None
