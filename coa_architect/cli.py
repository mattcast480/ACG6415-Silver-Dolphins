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
import re
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

    def __init__(self, file_path: Optional[str] = None):
        self.file_path = file_path
        self.hierarchy: Optional[AccountHierarchy] = None
        self.workbook = None
        self._loader = CoALoader()
        self._analyzer = CoAAnalyzer()
        self._placer = AccountPlacer()
        self._suggester = CategorySuggester()
        self._validator = AccountValidator()
        self._exporter = CoAExporter()
        # Read Anthropic API key from environment; None if not set
        self._api_key: Optional[str] = os.environ.get("ANTHROPIC_API_KEY") or None

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
        Prompts for the CoA file path if not already provided, then loads,
        analyzes, and enriches it with advisory context from 1.code_tables/.

        Call sequence:
          1. Prompt for file path (if needed)
          2. Create working copy
          3. Load workbook + parse accounts
          4. Build hierarchy
          5. Load advisory context from 1.code_tables/
          6. Show column mapping
        """
        # Prompt for CoA file path if not provided via CLI arg
        if not self.file_path:
            self.file_path = input("\nCoA Excel file path: ").strip().strip('"')
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

        print(f"\nCoA file:   {self.file_path}\n")

        # Load the workbook
        print("Loading workbook...")
        accounts, reference_data, column_mapping, workbook = (
            self._loader.load_chart_of_accounts(self.file_path)
        )
        self.workbook = workbook

        # Build the hierarchy
        print("Analyzing hierarchy...")
        self.hierarchy = self._analyzer.analyze(
            accounts, reference_data, column_mapping, self.file_path
        )

        # Push hierarchy into Spyder/IPython Variable Explorer for traceability
        # Inspect .accounts, .patterns, .ferc_usage_map, .ranges, .column_mapping
        try:
            get_ipython().user_ns["account_hierarchy"] = self.hierarchy
        except (NameError, AttributeError):
            pass  # Not running in IPython — skip silently

        # Report API key status so the user knows which generator is active
        if self._api_key:
            print("API key found — account description generation enabled (claude-haiku-4-5)")
        else:
            print("No ANTHROPIC_API_KEY — using rule-based description generation")

        # Load advisory context from 1.code_tables/ (after hierarchy is ready)
        self._load_code_tables()

        # Show column mapping for user confirmation
        self._show_column_mapping(column_mapping)

    # ------------------------------------------------------------------
    # Post-Save Reload
    # ------------------------------------------------------------------

    def _reload_after_save(self) -> None:
        """
        Reloads the workbook and rebuilds the hierarchy from the saved file.
        Called after each successful account addition so that max_account_id
        and all hierarchy data reflect the newly saved state.
        Advisory context is preserved — no need to re-scan code tables.
        """
        # Preserve advisory context loaded at session start
        advisory_context = getattr(self.hierarchy, "advisory_context", {})

        # Reload workbook from the saved file
        accounts, reference_data, column_mapping, workbook = (
            self._loader.load_chart_of_accounts(self.file_path)
        )
        self.workbook = workbook

        # Rebuild hierarchy from fresh data
        self.hierarchy = self._analyzer.analyze(
            accounts, reference_data, column_mapping, self.file_path
        )

        # Restore advisory context so code-table validation still works
        self.hierarchy.advisory_context = advisory_context

        # Re-expose updated hierarchy to Variable Explorer after save/reload
        try:
            get_ipython().user_ns["account_hierarchy"] = self.hierarchy
        except (NameError, AttributeError):
            pass  # Not running in IPython — skip silently

    # ------------------------------------------------------------------
    # Advisory Code Tables
    # ------------------------------------------------------------------

    def _load_code_tables(self) -> None:
        """
        Scans the 1.code_tables/ folder for advisory reference files, loads them,
        and stores the result on self.hierarchy.advisory_context.

        Files are matched to column headers by case-insensitive filename stem comparison.
        All issues (conflicts, unrecognized files, parse errors) are reported after
        loading completes, each with a fix-or-proceed numbered menu.

        The final advisory_context dict is also pushed to the IPython namespace as
        'advisory_context_tables' for inspection in the Spyder variable explorer.
        """
        from .code_table_loader import (
            get_actual_column_headers,
            scan_code_tables,
            load_advisory_file,
            build_advisory_context,
            ADVISORY_LOGIC_FIELDS,
        )

        # Locate 1.code_tables/ relative to this module file
        # coa_architect/cli.py → coa_architect/ → repo_root/ → 1.code_tables/
        _module_dir = os.path.dirname(os.path.abspath(__file__))
        _code_tables_dir = os.path.normpath(
            os.path.join(_module_dir, "..", "1.code_tables")
        )

        if not os.path.isdir(_code_tables_dir):
            return  # Folder absent — nothing to load; silently continue

        # Step 1: Get actual column headers from the main worksheet row 1
        ws = self.workbook.worksheets[0]
        column_headers = get_actual_column_headers(ws)

        # (No synonym-based mapping needed here — advisory logic check below uses
        # normalization directly: "Book-Tax Difference" → "book_tax_difference")

        # Step 2: Scan folder
        matches, conflicts, unrecognized = scan_code_tables(_code_tables_dir, column_headers)

        # Step 3: Resolve conflicts — ask user which file to use for each column
        for col_header in sorted(conflicts):
            file_paths = conflicts[col_header]
            print(f"\nWarning: Multiple files match column '{col_header}':")
            file_choices = [
                (os.path.basename(p), p) for p in file_paths
            ]
            file_choices.append(("Proceed without any file for this column", None))
            chosen = self._pick(
                f"  Which file to use for '{col_header}'?",
                file_choices,
                allow_cancel=False,
            )
            if chosen is not None:
                matches[col_header] = chosen
            # If chosen is None, this column has no advisory file — skip silently

        # Step 4: Load each matched file (collect results; errors reported next)
        loaded_data: dict = {}
        for col_header in sorted(matches):
            file_path = matches[col_header]
            content, error = load_advisory_file(file_path)
            filename = os.path.basename(file_path)

            if error or content is None:
                reason = error or "No data could be extracted from the file."
                self._code_table_issue(f"'{filename}' could not be parsed: {reason}")
                # _code_table_issue exits if user chooses End session; otherwise skip file
                continue

            loaded_data[col_header] = content
            print(f"Successfully loaded {filename}")

            # Warn if this column has no advisory logic in suggester.py.
            # Normalize the column header to snake_case (lowercase, spaces/hyphens/slashes
            # become underscores) and check against the known set of implemented fields.
            # Example: "Book-Tax Difference" → "book_tax_difference" → recognized ✓
            field = re.sub(r"[\s\-/]+", "_", col_header.lower())
            if field not in ADVISORY_LOGIC_FIELDS:
                print(
                    f"  Note: '{col_header}' has no advisory logic — "
                    f"{filename} is loaded but will not affect suggestions."
                )

        # Step 5: Report unrecognized files (no column match)
        for file_path in unrecognized:
            filename = os.path.basename(file_path)
            self._code_table_issue(
                f"'{filename}' does not match any column in the CoA. "
                "Rename it to match a column header exactly "
                "(e.g., 'FERC Code.pdf', 'Asset Life.csv')."
            )

        # Step 6: Build final advisory context dict and store on hierarchy
        advisory_context_tables = build_advisory_context(matches, loaded_data)
        self.hierarchy.advisory_context = advisory_context_tables

        # Push to IPython / Spyder variable explorer for inspection
        try:
            get_ipython().user_ns["advisory_context_tables"] = advisory_context_tables
        except (NameError, AttributeError):
            pass  # Not running in IPython — skip silently

    def _code_table_issue(self, message: str) -> None:
        """
        Displays a warning and a fix-or-proceed numbered menu for a code table problem.

        If the user chooses 'End session', exits immediately so they can fix the issue.
        If the user chooses 'Proceed without this file', returns normally (caller skips).
        """
        print(f"\n  Warning: {message}")
        choices = [
            ("Proceed without this file", "proceed"),
            ("End session (fix the issue and start a new session)", "exit"),
        ]
        result = self._pick("  Action", choices, allow_cancel=False)
        if result == "exit":
            print("\nSession ended. Please fix the issue and restart.")
            sys.exit(0)

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

        # Generate a short professional account description from the plain-English input
        self._generate_account_description(proposal, description)

        proposal = self._confirm_fields(proposal)

        # f. Show final summary
        self._show_final_proposal(proposal)

        # Push completed proposal into Variable Explorer so the suggestion reasoning
        # chain is inspectable (inspect .reasoning for per-field confidence + source)
        try:
            get_ipython().user_ns["last_proposal"] = proposal
        except (NameError, AttributeError):
            pass  # Not running in IPython — skip silently

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
            self._reload_after_save()   # Refresh hierarchy so next account gets a unique ID
            return proposal
        else:
            print("Cancelled — file not changed.\n")
            return None

    def _generate_account_description(
        self, proposal: NewAccountProposal, original_input: str
    ) -> None:
        """
        Replaces the raw plain-English input on the proposal with a short,
        professional account description.

        Calls the Claude API when an API key is available; otherwise uses
        the rule-based generator.  Preserves the original input string in
        proposal.reasoning["account_description"] so the user can see how
        the title was derived.

        This method never raises — any API failure is caught in generate_description.
        """
        from .description_generator import generate_description

        if self._api_key:
            print("Generating account description...")

        generated, reasoning = generate_description(
            original_input, proposal, self.hierarchy, self._api_key
        )
        proposal.account_description = generated
        proposal.reasoning["account_description"] = reasoning

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
            return self._prompt_custom_number(business_unit=proposal.business_unit)
        return selected

    def _prompt_custom_number(self, business_unit: Optional[str] = None) -> Optional[int]:
        """
        Prompts the user to enter a custom account number with validation.

        business_unit is passed through to the validator so that Rule 2 can
        allow the same account number across different business units — only
        a duplicate (number, business_unit) pair is rejected.
        """
        while True:
            raw = input("Enter a 6-digit account number (or blank to cancel): ").strip()
            if not raw:
                return None
            try:
                n = int(raw)
            except ValueError:
                print("  Please enter a 6-digit integer.")
                continue
            # Validate against existing hierarchy rules (pass BU for composite-key check)
            ok, msg = self._validator.validate_account_number(n, self.hierarchy, business_unit)
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
