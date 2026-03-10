"""
extract_ferc_pdf.py — One-time utility to extract FERC account codes from the
18 CFR Part 101 PDF and write them to resources/ferc_uniform_system.csv.

Usage:
    pip install pdfplumber          # dev-only dependency
    python tools/extract_ferc_pdf.py

Output:
    resources/ferc_uniform_system.csv   (Code, Description)

This script is run ONCE offline.  The resulting CSV is then committed to the
repo and loaded by the app at runtime via --ferc-ref or auto-load logic.

How the extraction works:
    18 CFR Part 101 uses two styles for account entries:
      Style A (tabular):  lines like  "101   Electric plant in service"
      Style B (header):   lines like  "Account 101. Electric Plant in Service."
    The script tries both patterns, deduplicates, and sorts by code.

    Because PDF layout varies, a manual review pass is recommended before
    committing the output CSV.
"""

import csv
import os
import re
import sys

# ---------------------------------------------------------------------------
# Path setup — resolve paths relative to the repo root, not the tools/ dir
# ---------------------------------------------------------------------------

# The repo root is one level above this script (tools/)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF_PATH = os.path.join(REPO_ROOT, "resources", "18 CFR Part 101 (up to date as of 3-06-2026).pdf")
CSV_PATH = os.path.join(REPO_ROOT, "resources", "ferc_uniform_system.csv")


# ---------------------------------------------------------------------------
# Pattern matching helpers
# ---------------------------------------------------------------------------

# Matches lines like:  "101   Electric plant in service"
# Account codes may be integers or decimals like 101.1, 314.1, etc.
# The description text follows after whitespace.
TABULAR_RE = re.compile(
    r"^\s*(\d{2,4}(?:\.\d{1,2})?)\s{2,}(.+)$"
)

# Matches lines like:  "Account 101. Electric Plant in Service."
# or                   "Account No. 101 - Electric Plant"
HEADER_RE = re.compile(
    r"(?i)\bAccount\s+(?:No\.?\s*)?(\d{2,4}(?:\.\d{1,2})?)[.\s\-–]+(.+)"
)

# Matches lines that are purely a code (in case description wraps to next line)
CODE_ONLY_RE = re.compile(
    r"^\s*(\d{2,4}(?:\.\d{1,2})?)\s*$"
)


def clean_description(text: str) -> str:
    """
    Strips trailing punctuation artifacts and excessive whitespace from a
    description extracted from PDF text.
    """
    # Collapse internal whitespace (PDF extraction often introduces extra spaces)
    text = re.sub(r"\s+", " ", text).strip()
    # Remove trailing period if it looks like a section terminator rather than
    # part of the name (e.g., "Electric plant in service." → "Electric plant in service")
    text = text.rstrip(".")
    return text


def code_sort_key(code_str: str):
    """
    Returns a sort key so that codes sort numerically, e.g.:
        101 < 101.1 < 102 < 200 < 311 < 312 ...
    """
    parts = code_str.split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        major, minor = 0, 0
    return (major, minor)


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------

