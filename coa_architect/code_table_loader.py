"""
code_table_loader.py — Scans the 1.code_tables/ folder and loads advisory reference files.

Advisory files are keyed by column name (e.g., 'FERC Code.pdf' maps to the 'FERC Code'
column).  They provide richer descriptions that augment, but never override, the
authoritative code lists embedded in the CoA workbook tabs.

Supported formats: CSV, Excel (.xlsx / .xls), PDF (text-based only).

Matching rule: filename stem must match an actual column header from the CoA main sheet,
case-insensitively and character-for-character (spaces allowed; hyphens are not interchangeable
with spaces).  For example:
  'ferc code.pdf'  → matches 'FERC Code'   ✓
  'ferc-code.pdf'  → does NOT match        ✗
"""

import csv
import os
import re

import openpyxl


# ---------------------------------------------------------------------------
# Internal field names that have advisory logic implemented in suggester.py
# Columns not in this set are loaded but flagged as having no advisory effect.
# ---------------------------------------------------------------------------
ADVISORY_LOGIC_FIELDS = {
    "ferc_code",
    "asset_life",
    "cash_flow_category",
    "book_tax_difference",
    "posting_edit",
}

# ---------------------------------------------------------------------------
# PDF regex patterns — copied from tools/extract_ferc_pdf.py
# (tools/ is not a package so we cannot import from it at runtime)
# ---------------------------------------------------------------------------

# Matches lines like:  "101   Electric plant in service"
TABULAR_RE = re.compile(
    r"^\s*(\d{2,4}(?:\.\d{1,2})?)\s{2,}(.+)$"
)

# Matches lines like:  "Account 101. Electric Plant in Service."
HEADER_RE = re.compile(
    r"(?i)\bAccount\s+(?:No\.?\s*)?(\d{2,4}(?:\.\d{1,2})?)[.\s\-–]+(.+)"
)

# Matches lines that are purely a code (description may wrap to the next line)
CODE_ONLY_RE = re.compile(
    r"^\s*(\d{2,4}(?:\.\d{1,2})?)\s*$"
)


def _clean_description(text: str) -> str:
    """
    Strips trailing punctuation artifacts and extra whitespace from text
    extracted by pdfplumber (which sometimes introduces extra spaces).
    """
    # Collapse runs of whitespace to a single space
    text = re.sub(r"\s+", " ", text).strip()
    # Remove trailing period that looks like a section terminator
    text = text.rstrip(".")
    return text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_actual_column_headers(worksheet) -> list:
    """
    Reads row 1 of the given worksheet and returns a list of raw header strings
    (whitespace stripped, non-empty cells only).

    These are the strings that file stems in 1.code_tables/ are matched against.
    """
    headers = []
    for cell in worksheet[1]:
        if cell.value is not None:
            headers.append(str(cell.value).strip())
    return headers


def scan_code_tables(folder_path: str, column_headers: list) -> tuple:
    """
    Scans folder_path for advisory reference files and matches them to column headers.

    Matching is case-insensitive on the filename stem vs each header string.
    Supported extensions: .csv, .xlsx, .xls, .pdf

    Returns a 3-tuple:
      matches      — {column_header: file_path}  — exactly one file per column
      conflicts    — {column_header: [file_path, ...]}  — two or more files matched
      unrecognized — [file_path, ...]  — no column matched
    """
    supported_exts = {".csv", ".xlsx", ".xls", ".pdf"}

    # Build case-insensitive lookup:  header_lower → original header string
    header_lower_map = {h.lower(): h for h in column_headers}

    # First pass: accumulate all matched paths per column
    all_matches: dict = {}   # column_header → [file_path, ...]
    unrecognized: list = []

    if not os.path.isdir(folder_path):
        return {}, {}, []

    for filename in sorted(os.listdir(folder_path)):
        ext = os.path.splitext(filename)[1].lower()
        if ext not in supported_exts:
            continue  # Skip non-supported files silently

        stem = os.path.splitext(filename)[0]   # filename without extension
        stem_lower = stem.lower()

        if stem_lower in header_lower_map:
            col_header = header_lower_map[stem_lower]
            file_path = os.path.join(folder_path, filename)
            all_matches.setdefault(col_header, []).append(file_path)
        else:
            unrecognized.append(os.path.join(folder_path, filename))

    # Split into unambiguous matches and conflicts
    matches: dict = {}
    conflicts: dict = {}
    for col_header, paths in all_matches.items():
        if len(paths) == 1:
            matches[col_header] = paths[0]
        else:
            conflicts[col_header] = paths

    return matches, conflicts, unrecognized


