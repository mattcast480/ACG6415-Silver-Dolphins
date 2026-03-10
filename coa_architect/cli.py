"""
cli.py — Interactive terminal UI for CoA Architect.

CoAArchitectCLI orchestrates the full user session using standard
print() and input() calls, compatible with any Python environment
including Spyder 6 and IPython consoles.

Session flow:
  1. Welcome screen
  2. Load + analyze the CoA file (path from CLI args or prompted)
  3. Display hierarchy summary
  4. Loop:
     a. Describe new account (plain English)
     b. Select parent account from ranked candidates
     c. Select account number from safe candidates
     d. Review and confirm/modify each field suggestion
     e. Final confirmation → export OR restart
     f. "Add another?" prompt
"""

import os
import shutil
import sys
from collections import Counter
from typing import Optional

from .models import Account, AccountHierarchy, NewAccountProposal
from .loader import CoALoader
from .analyzer import CoAAnalyzer
from .placer import AccountPlacer
from .suggester import CategorySuggester
from .validator import AccountValidator
from .exporter import CoAExporter

VERSION = "1.0"


class CoAArchitectCLI:
    """
    Interactive terminal session for safely adding a new GL account to the CoA.
    """

    def __init__(self, file_path: Optional[str] = None, ferc_ref_path: Optional[str] = None):
        self.file_path = file_path
        self.ferc_ref_path = ferc_ref_path
        self.hierarchy: Optional[AccountHierarchy] = None
        self.workbook = None
        self._loader = CoALoader()
        self._analyzer = CoAAnalyzer()
        self._placer = AccountPlacer()
        self._suggester = CategorySuggester()
        self._validator = AccountValidator()
        self._exporter = CoAExporter()

    # ------------------------------------------------------------------
    # Private UI helpers
    # ------------------------------------------------------------------

    def _pick(self, prompt: str, choices: list, allow_cancel: bool = True):
        """
        Displays a numbered menu and returns the value of the chosen item.

        choices: list of (label, value) tuples.
        If allow_cancel is True, a cancel option returning None is appended.
        Loops until the user enters a valid number.
        """
        # Build the full list, optionally adding a cancel entry at the end
        full_choices = list(choices)
        if allow_cancel:
            full_choices.append(("(cancel)", None))

        # Print the numbered menu
        print()
        for i, (label, _) in enumerate(full_choices, start=1):
            print(f"  {i}. {label}")

        # Keep asking until a valid number is entered
        while True:
            raw = input(f"{prompt} [1-{len(full_choices)}]: ").strip()
            try:
                index = int(raw)
                if 1 <= index <= len(full_choices):
                    return full_choices[index - 1][1]
                else:
                    print(f"  Please enter a number between 1 and {len(full_choices)}.")
            except ValueError:
                print("  Please enter a number.")

    def _ask_yes_no(self, prompt: str, default: bool = True) -> bool:
        """
        Prints a yes/no prompt and returns True for yes, False for no.

        default=True  → displays [Y/n]
        default=False → displays [y/N]
        Pressing Enter without input accepts the default.
        """
        hint = "[Y/n]" if default else "[y/N]"
        while True:
            raw = input(f"{prompt} {hint}: ").strip().lower()
            if raw == "":
                return default
            if raw in ("y", "yes"):
                return True
            if raw in ("n", "no"):
                return False
            print("  Please enter y or n.")

    def _copy_and_name_modified_file(self, original_path: str) -> str:
        """
        Prompts the user for a name for the working copy of the CoA file,
        validates that the name contains no illegal filename characters, copies
        the original file to that name in the same directory, and returns the
        full path to the copy.
        """
        # Characters that are illegal in Windows (and most OS) file names
        INVALID_CHARS = {'\\', '/', ':', '*', '?', '"', '<', '>', '|'}

        while True:
            new_name = input(
                "\nWhat would you like to name your modified Chart of Accounts?"
                " (Do not include the file extension): "
            ).strip()

            if not new_name:
                print("  Name cannot be empty. Please try again.")
                continue

            # Find any illegal characters the user typed
            bad_chars = sorted(c for c in INVALID_CHARS if c in new_name)
            if bad_chars:
                bad_str = "  ".join(bad_chars)
                print(f"  The following characters are not allowed in file names: {bad_str}")
                print("  Please try again.")
                continue

            break  # Name is valid

        # Build the destination path: same folder as original, new name, same extension
        directory = os.path.dirname(original_path)
        _, ext = os.path.splitext(original_path)
        Modified_CoA_Path = os.path.join(directory, new_name + ext)  # Modified CoA Path

        # Copy the original file — original is never touched again after this point
        shutil.copy2(original_path, Modified_CoA_Path)
        print(f"Working copy created: {Modified_CoA_Path}")

        # Push into Spyder/IPython Variable Explorer so it is visible after the run
        try:
            get_ipython().user_ns["Modified_CoA_Path"] = Modified_CoA_Path
        except (NameError, AttributeError):
            pass  # Not running in IPython — skip silently

        return Modified_CoA_Path

    # ------------------------------------------------------------------
    # Main Entry Point
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Runs the full interactive session."""
        self._show_welcome()
        self._load_and_analyze()
        self._show_hierarchy_summary()

        while True:
            proposal = self._add_account_session()
            if proposal is None:
                break  # User typed 'quit' or cancelled

            add_another = self._ask_yes_no("Add another account?", default=False)
            if not add_another:
                break

        print("\nSession complete. Goodbye!")

    # ------------------------------------------------------------------
    # Step 1: Welcome Screen
    # ------------------------------------------------------------------

    def _show_welcome(self) -> None:
        """Displays the app name and version as a plain-text banner."""
        print("=" * 55)
        print(f"  CoA Architect v{VERSION}")
        print("  Safe Chart of Accounts extension tool")
        print("  Silver Dolphins LLP")
        print("=" * 55)

    # ------------------------------------------------------------------
    # Step 2: Load + Analyze
    # ------------------------------------------------------------------

    def _load_and_analyze(self) -> None:
        """
        Prompts for the CoA file path if not already provided, then loads
        and analyzes it.  Also loads an optional external FERC reference file.
        """
        # Prompt for CoA file path if not provided via CLI arg
        if not self.file_path:
            self.file_path = input("\nCoA Excel file path: ").strip()
            if not self.file_path:
                print("No file path provided. Exiting.")
                sys.exit(1)

        Original_CoA_Path = str(self.file_path)  # Original CoA Path — plain text string
        # Push into Spyder/IPython Variable Explorer so it is visible after the run
        try:
            get_ipython().user_ns["Original_CoA_Path"] = Original_CoA_Path
        except (NameError, AttributeError):
            pass  # Not running in IPython — skip silently

        # Create the working copy — all reads and writes use this file, not the original
        Modified_CoA_Path = self._copy_and_name_modified_file(Original_CoA_Path)  # Modified CoA Path
        self.file_path = Modified_CoA_Path  # Redirect all downstream I/O to the copy

        # Auto-detect the bundled FERC reference CSV if it exists alongside the app.
        # The CSV lives at resources/ferc_uniform_system.csv relative to the repo root.
        # We look for it relative to this source file (coa_architect/cli.py → ../resources/).
        _module_dir = os.path.dirname(os.path.abspath(__file__))
        _default_ferc_csv = os.path.join(_module_dir, "..", "resources", "ferc_uniform_system.csv")
        _default_ferc_csv = os.path.normpath(_default_ferc_csv)

        if self.ferc_ref_path is None and os.path.exists(_default_ferc_csv):
            # Silently pre-load the bundled CSV; the user can still override via --ferc-ref
            self.ferc_ref_path = _default_ferc_csv
            print(f"Auto-detected FERC reference: {_default_ferc_csv}")

        # If no auto-detected file was found, offer to load one manually
        if self.ferc_ref_path is None:
            load_ferc = self._ask_yes_no(
                "Load an external FERC reference file? (optional)", default=False
            )
            if load_ferc:
                self.ferc_ref_path = input(
                    "External FERC file path (CSV or Excel): "
                ).strip()

        print(f"\nCoA file:   {self.file_path}")
        print(f"FERC ref:   {self.ferc_ref_path or '(none)'}\n")

        # Load the workbook
        print("Loading workbook...")
        accounts, reference_data, column_mapping, workbook = (
            self._loader.load_chart_of_accounts(self.file_path)
        )
        self.workbook = workbook

        # Merge external FERC codes if provided
        if self.ferc_ref_path:
            print("Loading external FERC codes...")
            try:
                external_codes = self._loader.load_external_ferc_file(self.ferc_ref_path)
                # CoA-embedded codes take precedence over external file
                new_external = set()
                for code, desc in external_codes.items():
                    if code not in reference_data.ferc_codes:
                        reference_data.ferc_codes[code] = desc
                        new_external.add(code)
                reference_data.external_ferc_codes = new_external
                print(f"Loaded {len(new_external)} new FERC codes from external file.")
            except Exception as e:
                print(f"Warning: Could not load external FERC file: {e}")

        # Build the hierarchy
        print("Analyzing hierarchy...")
        self.hierarchy = self._analyzer.analyze(
            accounts, reference_data, column_mapping, self.file_path
        )

        # Show column mapping for user confirmation
        self._show_column_mapping(column_mapping)

    def _show_column_mapping(self, column_mapping: dict) -> None:
        """Displays the detected column mapping as an aligned plain-text table."""
        print("\nDetected Column Mapping")
        print("-" * 35)
        for field, col_letter in sorted(column_mapping.items()):
            print(f"  {field:<25} {col_letter or '(not found)'}")
        print()

    # ------------------------------------------------------------------
    # Step 3: Hierarchy Summary
    # ------------------------------------------------------------------

    def _show_hierarchy_summary(self) -> None:
        """Displays a summary table: level counts and section breakdown."""
        accounts = self.hierarchy.accounts
        level_counts = Counter(a.line_of_detail for a in accounts)

        level_summary = "  ".join(
            f"L{level}×{count}" for level, count in sorted(level_counts.items())
        )

        print(
            f"Loaded {len(accounts)} accounts across "
            f"{len([a for a in accounts if a.line_of_detail == 1])} sections."
        )
        print(f"Hierarchy: {level_summary}\n")

        # Section breakdown table
        print("Sections")
        print(f"  {'Account #':<12} {'Description':<40} Children")
        print("-" * 65)

        level1 = [a for a in accounts if a.line_of_detail == 1]
        for section in sorted(level1, key=lambda a: a.account_number):
            child_count = sum(
                1 for a in accounts
                if a.parent
                and self._find_level1_ancestor(a)
                and self._find_level1_ancestor(a).account_number == section.account_number
            )
            print(
                f"  {str(section.account_number):<12} "
                f"{section.account_description:<40} "
                f"{child_count}"
            )
        print()

    # ------------------------------------------------------------------
    # Step 4: Add Account Session (one account per loop iteration)
    # ------------------------------------------------------------------

    def _add_account_session(self) -> Optional[NewAccountProposal]:
        """
        Runs one complete account-addition interaction.
        Returns the completed proposal on success, or None if the user quits.
        """
        # a. Describe the new account in plain English
        description = input(
            "\nDescribe the new account in plain English (or type 'quit' to exit): "
        ).strip()

        if not description or description.lower() == "quit":
            return None

        proposal = NewAccountProposal(account_description=description)

        # b. Select business unit — infers and confirms company + BU type
        bu_code, company_code, bu_type = self._select_business_unit()
        if bu_code is None:
            return None

        # Store confirmed BU fields on the proposal now, before parent scoring
        proposal.business_unit = bu_code
        proposal.company = company_code
        proposal.bu_type = bu_type
        proposal.reasoning["business_unit"] = f"Selected by user: {bu_code}"
        proposal.reasoning["company"] = f"Matched from BU {bu_code}, confirmed by user"
        proposal.reasoning["bu_type"] = f"Matched from BU {bu_code}, confirmed by user"

        # c. Select parent account — pass bu_type for stronger scoring
        parent = self._select_parent(description, proposal, bu_type=bu_type)
        if parent is None:
            return None
        proposal.suggested_parent = parent

        # Populate account_description from input if not set
        proposal.account_description = proposal.account_description or description

        # d. Select account number
        number = self._select_account_number(parent, proposal)
        if number is None:
            return None
        proposal.account_number = number

        # e. Auto-suggest all fields, then confirm each one
        print("Generating suggestions...")
        self._suggester.suggest_all(proposal, self.hierarchy)

        proposal = self._confirm_fields(proposal)

        # f. Show final summary
        self._show_final_proposal(proposal)

        # g. Confirm and export to file
        confirmed = self._ask_yes_no("Add to CoA and save?", default=True)

        if confirmed:
            print("Saving...")
            saved_path = self._exporter.export(proposal, self.hierarchy, self.workbook)
            print(
                f"\nAccount {proposal.account_number} — "
                f"'{proposal.account_description}' added. File saved."
            )
            print(f"Saved to: {saved_path}\n")
            return proposal
        else:
            print("Cancelled — file not changed.\n")
            return None

    def _select_parent(
        self, description: str, proposal: NewAccountProposal,
        bu_type: Optional[str] = None,
    ) -> Optional[Account]:
        """
        Scores all Level 1–4 accounts and presents the top 5 for selection.
        Returns the chosen parent Account, or None if user cancels.
        """
        scored = self._placer.score_parent_candidates(
            description, self.hierarchy, bu_type=bu_type
        )

        if not scored:
            print("No eligible parent accounts found.")
            return None

        # Build choices from the top 5 scored candidates
        top5 = scored[:5]

        print("\nTop parent candidates:")
        choices = []
        for score, account in top5:
            ancestry = account.ancestry_path()
            label = (
                f"[{score:.0f}%] {account.account_number} — "
                f"{account.account_description}\n"
                f"         {ancestry}"
            )
            choices.append((label, account))

        # Let the user request the full list if none of the top 5 fit
        choices.append(("(show more / search manually)", "more"))

        selected = self._pick("Select parent account", choices, allow_cancel=True)

        if selected == "more":
            return self._select_parent_from_all(scored)
        return selected

    def _select_parent_from_all(self, scored: list) -> Optional[Account]:
        """Shows all scored candidates when user requests 'show more'."""
        choices = [
            (
                f"[{score:.0f}%] {account.account_number} — "
                f"{account.account_description} | {account.ancestry_path()}",
                account,
            )
            for score, account in scored
        ]
        return self._pick("Select parent account", choices, allow_cancel=True)

    def _select_account_number(
        self, parent: Account, proposal: NewAccountProposal
    ) -> Optional[int]:
        """
        Finds safe candidate numbers and presents them for selection.
        Also allows free-text entry with validation.
        Returns the chosen number, or None if cancelled.
        """
        candidates = self._placer.find_available_numbers_in_range(parent, self.hierarchy)

        # Find the parent's range for display context
        parent_range = next(
            (r for r in self.hierarchy.ranges
             if r.owner_account.account_number == parent.account_number),
            None,
        )
        range_str = (
            f"{parent_range.range_start}–{parent_range.range_end}"
            if parent_range else "unknown range"
        )
        last_child = (
            max(c.account_number for c in parent.children)
            if parent.children else parent.account_number
        )

        print(
            f"\nSuggested numbers "
            f"(range {range_str}, last sibling: {last_child}):"
        )

        choices = [
            (f"{number}  ({rationale})", number)
            for number, rationale in candidates
        ]
        choices.append(("Enter a custom number", "custom"))

        selected = self._pick("Select account number", choices, allow_cancel=True)

        if selected == "custom":
            return self._prompt_custom_number()
        return selected

    def _prompt_custom_number(self) -> Optional[int]:
        """Prompts the user to enter a custom account number with validation."""
        while True:
            raw = input("Enter a 6-digit account number (or blank to cancel): ").strip()
            if not raw:
                return None
            try:
                n = int(raw)
            except ValueError:
                print("  Please enter a 6-digit integer.")
                continue
            # Validate against existing hierarchy rules
            ok, msg = self._validator.validate_account_number(n, self.hierarchy)
            if not ok:
                print(f"  {msg}")
                continue
            return n

    # ------------------------------------------------------------------
    # Step d: Field-by-field confirmation
    # ------------------------------------------------------------------

    def _confirm_fields(self, proposal: NewAccountProposal) -> NewAccountProposal:
        """
        Steps the user through each suggested field value.
        For each field, the user can: Accept / Modify / (Clear if allowed).
        """
        print("\nConfirming fields:")

        # Description — always prompt for review
        proposal.account_description = self._confirm_text_field(
            "Description",
            proposal.account_description,
            "Derived from your plain-English input.",
        )

        # Company — already confirmed if set during BU selection
        if proposal.company is None:
            proposal.company = self._confirm_text_field(
                "Company",
                proposal.company,
                proposal.reasoning.get("company", ""),
            )
        else:
            desc = self.hierarchy.reference_data.companies.get(proposal.company, "")
            label = proposal.company + (f" — {desc}" if desc else "")
            print(f"\n  Company: {label}  (confirmed earlier)")

        # Business Unit — already confirmed if set during BU selection
        if proposal.business_unit is None:
            proposal.business_unit = self._confirm_text_field(
                "Business Unit",
                proposal.business_unit,
                proposal.reasoning.get("business_unit", ""),
            )
        else:
            desc = self.hierarchy.reference_data.business_units.get(
                proposal.business_unit, ""
            )
            label = proposal.business_unit + (f" — {desc}" if desc else "")
            print(f"\n  Business Unit: {label}  (confirmed earlier)")

        # BU Type — already confirmed if set during BU selection
        if proposal.bu_type is None:
            proposal.bu_type = self._confirm_choice_field(
                "BU Type",
                proposal.bu_type,
                ["BS", "IS"],
                proposal.reasoning.get("bu_type", ""),
            )
        else:
            type_name = {
                "BS": "Balance Sheet", "IS": "Income Statement"
            }.get(proposal.bu_type, proposal.bu_type)
            print(f"\n  BU Type: {proposal.bu_type} ({type_name})  (confirmed earlier)")

        # Posting Edit — usually blank for Level-5 posting accounts
        proposal.posting_edit = self._confirm_text_field(
            "Posting Edit",
            proposal.posting_edit,
            proposal.reasoning.get("posting_edit", ""),
            allow_blank=True,
        )

        # Line of Detail — always 5 for new posting accounts
        print(
            f"  Line of Detail: 5  "
            f"({proposal.reasoning.get('line_of_detail', 'Posting account')})"
        )
        proposal.line_of_detail = 5

        # FERC Code — pick from suggestions or enter custom
        ferc_suggestions = self._suggester.suggest_ferc_code(proposal, self.hierarchy)
        proposal.ferc_code = self._confirm_code_field(
            "FERC Code",
            proposal.ferc_code,
            ferc_suggestions,
            proposal.reasoning.get("ferc_code", ""),
            self.hierarchy.reference_data.ferc_codes,
        )

        # Asset Life — pick from suggestions or enter custom
        life_suggestions = self._suggester.suggest_asset_life(proposal, self.hierarchy)
        life_choices = [(v, e) for v, e in life_suggestions]
        proposal.asset_life = self._confirm_code_field(
            "Asset Life",
            proposal.asset_life,
            [(v, 0, e) for v, e in life_choices],  # confidence pct not used here
            proposal.reasoning.get("asset_life", ""),
            self.hierarchy.reference_data.asset_life_codes,
            allow_blank=True,
        )

        # Book-Tax Difference — often blank
        proposal.book_tax_difference = self._confirm_text_field(
            "Book-Tax Difference",
            proposal.book_tax_difference,
            proposal.reasoning.get("book_tax_difference", ""),
            allow_blank=True,
        )

        # Cash Flow Category — pick from suggestions or enter custom
        cf_suggestions = self._suggester.suggest_cash_flow_category(proposal, self.hierarchy)
        proposal.cash_flow_category = self._confirm_code_field(
            "Cash Flow Category",
            proposal.cash_flow_category,
            [(v, 0, e) for v, e in cf_suggestions],
            proposal.reasoning.get("cash_flow_category", ""),
            self.hierarchy.reference_data.cash_flow_codes,
            allow_blank=True,
        )

        return proposal

    def _confirm_text_field(
        self,
        field_label: str,
        current_value: Optional[str],
        reasoning: str,
        allow_blank: bool = False,
    ) -> Optional[str]:
        """
        Shows the current suggestion for a text field and lets the user
        accept it, modify it, or (if allow_blank) clear it.
        """
        display_value = current_value if current_value else "(blank)"
        print(f"\n  {field_label}: {display_value}")
        if reasoning:
            print(f"  {reasoning}")

        # Build the action choices based on whether blanking is allowed
        choices = [
            ("Accept", "accept"),
            ("Modify", "modify"),
        ]
        if allow_blank:
            choices.append(("Clear (leave blank)", "clear"))

        action = self._pick(f"  {field_label}", choices, allow_cancel=False)

        if action == "modify":
            default_display = current_value or ""
            new_val = input(
                f"  Enter new {field_label} [{default_display}]: "
            ).strip()
            return new_val if new_val else current_value
        elif action == "clear":
            return ""
        # "accept" — return unchanged
        return current_value

    def _confirm_choice_field(
        self,
        field_label: str,
        current_value: Optional[str],
        options: list,
        reasoning: str,
    ) -> Optional[str]:
        """Shows current suggestion and lets user pick from a fixed list of options."""
        display_value = current_value if current_value else "(blank)"
        print(f"\n  {field_label}: {display_value}")
        if reasoning:
            print(f"  {reasoning}")

        # The current suggestion appears first as the default accept option
        choices = [(f"Accept ({current_value})", current_value)]
        for opt in options:
            if opt != current_value:
                choices.append((opt, opt))

        return self._pick(f"  {field_label}", choices, allow_cancel=False)

    def _confirm_code_field(
        self,
        field_label: str,
        current_value: Optional[str],
        suggestions: list,      # [(code, confidence_pct, explanation), ...]
        reasoning: str,
        code_lookup: dict,      # {code: description}
        allow_blank: bool = False,
    ) -> Optional[str]:
        """
        Shows the top suggestion and presents alternatives for code fields
        like FERC Code, Asset Life, and Cash Flow Category.
        """
        display_value = current_value if current_value else "(blank)"
        print(f"\n  {field_label}: {display_value}")
        if reasoning:
            print(f"  {reasoning}")

        # Start with the current accepted value
        choices = [(f"Accept ({display_value})", current_value)]

        # Add up to 4 alternative suggestions with descriptions and confidence
        for code, conf, expl in suggestions[:4]:
            desc = code_lookup.get(str(code), "")
            label = f"{code}"
            if desc:
                label += f" — {desc}"
            if conf:
                label += f" [{conf}%]"
            choices.append((label, code))

        if allow_blank:
            choices.append(("(blank / skip)", ""))
        choices.append(("Enter custom value", "__custom__"))

        selected = self._pick(f"  {field_label}", choices, allow_cancel=False)

        if selected == "__custom__":
            custom = input(f"  Enter custom {field_label}: ").strip()
            return custom if custom else current_value

        return selected

    # ------------------------------------------------------------------
    # Step e: Final Proposal Summary
    # ------------------------------------------------------------------

    def _show_final_proposal(self, proposal: NewAccountProposal) -> None:
        """Displays the complete proposal as an aligned plain-text table with borders."""

        def ref_desc(lookup: dict, code: str) -> str:
            """Appends reference description to a code value if one exists."""
            if not code:
                return "(blank)"
            desc = lookup.get(str(code), "")
            return f"{code} — {desc}" if desc else str(code)

        rows = [
            ("Account Number", str(proposal.account_number), "Selected by user"),
            ("Description", proposal.account_description or "", proposal.reasoning.get("account_description", "")),
            ("Company", ref_desc(self.hierarchy.reference_data.companies, proposal.company or ""), proposal.reasoning.get("company", "")),
            ("Business Unit", ref_desc(self.hierarchy.reference_data.business_units, proposal.business_unit or ""), proposal.reasoning.get("business_unit", "")),
            ("BU Type", proposal.bu_type or "", proposal.reasoning.get("bu_type", "")),
            ("Posting Edit", proposal.posting_edit or "(blank)", proposal.reasoning.get("posting_edit", "")),
            ("Line of Detail", str(proposal.line_of_detail), proposal.reasoning.get("line_of_detail", "")),
            ("FERC Code", ref_desc(self.hierarchy.reference_data.ferc_codes, proposal.ferc_code or ""), proposal.reasoning.get("ferc_code", "")),
            ("Asset Life", ref_desc(self.hierarchy.reference_data.asset_life_codes, proposal.asset_life or ""), proposal.reasoning.get("asset_life", "")),
            ("Book-Tax Diff", proposal.book_tax_difference or "(blank)", proposal.reasoning.get("book_tax_difference", "")),
            ("Cash Flow", ref_desc(self.hierarchy.reference_data.cash_flow_codes, proposal.cash_flow_category or ""), proposal.reasoning.get("cash_flow_category", "")),
        ]

        print("\n" + "=" * 70)
        print(f"  Account {proposal.account_number} — {proposal.account_description}")
        print("=" * 70)
        print(f"  {'Field':<18} {'Value':<35} Reasoning")
        print("-" * 70)

        for field, value, reason in rows:
            # Truncate long reasoning text so columns stay aligned
            reason_display = reason[:35] + "..." if len(reason) > 35 else reason
            print(f"  {field:<18} {value:<35} {reason_display}")

        print("=" * 70)

        # Show the full ancestry path so the user can verify placement
        if proposal.suggested_parent:
            ancestry = proposal.suggested_parent.ancestry_path()
            print(f"\n  Placement: {ancestry} > {proposal.account_description}")

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

    def _infer_bu_attributes_from_accounts(
        self, bu_code: str
    ) -> tuple:
        """
        Scans existing accounts to find which company and BU type
        co-occur with the given business unit code.
        Returns (company_code, bu_type) — either may be None.
        """
        matching = [
            a for a in self.hierarchy.accounts
            if a.business_unit == bu_code
        ]
        if not matching:
            return None, None

        company_counts = Counter(a.company for a in matching if a.company)
        inferred_company = (
            company_counts.most_common(1)[0][0] if company_counts else None
        )
        bu_type_counts = Counter(a.bu_type for a in matching if a.bu_type)
        inferred_bu_type = (
            bu_type_counts.most_common(1)[0][0] if bu_type_counts else None
        )
        return inferred_company, inferred_bu_type

    def _confirm_inferred_company(
        self, bu_code: str, inferred_company: Optional[str]
    ) -> Optional[str]:
        """
        Shows the company inferred for the selected BU and asks user to confirm.
        Falls back to manual selection if user declines or no inference available.
        """
        ref = self.hierarchy.reference_data
        if inferred_company:
            desc = ref.companies.get(inferred_company, "")
            label = inferred_company + (f" — {desc}" if desc else "")
            print(f"\n  Company matched from BU {bu_code}: {label}")
            if self._ask_yes_no("  Use this company?", default=True):
                return inferred_company

        # Fallback: manual selection from reference list
        print("  Select company manually:")
        company_choices = [
            (f"{code} — {desc}", code)
            for code, desc in sorted(ref.companies.items())
        ]
        if not company_choices:
            raw = input("  Enter company code (or blank to skip): ").strip()
            return raw if raw else None
        return self._pick("Company", company_choices, allow_cancel=True)

    def _confirm_inferred_bu_type(
        self, bu_code: str, inferred_bu_type: Optional[str]
    ) -> Optional[str]:
        """
        Shows the BU type (BS/IS) inferred for the selected BU and asks user to confirm.
        Falls back to manual choice if user declines or no inference available.
        """
        if inferred_bu_type:
            type_name = {
                "BS": "Balance Sheet", "IS": "Income Statement"
            }.get(inferred_bu_type, inferred_bu_type)
            print(
                f"\n  BU Type matched from BU {bu_code}: "
                f"{inferred_bu_type} ({type_name})"
            )
            if self._ask_yes_no("  Use this BU type?", default=True):
                return inferred_bu_type

        # Fallback: manual choice
        print("  Select BU type manually:")
        choices = [("BS — Balance Sheet", "BS"), ("IS — Income Statement", "IS")]
        return self._pick("BU Type", choices, allow_cancel=False)

    def _select_business_unit(self) -> tuple:
        """
        Prompts user to pick a Business Unit, then infers and confirms
        the associated company and BU type from existing accounts.
        Returns (bu_code, company_code, bu_type).
        Returns (None, None, None) if the user cancels.
        """
        ref = self.hierarchy.reference_data
        bu_choices = [
            (f"{code} — {desc}", code)
            for code, desc in sorted(ref.business_units.items())
        ]
        if not bu_choices:
            print("  No business units found in reference data.")
            return None, None, None

        print("\nSelect Business Unit:")
        bu_code = self._pick("Business Unit", bu_choices, allow_cancel=True)
        if bu_code is None:
            return None, None, None

        inferred_company, inferred_bu_type = self._infer_bu_attributes_from_accounts(bu_code)
        confirmed_company = self._confirm_inferred_company(bu_code, inferred_company)
        confirmed_bu_type = self._confirm_inferred_bu_type(bu_code, inferred_bu_type)

        return bu_code, confirmed_company, confirmed_bu_type
