# CoA Architect

**A guided CLI tool for safely extending the Silver Dolphins LLP Chart of Accounts.**

Built for ACG 6415 — designed for accountants, not developers. CoA Architect reads an existing Chart of Accounts Excel file, learns its structure automatically, and walks users step-by-step through adding a new Level-5 GL posting account — enforcing hierarchy rules, preventing gap-range violations, and suggesting evidence-based codes at every step.

---

## The Problem It Solves

Manual edits to a Chart of Accounts risk:
- Placing accounts in **undefined number gaps** (no parent range)
- Assigning **wrong FERC, asset life, or cash flow codes**
- **Breaking the hierarchy** by skipping levels or mis-parenting accounts
- **Overwriting** the file without a backup

CoA Architect eliminates these risks with automated structure analysis, safe number selection, and a backup-first save strategy.

---

## Features

| Feature | Description |
|---|---|
| Auto-detection | Reads column headers and hierarchy from the existing file — no configuration needed |
| Safe number selection | Only suggests numbers inside a defined parent range; rejects gaps and duplicates |
| Evidence-based suggestions | Recommends FERC codes, asset life, and cash flow categories from sibling accounts and description keywords |
| Field-by-field review | Accept, modify, or skip each suggestion before saving |
| Backup-first save | Timestamped backup created before any write operation |
| External FERC support | Optionally merges additional FERC codes from a user-supplied CSV or Excel file |
| Interactive UI | Arrow-key menus and validated prompts via `questionary` and `rich` |

---

## Requirements

- Python 3.10+
- pip packages: `openpyxl`, `questionary`, `rich`, `pytest`

---

## Installation

```bash
git clone https://github.com/mattcast480/ACG6415-Silver-Dolphins.git
cd ACG6415-Silver-Dolphins
pip install -r requirements.txt
```

---

## Usage

```bash
# Prompts for the file path interactively
python main.py

# Pass the CoA file directly
python main.py --file ../Silver_Dolphins_CoA.xlsx

# With an optional external FERC reference file
python main.py --file ../Silver_Dolphins_CoA.xlsx --ferc-ref ferc_codes.csv
```

### Arguments

| Argument | Description |
|---|---|
| `--file`, `-f` | Path to the Chart of Accounts `.xlsx` file |
| `--ferc-ref` | Optional external FERC code file (CSV or Excel) with `Code` and `Description` columns |

---

## Example Session

```
╔══════════════════════════════════════════════════╗
║           CoA Architect v1.0                     ║
║  Safe Chart of Accounts extension tool           ║
╚══════════════════════════════════════════════════╝

CoA file:   Silver_Dolphins_CoA.xlsx
FERC ref:   (none)

Loaded 99 accounts across 7 sections.
Hierarchy: L1×7  L2×7  L3×11  L4×11  L5×63

Describe the new account: offshore wind turbine installation

Top parent candidates:
  1. [82%] 102000 — Machinery and Equipment
              ASSETS > Long-Term Assets > PP&E > Machinery and Equipment
  2. [74%] 100002 — Property Plant and Equipment

Select parent: 102000 — Machinery and Equipment

Suggested numbers (range 102000–104999, last sibling: 103400):
  1. 103500  (+100 after last sibling — dominant spacing)
  2. 104000  (next round multiple-of-1000)

Select number: 103500

  Description:   Offshore Wind Turbines         [Accept]
  Company:       10 — Admin Services            [Accept]
  BU Type:       BS                             [Accept]
  FERC Code:     314 — Turbogenerator units     [85% — siblings use 314]
  Asset Life:    300 — 25 Years                 [Accept]
  Cash Flow:     INV — Investing Activities     [Accept]

Add to CoA and save? [Y/n]: y
Backup saved: Silver_Dolphins_CoA_backup_20260303_142255.xlsx
Account 103500 — Offshore Wind Turbines added. File saved.
```

---

## Project Structure

```
ACG6415-Silver-Dolphins/
├── main.py                    # Entry point — CLI argument parsing
├── requirements.txt           # Annotated dependencies
├── README.md
├── CHANGELOG.md
├── coa_architect/
│   ├── models.py              # Dataclasses: Account, AccountRange, AccountHierarchy, etc.
│   ├── loader.py              # Reads Excel → Python objects; auto-detects columns
│   ├── analyzer.py            # Backward-scan hierarchy builder; range + pattern detection
│   ├── placer.py              # Parent scoring; safe account number candidates
│   ├── suggester.py           # FERC, asset life, cash flow, BU type suggestions
│   ├── validator.py           # Four-rule account number safety checks
│   ├── cli.py                 # Interactive terminal session (questionary + rich)
│   └── exporter.py            # Row insertion, ID re-sequencing, backup + save
└── tests/
    ├── test_loader.py
    ├── test_analyzer.py
    ├── test_placer.py
    └── test_suggester.py
```

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Business Rules Enforced

1. Account numbers must be **6 digits** (100000–999999)
2. Numbers must **not already be in use**
3. Numbers must fall **inside a defined parent range** — gap numbers are rejected with an explanation
4. New accounts are always **Level 5** (posting / leaf accounts)
5. The original Excel file is **never overwritten without a timestamped backup**

---

## Course Context

This tool was developed as part of **ACG 6415** to demonstrate applied accounting information systems design — combining GL account structure knowledge with practical Python tooling.