def load_advisory_file(file_path: str) -> tuple:
    """
    Loads an advisory reference file and returns (content, error_message).

    content:
      - dict {code: description}  if the file has structured Code/Description columns
      - str                        if the file has text but no structured columns
      - None                       if parsing completely failed

    error_message:
      - None on success
      - str explaining the problem on failure
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".csv":
        return _load_csv(file_path)
    elif ext in (".xlsx", ".xls"):
        return _load_excel(file_path)
    elif ext == ".pdf":
        return _load_pdf(file_path)
    else:
        return None, f"Unsupported file format: '{ext}'"


def build_advisory_context(matches: dict, loaded_data: dict) -> dict:
    """
    Builds the final advisory context dict from matched files and loaded data.

    Returns {column_header: content} for each column whose file loaded successfully.
    Columns whose files failed to load are absent from the result.
    """
    result = {}
    for col_header in matches:
        content = loaded_data.get(col_header)
        if content is not None:
            result[col_header] = content
    return result


# ---------------------------------------------------------------------------
# Private loaders
# ---------------------------------------------------------------------------

def _load_csv(file_path: str) -> tuple:
    """
    Reads a CSV advisory file.

    If the CSV has 'Code' and 'Description' columns (case-insensitive), returns
    a {code: description} dict.  Otherwise falls back to returning raw text.
    """
    try:
        with open(file_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            # Build case-insensitive map of fieldname → actual key
            fieldnames_lower = {k.lower(): k for k in (reader.fieldnames or [])}
            code_key = fieldnames_lower.get("code")
            desc_key = fieldnames_lower.get("description")

            if code_key is None:
                # No 'Code' column — return raw text as fallback
                f.seek(0)
                raw = f.read()
                return (raw if raw.strip() else None), None

            result = {}
            for row in reader:
                code = str(row.get(code_key, "")).strip()
                desc = str(row.get(desc_key, "")).strip() if desc_key else ""
                if code:
                    result[code] = desc

            if not result:
                return None, "CSV has a 'Code' column but no data rows were found."
            return result, None

    except Exception as exc:
        return None, f"Could not read CSV: {exc}"


def _load_excel(file_path: str) -> tuple:
    """
    Reads an Excel advisory file (.xlsx / .xls).

    If the first sheet has 'Code' and 'Description' headers (case-insensitive),
    returns a {code: description} dict.  Otherwise returns raw concatenated text.
    """
    try:
        wb = openpyxl.load_workbook(file_path, data_only=True)
        ws = wb.worksheets[0]

        # Read header row to find Code / Description columns
        header = {}
        for cell in ws[1]:
            if cell.value:
                header[str(cell.value).strip().lower()] = cell.column_letter

        code_col = header.get("code")
        desc_col = header.get("description")

        if code_col is None:
            # No 'Code' column — return raw text from all cells as fallback
            rows_text = []
            for row in ws.iter_rows(values_only=True):
                row_text = "  ".join(str(c) for c in row if c is not None)
                if row_text.strip():
                    rows_text.append(row_text.strip())
            raw = "\n".join(rows_text)
            return (raw if raw.strip() else None), None

        result = {}
        for row in ws.iter_rows(min_row=2):
            row_dict = {cell.column_letter: cell for cell in row}
            code_cell = row_dict.get(code_col)
            if code_cell is None or code_cell.value is None:
                continue
            code = str(code_cell.value).strip()
            desc = ""
            if desc_col and row_dict.get(desc_col) and row_dict[desc_col].value:
                desc = str(row_dict[desc_col].value).strip()
            if code:
                result[code] = desc

        if not result:
            return None, "Excel file has a 'Code' column but no data rows were found."
        return result, None

    except Exception as exc:
        return None, f"Could not read Excel file: {exc}"


def _load_pdf(file_path: str) -> tuple:
    """
    Reads a text-based PDF advisory file using pdfplumber and the same regex
    patterns used by tools/extract_ferc_pdf.py.

    Returns a {code: description} dict if structured entries are found.
    Falls back to returning raw extracted text if no structured entries are found.
    Returns (None, error_message) if the PDF cannot be read at all.
    """
    try:
        import pdfplumber  # noqa: PLC0415 — deferred import; pdfplumber is optional
    except ImportError:
        return None, "pdfplumber is not installed. Run: pip install pdfplumber"

    try:
        accounts_tabular: dict = {}   # from Style A patterns (preferred)
        accounts_header: dict = {}    # from Style B patterns (fallback)

        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                lines = text.splitlines()

                # Track a "pending code" in case a code appears alone on a line
                # and its description continues on the next line.
                pending_code = None

                for line in lines:
                    # --- Resolve any pending lone code from the previous line ---
                    if pending_code is not None:
                        stripped = line.strip()
                        if (stripped
                                and not CODE_ONLY_RE.match(line)
                                and not TABULAR_RE.match(line)):
                            desc = _clean_description(stripped)
                            if desc:
                                accounts_tabular.setdefault(pending_code, desc)
                        pending_code = None

                    # --- Style A: tabular "101   Description" ---
                    m = TABULAR_RE.match(line)
                    if m:
                        code = m.group(1).strip()
                        desc = _clean_description(m.group(2))
                        if desc:
                            accounts_tabular.setdefault(code, desc)
                        continue

                    # --- Lone code on a line (description may wrap to next line) ---
                    m2 = CODE_ONLY_RE.match(line)
                    if m2:
                        pending_code = m2.group(1).strip()
                        continue

                    # --- Style B: "Account 101. Description" ---
                    m3 = HEADER_RE.search(line)
                    if m3:
                        code = m3.group(1).strip()
                        desc = _clean_description(m3.group(2))
                        if desc and code not in accounts_header:
                            accounts_header[code] = desc

        # Merge: tabular entries take precedence over header-style entries
        merged: dict = {}
        for code, desc in accounts_header.items():
            merged[code] = desc
        for code, desc in accounts_tabular.items():
            merged[code] = desc  # overwrites header entry if both found

        if merged:
            return merged, None

        # No structured entries found — try returning raw extracted text
        raw_pages = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                if page_text.strip():
                    raw_pages.append(page_text)

        raw_text = "\n".join(raw_pages)
        if raw_text.strip():
            return raw_text, None

        # PDF opened but produced no text at all — likely a scanned image
        return None, (
            "PDF appears to be image-based (no extractable text). "
            "Only text-based PDFs are supported."
        )

    except Exception as exc:
        return None, f"Could not read PDF: {exc}"
