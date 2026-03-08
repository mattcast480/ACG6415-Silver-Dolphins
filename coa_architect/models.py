"""
models.py — Data structures for CoA Architect.

All modules in this package import from here. Define this file first
before implementing any other module.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Account:
    """
    Represents one row in the Chart of Accounts worksheet.

    Fields map directly to spreadsheet columns:
      A → account_id  (sequential row identifier)
      B → company
      C → business_unit
      D → bu_type        ("BS" = Balance Sheet, "IS" = Income Statement)
      E → account_number (6-digit integer)
      F → account_description
      G → posting_edit   (blank / B / L / I)
      H → line_of_detail (1–5; Level 5 = posting / leaf account)
      I → ferc_code
      J → asset_life     (months as string, e.g. "300", or None)
      K → book_tax_difference
      L → cash_flow_category

    parent and children are set by analyzer.build_hierarchy() after loading.
    """
    account_id: int
    company: str
    business_unit: str
    bu_type: str
    account_number: int
    account_description: str
    posting_edit: str
    line_of_detail: int
    ferc_code: str
    asset_life: Optional[str]
    book_tax_difference: Optional[str]
    cash_flow_category: Optional[str]
    # Relationships populated by the analyzer (not stored in Excel)
    parent: Optional['Account'] = field(default=None, repr=False, compare=False)
    children: list = field(default_factory=list, repr=False, compare=False)

    def ancestry_path(self) -> str:
        """
        Returns a human-readable path from the root down to this account.
        Example: 'ASSETS > Long-Term Assets > PP&E > Machinery and Equipment'
        """
        # Walk up to collect all ancestors, then reverse for top-down display
        ancestors = []
        node = self
        while node is not None:
            ancestors.append(node.account_description)
            node = node.parent
        ancestors.reverse()
        return " > ".join(ancestors)

    def __hash__(self):
        # Allow Account objects to be used in sets and as dict keys
        return hash(self.account_number)

    def __eq__(self, other):
        if not isinstance(other, Account):
            return False
        return self.account_number == other.account_number


@dataclass
class AccountRange:
    """
    Defines the inclusive number range owned by a header (non-Level-5) account.

    range_start = owner_account.account_number
    range_end   = (next account at same-or-higher level).account_number - 1
                  or 999999 if no such account exists.

    Any proposed new account number must fall within an AccountRange — never
    in a 'gap' between ranges.
    """
    owner_account: Account   # The header account that owns this range
    range_start: int         # Inclusive lower bound
    range_end: int           # Inclusive upper bound


@dataclass
class ReferenceData:
    """
    Lookup tables loaded from the reference sheets in the CoA workbook.

    Each dict maps a code string to its human-readable description.
    If a sheet is missing, the corresponding dict will be empty.
    """
    ferc_codes: dict          # {code_str: description}
    asset_life_codes: dict    # {months_str: description}
    cash_flow_codes: dict     # {code_str: description}
    posting_edit_codes: dict  # {code_str: description}
    book_tax_codes: dict      # {code_str: description}
    companies: dict           # {company_str: description}
    business_units: dict      # {bu_str: description}
    # Track which FERC codes came from an external file so the suggester
    # can label them differently (lower confidence)
    external_ferc_codes: set = field(default_factory=set)


@dataclass
class AccountHierarchy:
    """
    The fully-analyzed Chart of Accounts, ready for querying.

    Created by analyzer.CoAAnalyzer.analyze() and passed to all other modules.
    """
    accounts: list            # All Account objects sorted by account_number
    reference_data: ReferenceData
    ranges: list              # All AccountRange objects
    accounts_by_number: dict  # {account_number: Account} for O(1) lookup
    source_file_path: str     # Absolute path to the source Excel file
    column_mapping: dict      # {'account_number': 'E', 'ferc_code': 'I', ...}
    max_account_id: int       # Highest account_id value; new rows start at +1
    patterns: dict = field(default_factory=dict)  # Output of detect_number_patterns
    ferc_usage_map: dict = field(default_factory=dict)  # Output of build_ferc_usage_map


@dataclass
class NewAccountProposal:
    """
    Accumulates user choices during the interactive CLI session.

    All fields start as None and are filled in step-by-step.
    The 'reasoning' dict holds explanation strings shown to the user
    before they accept or modify each suggestion.
    """
    account_number: Optional[int] = None
    account_description: Optional[str] = None
    company: Optional[str] = None
    business_unit: Optional[str] = None
    bu_type: Optional[str] = None
    posting_edit: Optional[str] = None
    line_of_detail: Optional[int] = None   # Always 5 for posting accounts
    ferc_code: Optional[str] = None
    asset_life: Optional[str] = None
    book_tax_difference: Optional[str] = None
    cash_flow_category: Optional[str] = None
    suggested_parent: Optional[Account] = None
    # Maps field name → human-readable explanation of how the value was derived
    reasoning: dict = field(default_factory=dict)
