# CoA Architect

**Safely extend the Silver Dolphins LLP Chart of Accounts.**

CoA Architect is an interactive Python CLI tool that reads the existing Chart of Accounts Excel file, learns its structure automatically, then guides accountants step-by-step through adding a new Level-5 posting account — with safe number selection and evidence-based code suggestions.

---

## Features

- **Automatic structure detection** — reads hierarchy levels, account ranges, and naming patterns from the existing CoA
- **Safe number selection** — only suggests account numbers within defined ranges; rejects gap numbers and duplicates
- **Evidence-based suggestions** — recommends FERC codes, asset life, cash flow categories based on sibling accounts and description keywords
- **Backup-first saving** — creates a timestamped backup before writing any changes
- **External FERC reference** — optionally loads additional FERC codes from a user-supplied CSV or Excel file
- **Interactive terminal UI** — arrow-key menus and validated text prompts via `questionary` and `rich`

---

## Requirements

- Python 3.10+
- Dependencies listed in `requirements.txt`

| Library | Version | Purpose |
|---|---|---|
| `openpyxl` | ≥3.1.0 | Read/write `.xlsx`; preserves formatting |
| `questionary` | ≥2.0.1 | Arrow-key select menus and validated text prompts |
| `rich` | ≥13.0.0 | Formatted tables, panels, styled terminal output |
| `pytest` | ≥7.0.0 | Unit testing |

---

## Installation

```bash
cd ACG6415-Silver-Dolphins
pip install -r requirements.txt
```

---

## Usage

### Basic (prompts for file path interactively)
```bash
python main.py
```

### With CoA file specified
```bash
python main.py --file ../Silver_Dolphins_CoA.xlsx
```

### With optional external FERC reference file
```bash
python main.py --file ../Silver_Dolphins_CoA.xlsx --ferc-ref ferc_codes.csv
```

### Command-line arguments

| Argument | Description |
|---|---|
| `--file`, `-f` | Path to the Chart of Accounts Excel file (`.xlsx`) |
| `--ferc-ref` | Optional external FERC reference file (CSV or Excel) with `Code` and `Description` columns |

---

## Session Walkthrough

```
CoA Architect v1.0
==================
CoA file:   Silver_Dolphins_CoA.xlsx
FERC ref:   (none)

Loaded 99 accounts across 7 sections.
Hierarchy: L1×7  L2×7  L3×11  L4×11  L5×63

Describe the new account: offshore wind turbine installation

Top parent candidates:
  1. [82%] 102000 — Machinery and Equipment
              ASSETS > Long-Term Assets > PP&E > Machinery and Equipment
  2. [74%] 100002 — Property Plant and Equipment
  ...
Select parent: 102000 — Machinery and Equipment

Suggested numbers (range 102000–104999, last sibling: 103400):
  1. 103500  (+100 after last sibling — dominant spacing)
  2. 104000  (next round multiple-of-1000)
Select number: 103500

[field-by-field confirmation with Accept / Modify / Skip]

┌──────────────────────────────────────────────────┐
│  Account 103500 — Offshore Wind Turbines         │
│  ASSETS > Long-Term Assets > PP&E >              │
│    Machinery and Equipment                       │
└──────────────────────────────────────────────────┘
Add to CoA and save? [Y/n]: y
Backup saved: Silver_Dolphins_CoA_backup_20260303_142255.xlsx
Account 103500 added. File saved.
```

---

## Project Structure

```
ACG6415-Silver-Dolphins/
├── main.py                   # Entry point — CLI arg parsing
├── requirements.txt
├── README.md
├── CHANGELOG.md
├── coa_architect/
│   ├── __init__.py
│   ├── models.py             # Dataclasses: Account, AccountRange, etc.
│   ├── loader.py             # Read Excel → Python objects (openpyxl)
│   ├── analyzer.py           # Build hierarchy, detect ranges + patterns
│   ├── placer.py             # Score parent candidates, suggest safe numbers
│   ├── suggester.py          # Suggest FERC, Asset Life, Cash Flow codes
│   ├── validator.py          # Validate account numbers and code values
│   ├── cli.py                # Interactive terminal UI (questionary + rich)
│   └── exporter.py           # Write updated CoA back to Excel with backup
└── tests/
    ├── test_loader.py
    ├── test_analyzer.py
    ├── test_placer.py
    └── test_suggester.py
```

---

## Running Tests

```bash
cd ACG6415-Silver-Dolphins
pytest tests/ -v
```

Individual test files:
```bash
pytest tests/test_loader.py -v
pytest tests/test_analyzer.py -v
pytest tests/test_placer.py -v
pytest tests/test_suggester.py -v
```

---

## Key Business Rules

1. **6-digit account numbers only** — must be between 100000 and 999999
2. **No duplicate account numbers** — rejects any number already in use
3. **No gap numbers** — rejects numbers that fall between defined account ranges (undefined territory)
4. **Parent-range constraint** — suggested numbers always fall within the chosen parent's owned range
5. **Level-5 posting accounts** — all new accounts added via this tool are Level-5 (leaf) accounts
6. **Backup before save** — original file is never overwritten without a timestamped backup

---

## External FERC Reference File Format

If loading additional FERC codes from an external file, the file must have `Code` and `Description` columns (case-insensitive header matching):

**CSV example:**
```csv
Code,Description
314,Turbogenerator units
331,Structures and improvements
```

**Excel:** Same format, first row = headers.

External codes that duplicate codes already in the CoA are ignored (CoA-embedded codes take precedence). External-only codes appear in suggestions labeled *"From external reference file"* at lower confidence.
