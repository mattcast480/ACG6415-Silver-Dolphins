# Changelog

All notable changes to CoA Architect are documented here.

---

## [1.0] — 2026-03-24

### Added

- **`coa_architect/cli.py`** — `account_hierarchy` (the full `AccountHierarchy` object) is now
  pushed to the IPython/Spyder Variable Explorer immediately after the hierarchy is built at
  startup, and again after every save/reload. Allows graders and instructors to inspect
  `.accounts`, `.patterns`, `.ferc_usage_map`, `.ranges`, and `.column_mapping` interactively.

- **`coa_architect/cli.py`** — `last_proposal` (the `NewAccountProposal` object) is now pushed
  to the Variable Explorer after the final proposal summary is displayed for each account.
  Inspect `.reasoning` to see per-field confidence levels and suggestion sources
  (e.g. `"[85%] 2 of 3 siblings use FERC 314 — Wind Turbines"`).

- **`1.code_tables/Asset Life.csv`** — Advisory asset life reference table committed to the
  repository so the app can load it at startup without a separate manual step.

- **`1.code_tables/FERC Code.pdf`** — FERC Uniform System of Accounts reference PDF committed
  to the repository for advisory context loading.

- **`resources/`** — Additional reference documents committed: `Asset Life - tax life.pdf`,
  `BOOK TO TAX DIFFERENCE - Explained.docx`, `COA Descriptions, Class Life and Years.pdf`,
  `COA_Descriptions_Class_Life_and_Years.csv`, `CoA_Architect_Session_Checklist.docx`,
  `CoA_Architect_Session_Checklist.txt`.

### Fixed

- **`coa_architect/cli.py`** — `VERSION` constant corrected from `"1.0"` to match actual
  release history (`"0.2b"`), then bumped to `"1.0"` for this release. Banner was displaying
  a future version number.

### Changed

- **`CLAUDE.md`** — Added session-end workflow rule: before each commit/tag, update `VERSION`
  in `coa_architect/cli.py` to match the version tag being applied. Keeps the in-app banner
  permanently in sync with the git tag.

### Tests

- All 86 unit tests pass (`pytest tests/`). No new tests required.

---

## [0.2b] — 2026-03-22

### Added

- **`1.code_tables/Book-Tax Difference.csv`** — New advisory reference file mapping
  9 book-tax difference codes (L274, L162m, L163j, L243, T+, T-, P+, P-) to descriptions
  that include example account names and IRC references. Used by `suggest_book_tax_difference()`
  at runtime.

### Fixed

- **`coa_architect/loader.py`** — `detect_column_mapping()` now includes a normalization
  fallback for optional/advisory fields. After the synonym list is exhausted, each actual
  column header is lowercased and its spaces, hyphens, and slashes are replaced with
  underscores; if the result matches the field name the column is mapped. Example:
  `"Book-Tax Difference"` → `"book_tax_difference"`. This means advisory files in
  `1.code_tables/` must be named to match the exact column header text in the workbook
  (case-insensitive), not a hardcoded synonym variant.

- **`coa_architect/cli.py`** — The advisory logic check that warns `"has no advisory logic"`
  now uses the same normalization (`re.sub(r"[\s\-/]+", "_", col_header.lower())`) instead
  of the synonym-dependent `header_lower_to_field` lookup. Removes a false-positive warning
  for any column whose header contains hyphens (e.g. `"Book-Tax Difference"`).

### Changed

- **`coa_architect/suggester.py`** — Added `suggest_book_tax_difference()`: keyword-overlap
  scoring against the advisory CSV. Tokenizes the account description, counts matching words
  against each code's description text, and returns the best-matching code with confidence
  capped at 40% (book-tax requires professional judgment). Wired into `suggest_all()`,
  replacing the former hardcoded `"Review with tax team — no automatic suggestion."` message.
  That message is still returned as a fallback when no keyword match is found.

### Tests

- All 86 unit tests pass (`pytest tests/`). No new tests required.

---

## [0.2a] — 2026-03-21

### Fixed

- **`coa_architect/code_table_loader.py`** — `_load_csv()` now detects a numeric code
  column by content when no explicit "Code" header exists. Scans each column; if ≥ 70 %
  of non-empty values are pure integers, treats it as the code column (last match wins).
  Builds a `{code: concatenated_text}` dict by joining all remaining columns per row,
  concatenating multiple rows that share the same code. Result: the Asset Life CSV
  (`Category, Account_Range, Asset_Name, Description, Asset_Life_Months`) now loads as
  a structured dict keyed by months, enabling keyword matching in `suggest_asset_life()`.

- **`coa_architect/suggester.py`** — `suggest_asset_life()` refactored so the advisory
  context (PDF/CSV table) is the PRIMARY source, consulted first and ranked by
  keyword-overlap count (most specific match first). The hardcoded `ASSET_LIFE_KEYWORDS`
  table is now a FALLBACK consulted only when the advisory context produces no matches.
  Sibling suggestion is appended rather than force-inserted at position 0, so advisory
  and keyword results retain their rank when present.

- **`coa_architect/cli.py`** — File-path input strips surrounding quote characters
  (`.strip('"')`) so paths pasted with Windows Explorer quotes no longer crash the loader.

### Tests

- All 86 unit tests pass (`pytest tests/`). No new tests required.

---

## [0.2] — 2026-03-18

### Changed

