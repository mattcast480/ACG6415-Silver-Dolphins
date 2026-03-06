# Changelog

All notable changes to CoA Architect are documented here.

---

## [0.1b] — 2026-03-04

### Changed

- **`coa_architect/cli.py`** — Rewrote all UI code to use `print()` and `input()` only, removing `rich` and `questionary` dependencies. The CLI is now fully compatible with Spyder 6 and IPython consoles, which do not emulate the native Windows console required by those libraries. All menus now display as numbered lists; all prompts use standard `input()`.
- **`main.py`** — Fixed argparse crash in Spyder: switched `parse_args()` to `parse_known_args()` so IPython kernel arguments (e.g. `-f kernel-xyz.json`) in `sys.argv` are silently ignored instead of causing an error.
- **`requirements.txt`** — Removed `questionary>=2.0.1` and `rich>=13.0.0`; no longer required.

---

## [0.1a] — 2026-03-04

### Added

- **`setup_project.py`** — One-click dependency installer for teammates new to the terminal; installs all packages from `requirements.txt`, adds Spyder for a GUI IDE experience, and prints step-by-step CLI setup instructions.

### Fixed

- **`coa_architect/cli.py`** — Added `Account` to the `.models` import (was: `AccountHierarchy, NewAccountProposal`; now: `Account, AccountHierarchy, NewAccountProposal`). Resolved `NameError: name 'Account' is not defined` that crashed `main.py` on startup.

---

## [0.1] — 2026-03-03

### Added

- **`coa_architect/models.py`** — Core dataclasses: `Account`, `AccountRange`, `ReferenceData`, `AccountHierarchy`, `NewAccountProposal`
- **`coa_architect/loader.py`** — `CoALoader` class: reads Chart of Accounts Excel workbook into Python objects; auto-detects column headers with synonym matching; loads all reference sheets (FERC, Asset Life, Cash Flow, Posting Edit, Book-Tax, Companies, Business Units); supports optional external FERC reference files (CSV or Excel)
- **`coa_architect/analyzer.py`** — `CoAAnalyzer` class: backward-scan hierarchy builder (handles level skips); range ownership computation; dominant spacing pattern detection; FERC usage map builder
- **`coa_architect/placer.py`** — `AccountPlacer` class: scores Level 1–4 parent candidates using keyword overlap, BU type, FERC consistency, level depth, and naming pattern similarity; finds safe account numbers within parent range using dominant-spacing, round-100, and round-1000 strategies; enforces no-gap constraint
- **`coa_architect/validator.py`** — `AccountValidator` class: enforces four safety rules (6-digit range, not-in-use, within-range, not-a-header-boundary); validates FERC codes and asset life values against reference data; identifies gap ranges for clear error messages
- **`coa_architect/suggester.py`** — `CategorySuggester` class: suggests FERC codes from sibling accounts, keyword matching, and section frequency; suggests asset life via keyword lookup table (land=0, software=36, turbine=300, building=420, etc.); suggests cash flow category by BU type; inherits BU type from parent; all suggestions include confidence percentage and explanation
- **`coa_architect/exporter.py`** — `CoAExporter` class: inserts new account row in sorted position after last sibling; copies cell formatting from adjacent row; re-sequences Account ID column; creates timestamped backup before saving
- **`coa_architect/cli.py`** — `CoAArchitectCLI` class: full interactive terminal session using `rich` panels/tables and `questionary` select menus; field-by-field confirmation with Accept/Modify/Skip; final proposal summary with ancestry path; multi-account session loop
- **`main.py`** — CLI entry point with `argparse`; `--file` and `--ferc-ref` arguments; graceful handling of `KeyboardInterrupt` and `FileNotFoundError`
- **`tests/test_loader.py`** — Unit tests for column detection, account parsing, reference data loading, external FERC file support
- **`tests/test_analyzer.py`** — Unit tests for backward-scan hierarchy, range computation, number pattern detection, FERC usage map
- **`tests/test_placer.py`** — Unit tests for safe number validation (accept/reject cases), candidate number generation, parent candidate scoring
- **`tests/test_suggester.py`** — Unit tests for FERC suggestion (turbine→314), asset life (land→0), cash flow (BS→INV, IS→OP), BU type inheritance, posting edit, `suggest_all` integration
- **`requirements.txt`** — `openpyxl>=3.1.0`, `questionary>=2.0.1`, `rich>=13.0.0`, `pytest>=7.0.0`
- **`README.md`** — Full usage instructions, installation steps, session walkthrough, project structure, business rules, external FERC file format
