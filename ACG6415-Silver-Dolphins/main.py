"""
main.py — Entry point for CoA Architect.

Usage:
    python main.py --file path/to/Silver_Dolphins_CoA.xlsx
    python main.py --file path/to/Silver_Dolphins_CoA.xlsx --ferc-ref path/to/ferc_codes.csv

Arguments:
    --file, -f       Path to the Chart of Accounts Excel file (required or prompted).
    --ferc-ref       Optional path to an external FERC reference file (CSV or Excel).

If --file is not provided, the CLI will prompt for it interactively.
"""

import argparse
import sys

from coa_architect.cli import CoAArchitectCLI


def build_arg_parser() -> argparse.ArgumentParser:
    """
    Defines and returns the command-line argument parser.

    Arguments are optional — the CLI will prompt for anything not provided.
    """
    parser = argparse.ArgumentParser(
        prog="coa-architect",
        description=(
            "CoA Architect — Safely extend the Silver Dolphins Chart of Accounts.\n"
            "Guides you step-by-step through adding a new Level-5 posting account\n"
            "with evidence-based suggestions for FERC codes, asset life, and more."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--file", "-f",
        metavar="PATH",
        help="Path to the Chart of Accounts Excel file (.xlsx)",
        default=None,
    )

    parser.add_argument(
        "--ferc-ref",
        metavar="PATH",
        help="Optional external FERC reference file (CSV or Excel) with 'Code' and 'Description' columns",
        default=None,
    )

    return parser


def main() -> None:
    """
    Parses command-line arguments and launches the interactive CLI session.
    """
    parser = build_arg_parser()
    args, _ = parser.parse_known_args()

    # Instantiate and run the CLI
    app = CoAArchitectCLI(
        file_path=args.file,
        ferc_ref_path=args.ferc_ref,
    )

    try:
        app.run()
    except KeyboardInterrupt:
        # Handle Ctrl+C gracefully — no stack trace shown to the user
        print("\n\nSession interrupted. File not changed.")
        sys.exit(0)
    except FileNotFoundError as e:
        print(f"\nError: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        raise  # Re-raise for debugging; remove in production if desired


if __name__ == "__main__":
    main()
