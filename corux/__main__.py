"""CLI entrypoint:  python -m corux <input.json> [--literature] [--no-persist]"""

from __future__ import annotations

import argparse
import json
import sys

from dotenv import load_dotenv

from .pipeline import run


def main(argv: list[str] | None = None) -> int:
    load_dotenv()  # pick up ANTHROPIC_API_KEY from .env

    parser = argparse.ArgumentParser(prog="corux", description="CORUX lab interpretation pipeline")
    parser.add_argument("input", help="Path to analyzer output JSON")
    parser.add_argument(
        "--literature", action="store_true", help="Enable the literature-consultation step"
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Do not read/write the longitudinal store (use only reports in this file)",
    )
    args = parser.parse_args(argv)

    result = run(
        args.input,
        literature_enabled=args.literature,
        persist=not args.no_persist,
    )

    output = {
        "patient_key": result.patient.patient_key,
        "visits_on_record": result.visits,
        "notes": result.notes,
        "interpretation": result.final.model_dump(),
    }
    print(json.dumps(output, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