def extract_accounts(pdf_path: str) -> dict:
    """
    Opens the PDF with pdfplumber, scans every page for FERC account entries,
    and returns {code_str: description_str}.

    If two patterns match the same code, the tabular match is preferred because
    it is usually more precise (the header pattern sometimes picks up surrounding
    section headings as part of the description).
    """
    try:
        import pdfplumber  # noqa: PLC0415 — intentional deferred import
    except ImportError:
        print(
            "ERROR: pdfplumber is not installed.\n"
            "Install it with:  pip install pdfplumber\n"
            "This is a one-time dev dependency used only by this script."
        )
        sys.exit(1)

    accounts_tabular: dict[str, str] = {}   # from Style A patterns
    accounts_header: dict[str, str] = {}    # from Style B patterns

    print(f"Opening PDF: {pdf_path}")

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        print(f"Pages: {total_pages}")

        for page_num, page in enumerate(pdf.pages, start=1):
            # Extract text as plain lines; pdfplumber preserves column order
            text = page.extract_text() or ""
            lines = text.splitlines()

            # Track a "pending code" in case a code appears alone on a line
            # and the description is on the next line
            pending_code = None

            for line in lines:
                # --- Try to resolve a pending lone code ---
                if pending_code is not None:
                    stripped = line.strip()
                    # If the next line looks like a description (not another code,
                    # not a blank line, not a page header), use it
                    if stripped and not CODE_ONLY_RE.match(line) and not TABULAR_RE.match(line):
                        desc = clean_description(stripped)
                        if desc:
                            accounts_tabular.setdefault(pending_code, desc)
                    pending_code = None

                # --- Style A: tabular "101   Description" ---
                m = TABULAR_RE.match(line)
                if m:
                    code = m.group(1).strip()
                    desc = clean_description(m.group(2))
                    if desc:
                        accounts_tabular.setdefault(code, desc)
                    continue

                # --- Lone code on a line (description may wrap) ---
                m2 = CODE_ONLY_RE.match(line)
                if m2:
                    pending_code = m2.group(1).strip()
                    continue

                # --- Style B: "Account 101. Description" ---
                m3 = HEADER_RE.search(line)
                if m3:
                    code = m3.group(1).strip()
                    desc = clean_description(m3.group(2))
                    if desc and code not in accounts_header:
                        accounts_header[code] = desc

            if page_num % 10 == 0:
                print(f"  Processed page {page_num}/{total_pages}...")

    # Merge: tabular entries take precedence over header-style entries
    merged: dict[str, str] = {}
    for code, desc in accounts_header.items():
        merged[code] = desc
    for code, desc in accounts_tabular.items():
        merged[code] = desc   # overwrites header entry if both found

    print(f"Found {len(merged)} account codes.")
    return merged


def write_csv(accounts: dict, csv_path: str) -> None:
    """
    Writes {code: description} to a CSV file sorted numerically by code.
    """
    sorted_codes = sorted(accounts.keys(), key=code_sort_key)

    os.makedirs(os.path.dirname(csv_path), exist_ok=True)

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Code", "Description"])  # Header row
        for code in sorted_codes:
            writer.writerow([code, accounts[code]])

    print(f"Written {len(sorted_codes)} codes to: {csv_path}")


def main():
    """Entry point — validates inputs, runs extraction, writes output."""
    # Verify source PDF exists
    if not os.path.exists(PDF_PATH):
        print(f"ERROR: PDF not found at:\n  {PDF_PATH}")
        print("Make sure you are running this script from the repo root or tools/ directory.")
        sys.exit(1)

    # Warn if output CSV already exists
    if os.path.exists(CSV_PATH):
        response = input(
            f"Output file already exists:\n  {CSV_PATH}\nOverwrite? [y/N]: "
        ).strip().lower()
        if response != "y":
            print("Aborted.")
            sys.exit(0)

    # Run extraction
    accounts = extract_accounts(PDF_PATH)

    if not accounts:
        print(
            "WARNING: No accounts were extracted.  The PDF layout may not match\n"
            "the expected patterns.  Review extract_ferc_pdf.py and adjust the\n"
            "regex patterns if needed, or use Option A (manual extraction)."
        )
        sys.exit(1)

    # Write output
    write_csv(accounts, CSV_PATH)

    # Post-extraction guidance
    print(
        "\nNext steps:\n"
        "  1. Open resources/ferc_uniform_system.csv and review the entries.\n"
        "  2. Cross-check a sample against the PDF and the 76 codes in Silver_Dolphins_CoA.xlsx.\n"
        "  3. Fix any garbled descriptions caused by PDF layout artifacts.\n"
        "  4. Test with: python -m coa_architect --ferc-ref resources/ferc_uniform_system.csv\n"
        "  5. Commit the CSV once it looks correct."
    )


if __name__ == "__main__":
    main()
