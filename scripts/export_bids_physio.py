"""Export audited MRI run windows from a private manifest (see physio.bids)."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from physio.bids import export_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="Private JSON containing audited run onsets and PMU paths")
    parser.add_argument("--out", required=True, help="Separate output root; existing files are never overwritten")
    parser.add_argument("--report", type=Path, help="Optional new private JSON report; contains run identifiers")
    args = parser.parse_args()
    if args.report is not None and args.report.exists():
        parser.error("Choose a new report path; existing files are never overwritten")
    try:
        report = export_manifest(args.manifest, args.out)
    except ValueError as exc:
        parser.exit(2, f"Export rejected: {exc}\n")
    except OSError:
        parser.exit(2, "Export rejected: manifest or output is inaccessible\n")
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 1 if report["rejected"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