- **`coa_architect/placer.py`** — Reordered account number candidates in
  `find_available_numbers_in_range()`. The near-parent 100-step scan (formerly last)
  is now shown first (up to 3 results), so users see the earliest open space in the
  parent range before being offered the dominant-spacing option. Dominant spacing,
  next round-100, and next round-1000 candidates follow. No validation rules changed.
- **`coa_architect/cli.py`** — Added `_reload_after_save()`: after each successful
  account insertion the workbook is reloaded and the hierarchy rebuilt from the saved
  file. This ensures `max_account_id` and sibling lists are accurate for the next
  account added in the same session. Advisory context (code tables) is preserved
  across reloads.

### Tests

- All 86 unit tests pass (`pytest tests/`). No new tests required — the ordering
  change is covered by existing `TestFindAvailableNumbersInRange` assertions and the
  reload logic is exercised by the manual end-to-end workflow.

---

## [0.1d] — 2026-03-14

### Added

- **`coa_architect/code_table_loader.py`** — New module that owns all `1.code_tables/` logic.
  Scans the folder at startup, matches filenames (case-insensitively) to CoA column headers,
  parses CSV / Excel / text-based PDF files, and returns an advisory context dict. Includes
  `get_actual_column_headers()`, `scan_code_tables()`, `load_advisory_file()`, and
  `build_advisory_context()`.
- **`AccountHierarchy.advisory_context`** — New field (`dict`, default `{}`) on the hierarchy
  dataclass. Stores `{column_header: {code: desc}}` content loaded from `1.code_tables/`.
  Pushed to the IPython namespace as `advisory_context_tables` for Spyder inspection.

### Changed

- **`coa_architect/cli.py`** — Replaced the hardcoded FERC-only external file prompt with a
  generalized `_load_code_tables()` method. Removed `ferc_ref_path` parameter and all FERC
  auto-detect / manual-prompt logic. Added `_code_table_issue()` helper for fix-or-proceed menus.
- **`coa_architect/suggester.py`** — Updated `suggest_ferc_code()` Source 4 to use
  `hierarchy.advisory_context["FERC Code"]` (richer descriptions, only suggests codes that
  exist in the workbook). Added advisory context augmentation to `suggest_asset_life()` and
  `suggest_cash_flow_category()`.
- **`coa_architect/loader.py`** — Removed `load_external_ferc_file()`, `_load_ferc_from_csv()`,
  and `_load_ferc_from_excel()` (now handled by `code_table_loader`).
- **`coa_architect/models.py`** — Removed `external_ferc_codes: set` from `ReferenceData`
  (replaced by `advisory_context` on `AccountHierarchy`).
- **`requirements.txt`** — Added `pdfplumber>=0.10.0` as a runtime dependency (moved from
  `requirements-dev.txt`; now needed by `code_table_loader.py` at startup).
- **`requirements-dev.txt`** — Removed `pdfplumber` (promoted to runtime dependency).

### Tests

- **`tests/test_loader.py`** — Removed `TestLoadExternalFercFile` (tested removed methods).
- **`tests/test_suggester.py`** — Replaced `test_external_ferc_codes_labeled_differently` with
  `test_advisory_context_ferc_codes_labeled_differently` to match the new advisory context API.
- **`tests/test_analyzer.py`** — Removed stray `ferc="314"` from Level-4 "Machinery" fixture
  header, resolving a test failure introduced during FERC refactor. All 86 tests now pass.
- **`tests/test_description_generator.py`** — New test module for `description_generator.py`.

---

## [0.1c] — 2026-03-09

### Added

- **`tools/extract_ferc_pdf.py`** — One-time utility script that uses `pdfplumber` to extract
  FERC account codes and descriptions from `resources/18 CFR Part 101 (up to date as of 3-06-2026).pdf`
  and writes them to `resources/ferc_uniform_system.csv`. Run once offline; the resulting CSV is
  committed and loaded by the app at runtime.
- **`requirements-dev.txt`** — Dev-only dependency file. Adds `pdfplumber>=0.10.0` for use with
  `tools/extract_ferc_pdf.py`. Not required to run the application.

### Changed

- **`coa_architect/cli.py`** — Added auto-detect logic: on startup, if
  `resources/ferc_uniform_system.csv` is present alongside the app, it is loaded automatically
  without requiring the `--ferc-ref` CLI flag. Falls through to the manual prompt only when the
  file is absent.
- **`coa_architect/loader.py`** — Added `_parse_business_unit_sheet()`: a dedicated parser for
  the Business Unit reference sheet, which uses a variable-length header section rather than a
  fixed layout. Scans for the header row containing "Business Unit Number", then reads subsequent
  data rows using the detected column positions. Falls back to the generic parser if no recognised
  header is found. Updated `load_references()` to call this method instead of the generic
  `load_ref("business_units")`.
- **`coa_architect/placer.py`** — Added optional `bu_type` parameter to
  `score_parent_candidates()` and `_score_candidate()`. When `bu_type` is known (IS or BS),
  candidates are hard-filtered to matching accounts before scoring, and BU type consistency points
  use an exact match instead of the majority-heuristic fallback. No behaviour change when
  `bu_type` is `None`.
- **`coa_architect/suggester.py`** — Fixed indentation bug in `fill_defaults()`: reasoning
  entries for `bu_type`, `company`, and `business_unit` were being overwritten even when the
  proposal already carried a user-supplied value. Reasoning is now recorded only when the
  suggested value is also newly assigned.

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
