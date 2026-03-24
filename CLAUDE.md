# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

Active development — v1.0 released 2026-03-24. All 86 tests passing.

## Project Overview

CoA Architect is an interactive CLI tool for adding accounts to a Chart of Accounts
Excel workbook. Given a new account name and parent, it suggests an account number
(based on the existing hierarchy's spacing patterns), FERC uniform system code, asset
life, cash flow category, posting edit code, and other fields. The user confirms or
overrides each field before the new row is inserted and saved. Advisory context (FERC
codes, asset life tables, etc.) is loaded from a `1.code_tables/` folder at startup.

## Commands

- **Run the app:** `python main.py --file <path_to_coa_workbook.xlsx>`
- **Run tests:** `python -m pytest tests/`
- At the start of every new session, automatically run `git pull origin master` to ensure local files are up to date with the GitHub remote.
- After completing each major development milestone, ask the user: "Do you want to continue to the next task, or are you ending the session?" If the user indicates they are ending the session, remind them to commit all changes and push to GitHub, and suggest an appropriate version tag and commit message summarizing what was built during the session. Always apply a human-readable git tag matching the version number (e.g. `v0.1d`) and push it: `git tag <version> && git push origin <version>`. Before committing at session end, update `VERSION` in `coa_architect/cli.py` to match the version tag being applied (e.g. if tagging `v0.3`, set `VERSION = "0.3"`). This keeps the in-app banner in sync with the git tag.
- Maintain a CHANGELOG.md file
- Present options and ask clarifying questions - do not automate all decisions
- Use descriptive names for all functions and variables
- When pushing to GitHub, always run git pull origin master before git push to avoid sync conflicts.
## Architecture

Main modules in `coa_architect/`:

| Module | Role |
|--------|------|
| `loader.py` | Reads the CoA Excel workbook and all reference sheets into Python objects |
| `analyzer.py` | Builds the account hierarchy, range ownership, spacing patterns, and FERC usage map |
| `placer.py` | Scores parent candidates and finds safe account numbers within a parent range |
| `validator.py` | Enforces safety rules (6-digit, not-in-use, within-range, not-a-header-boundary) |
| `suggester.py` | Suggests FERC codes, asset life, cash flow category, and other fields |
| `exporter.py` | Inserts the new row in sorted position, copies formatting, and saves the workbook |
| `cli.py` | Interactive session loop: field-by-field confirmation, multi-account workflow |
| `code_table_loader.py` | Scans `1.code_tables/` for advisory CSVs/PDFs and builds an advisory context dict |

## Code Style

- Always include comments in code explaining what each section does.
- Write comments as if explaining to someone learning the code for the first time.
- Use Python as the programming language.
- Build for portability (requirements.txt, README, etc.)
- Do not suggest account numbers in undefined or gap ranges
