"""
cli.py — Interactive terminal UI for CoA Architect.

CoAArchitectCLI orchestrates the full user session using:
  - rich   for formatted tables, panels, and styled output
  - questionary for arrow-key select menus and validated text prompts

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

import sys
from typing import Optional

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from .models import AccountHierarchy, NewAccountProposal
from .loader import CoALoader
from .analyzer import CoAAnalyzer
from .placer import AccountPlacer
from .suggester import CategorySuggester
from .validator import AccountValidator
from .exporter import CoAExporter

VERSION = "1.0"
console = Console()


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
                break  # User typed 'quit'

            add_another = questionary.confirm(
                "Add another account?", default=False
            ).ask()
            if not add_another:
                break

        console.print("\n[bold green]Session complete. Goodbye![/bold green]")

    # ------------------------------------------------------------------
    # Step 1: Welcome Screen
    # ------------------------------------------------------------------

    def _show_welcome(self) -> None:
        """Displays the app name and version in a rich panel."""
        console.print(
            Panel(
                f"[bold cyan]CoA Architect v{VERSION}[/bold cyan]\n"
                "[dim]Safe Chart of Accounts extension tool for Silver Dolphins LLP[/dim]",
                box=box.DOUBLE,
                expand=False,
            )
        )

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
            self.file_path = questionary.path(
                "CoA Excel file path:",
                only_directories=False,
            ).ask()
            if not self.file_path:
                console.print("[red]No file path provided. Exiting.[/red]")
                sys.exit(1)

        # Prompt for optional external FERC reference file
        if self.ferc_ref_path is None:
            load_ferc = questionary.confirm(
                "Load an external FERC reference file? (optional)", default=False
            ).ask()
            if load_ferc:
                self.ferc_ref_path = questionary.path(
                    "External FERC file path (CSV or Excel):"
                ).ask()

        console.print(f"\n[dim]CoA file:   {self.file_path}[/dim]")
        console.print(f"[dim]FERC ref:   {self.ferc_ref_path or '(none)'}[/dim]\n")

        # Load the workbook
        with console.status("Loading workbook..."):
            accounts, reference_data, column_mapping, workbook = (
                self._loader.load_chart_of_accounts(self.file_path)
            )
            self.workbook = workbook

        # Merge external FERC codes if provided
        if self.ferc_ref_path:
            with console.status("Loading external FERC codes..."):
                try:
                    external_codes = self._loader.load_external_ferc_file(self.ferc_ref_path)
                    # CoA-embedded codes take precedence
                    new_external = set()
                    for code, desc in external_codes.items():
                        if code not in reference_data.ferc_codes:
                            reference_data.ferc_codes[code] = desc
                            new_external.add(code)
                    reference_data.external_ferc_codes = new_external
                    console.print(
                        f"[green]Loaded {len(new_external)} new FERC codes from external file.[/green]"
                    )
                except Exception as e:
                    console.print(f"[yellow]Warning: Could not load external FERC file: {e}[/yellow]")

        # Build the hierarchy
        with console.status("Analyzing hierarchy..."):
            self.hierarchy = self._analyzer.analyze(
                accounts, reference_data, column_mapping, self.file_path
            )

        # Show column mapping for confirmation
        self._show_column_mapping(column_mapping)

    def _show_column_mapping(self, column_mapping: dict) -> None:
        """Displays the detected column mapping as a rich table."""
        table = Table(title="Detected Column Mapping", box=box.SIMPLE)
        table.add_column("Field", style="cyan")
        table.add_column("Column", style="green")

        for field, col_letter in sorted(column_mapping.items()):
            table.add_row(field, col_letter or "(not found)")

        console.print(table)
        console.print()

    # ------------------------------------------------------------------
    # Step 3: Hierarchy Summary
    # ------------------------------------------------------------------

    def _show_hierarchy_summary(self) -> None:
        """Displays a summary table: level counts and section breakdown."""
        from collections import Counter

        accounts = self.hierarchy.accounts
        level_counts = Counter(a.line_of_detail for a in accounts)

        level_summary = "  ".join(
            f"L{level}×{count}" for level, count in sorted(level_counts.items())
        )

        console.print(
            f"[bold]Loaded {len(accounts)} accounts across "
            f"{len([a for a in accounts if a.line_of_detail == 1])} sections.[/bold]"
        )
        console.print(f"Hierarchy: {level_summary}\n")

        # Section breakdown table
        table = Table(title="Sections", box=box.SIMPLE)
        table.add_column("Account #", style="cyan")
        table.add_column("Description", style="white")
        table.add_column("Children", style="green")

        level1 = [a for a in accounts if a.line_of_detail == 1]
        for section in sorted(level1, key=lambda a: a.account_number):
            child_count = sum(1 for a in accounts if a.parent and
                              self._find_level1_ancestor(a) and
                              self._find_level1_ancestor(a).account_number == section.account_number)
            table.add_row(
                str(section.account_number),
                section.account_description,
                str(child_count),
            )

        console.print(table)
        console.print()

    # ------------------------------------------------------------------
    # Step 4: Add Account Session (one account per loop iteration)
    # ------------------------------------------------------------------

    def _add_account_session(self) -> Optional[NewAccountProposal]:
        """
        Runs one complete account-addition interaction.
        Returns the completed proposal on success, or None if the user quits.
        """
        # a. Describe the new account
        description = questionary.text(
            "Describe the new account in plain English (or type 'quit' to exit):"
        ).ask()

        if not description or description.strip().lower() == "quit":
            return None

        proposal = NewAccountProposal(account_description=description.strip())

        # b. Select parent account
        parent = self._select_parent(description, proposal)
        if parent is None:
            return None
        proposal.suggested_parent = parent

        # Populate account_description from input if not set
        proposal.account_description = proposal.account_description or description

        # c. Select account number
        number = self._select_account_number(parent, proposal)
        if number is None:
            return None
        proposal.account_number = number

        # d. Auto-suggest all fields
        with console.status("Generating suggestions..."):
            self._suggester.suggest_all(proposal, self.hierarchy)

        # Step through each field for confirmation
        proposal = self._confirm_fields(proposal)

        # e. Show final summary
        self._show_final_proposal(proposal)

        # f. Confirm and export
        confirmed = questionary.confirm(
            "Add to CoA and save?", default=True
        ).ask()

        if confirmed:
            with console.status("Saving..."):
                saved_path = self._exporter.export(proposal, self.hierarchy, self.workbook)
            console.print(
                f"\n[bold green]Account {proposal.account_number} — "
                f"'{proposal.account_description}' added. File saved.[/bold green]"
            )
            console.print(f"[dim]Saved to: {saved_path}[/dim]\n")
            return proposal
        else:
            console.print("[yellow]Cancelled — file not changed.[/yellow]\n")
            return None

    def _select_parent(
        self, description: str, proposal: NewAccountProposal
    ) -> Optional[Account]:
        """
        Scores all Level 1–4 accounts and presents the top 5 for selection.
        Returns the chosen parent Account, or None if user cancels.
        """
        scored = self._placer.score_parent_candidates(description, self.hierarchy)

        if not scored:
            console.print("[red]No eligible parent accounts found.[/red]")
            return None

        # Prepare up to 5 choices for questionary.select
        top5 = scored[:5]

        choices = []
        for score, account in top5:
            ancestry = account.ancestry_path()
            label = f"[{score:.0f}%] {account.account_number} — {account.account_description}"
            choices.append(
                questionary.Choice(
                    title=f"{label}\n      {ancestry}",
                    value=account,
                )
            )

        choices.append(questionary.Choice(title="(show more / search manually)", value="more"))
        choices.append(questionary.Choice(title="(cancel)", value=None))

        console.print("\n[bold]Top parent candidates:[/bold]")
        selected = questionary.select(
            "Select parent account:",
            choices=choices,
        ).ask()

        if selected == "more":
            # Show all candidates
            return self._select_parent_from_all(scored)
        return selected

    def _select_parent_from_all(self, scored: list) -> Optional[Account]:
        """Shows all candidates when user requests 'show more'."""
        choices = [
            questionary.Choice(
                title=(
                    f"[{score:.0f}%] {account.account_number} — "
                    f"{account.account_description} | {account.ancestry_path()}"
                ),
                value=account,
            )
            for score, account in scored
        ]
        choices.append(questionary.Choice(title="(cancel)", value=None))

        return questionary.select(
            "Select parent account:", choices=choices
        ).ask()

    def _select_account_number(
        self, parent: Account, proposal: NewAccountProposal
    ) -> Optional[int]:
        """
        Finds safe candidate numbers and presents them for selection.
        Also allows free-text entry with validation.
        Returns the chosen number, or None if cancelled.
        """
        candidates = self._placer.find_available_numbers_in_range(parent, self.hierarchy)

        # Find the parent's range for display
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

        console.print(
            f"\n[bold]Suggested numbers[/bold] "
            f"(range {range_str}, last sibling: {last_child}):"
        )

        choices = [
            questionary.Choice(
                title=f"{number}  ({rationale})",
                value=number,
            )
            for number, rationale in candidates
        ]
        choices.append(questionary.Choice(title="Enter a custom number", value="custom"))
        choices.append(questionary.Choice(title="(cancel)", value=None))

        selected = questionary.select(
            "Select account number:", choices=choices
        ).ask()

        if selected == "custom":
            return self._prompt_custom_number()
        return selected

    def _prompt_custom_number(self) -> Optional[int]:
        """Prompts the user to enter a custom account number with validation."""
        def validate_number(text: str) -> bool | str:
            try:
                n = int(text.strip())
            except ValueError:
                return "Please enter a 6-digit integer."
            ok, msg = self._validator.validate_account_number(n, self.hierarchy)
            if not ok:
                return msg
            return True

        raw = questionary.text(
            "Enter a 6-digit account number:",
            validate=validate_number,
        ).ask()

        if raw is None:
            return None
        return int(raw.strip())

    # ------------------------------------------------------------------
    # Step d: Field-by-field confirmation
    # ------------------------------------------------------------------

    def _confirm_fields(self, proposal: NewAccountProposal) -> NewAccountProposal:
        """
        Steps the user through each suggested field value.
        For each field, the user can: Accept / Modify / Skip.
        """
        console.print("\n[bold]Confirming fields:[/bold]")

        # Description — always prompt for review
        proposal.account_description = self._confirm_text_field(
            "Description",
            proposal.account_description,
            "Derived from your plain-English input.",
        )

        # Company
        proposal.company = self._confirm_text_field(
            "Company",
            proposal.company,
            proposal.reasoning.get("company", ""),
        )

        # Business Unit
        proposal.business_unit = self._confirm_text_field(
            "Business Unit",
            proposal.business_unit,
            proposal.reasoning.get("business_unit", ""),
        )

        # BU Type
        proposal.bu_type = self._confirm_choice_field(
            "BU Type",
            proposal.bu_type,
            ["BS", "IS"],
            proposal.reasoning.get("bu_type", ""),
        )

        # Posting Edit — usually blank for Level 5
        proposal.posting_edit = self._confirm_text_field(
            "Posting Edit",
            proposal.posting_edit,
            proposal.reasoning.get("posting_edit", ""),
            allow_blank=True,
        )

        # Line of Detail — fixed at 5 for posting accounts
        console.print(
            f"  [dim]Line of Detail: 5  "
            f"({proposal.reasoning.get('line_of_detail', 'Posting account')})[/dim]"
        )
        proposal.line_of_detail = 5

        # FERC Code
        ferc_suggestions = self._suggester.suggest_ferc_code(proposal, self.hierarchy)
        proposal.ferc_code = self._confirm_code_field(
            "FERC Code",
            proposal.ferc_code,
            ferc_suggestions,
            proposal.reasoning.get("ferc_code", ""),
            self.hierarchy.reference_data.ferc_codes,
        )

        # Asset Life
        life_suggestions = self._suggester.suggest_asset_life(proposal, self.hierarchy)
        life_choices = [(v, e) for v, e in life_suggestions]
        proposal.asset_life = self._confirm_code_field(
            "Asset Life",
            proposal.asset_life,
            [(v, 0, e) for v, e in life_choices],  # fake confidence pct=0
            proposal.reasoning.get("asset_life", ""),
            self.hierarchy.reference_data.asset_life_codes,
            allow_blank=True,
        )

        # Book-Tax Difference
        proposal.book_tax_difference = self._confirm_text_field(
            "Book-Tax Difference",
            proposal.book_tax_difference,
            proposal.reasoning.get("book_tax_difference", ""),
            allow_blank=True,
        )

        # Cash Flow Category
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
        console.print(
            f"\n  [cyan]{field_label}:[/cyan] {display_value}\n"
            f"  [dim]{reasoning}[/dim]"
        )

        action = questionary.select(
            f"  {field_label}:",
            choices=[
                questionary.Choice("Accept", value="accept"),
                questionary.Choice("Modify", value="modify"),
                *(
                    [questionary.Choice("Clear (leave blank)", value="clear")]
                    if allow_blank else []
                ),
            ],
        ).ask()

        if action == "modify":
            new_val = questionary.text(
                f"  Enter new {field_label}:", default=current_value or ""
            ).ask()
            return new_val.strip() if new_val else current_value
        elif action == "clear":
            return ""
        return current_value

    def _confirm_choice_field(
        self,
        field_label: str,
        current_value: Optional[str],
        options: list,
        reasoning: str,
    ) -> Optional[str]:
        """Shows current suggestion and lets user pick from a fixed list."""
        display_value = current_value if current_value else "(blank)"
        console.print(
            f"\n  [cyan]{field_label}:[/cyan] {display_value}\n"
            f"  [dim]{reasoning}[/dim]"
        )

        choices = [questionary.Choice(f"Accept ({current_value})", value=current_value)]
        for opt in options:
            if opt != current_value:
                choices.append(questionary.Choice(opt, value=opt))

        return questionary.select(f"  {field_label}:", choices=choices).ask()

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
        like FERC, Asset Life, Cash Flow Category.
        """
        display_value = current_value if current_value else "(blank)"
        console.print(
            f"\n  [cyan]{field_label}:[/cyan] {display_value}\n"
            f"  [dim]{reasoning}[/dim]"
        )

        choices = [questionary.Choice(f"Accept ({display_value})", value=current_value)]

        for code, conf, expl in suggestions[:4]:
            desc = code_lookup.get(str(code), "")
            label = f"{code}"
            if desc:
                label += f" — {desc}"
            if conf:
                label += f" [{conf}%]"
            choices.append(questionary.Choice(label, value=code))

        if allow_blank:
            choices.append(questionary.Choice("(blank / skip)", value=""))
        choices.append(questionary.Choice("Enter custom value", value="__custom__"))

        selected = questionary.select(f"  {field_label}:", choices=choices).ask()

        if selected == "__custom__":
            custom = questionary.text(f"  Enter custom {field_label}:").ask()
            return custom.strip() if custom else current_value

        return selected

    # ------------------------------------------------------------------
    # Step e: Final Proposal Summary
    # ------------------------------------------------------------------

    def _show_final_proposal(self, proposal: NewAccountProposal) -> None:
        """Displays the complete proposal as a rich table with ancestry path."""
        table = Table(
            title=f"Account {proposal.account_number} — {proposal.account_description}",
            box=box.ROUNDED,
        )
        table.add_column("Field", style="cyan", no_wrap=True)
        table.add_column("Value", style="white")
        table.add_column("Reasoning", style="dim")

        def ref_desc(lookup: dict, code: str) -> str:
            """Appends reference description to a code if available."""
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

        for field, value, reason in rows:
            table.add_row(field, value, reason[:60] + "..." if len(reason) > 60 else reason)

        console.print(table)

        # Show ancestry path
        if proposal.suggested_parent:
            ancestry = proposal.suggested_parent.ancestry_path()
            console.print(
                Panel(
                    f"[dim]Placement:[/dim] {ancestry} > "
                    f"[bold]{proposal.account_description}[/bold]",
                    expand=False,
                )
            )

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
