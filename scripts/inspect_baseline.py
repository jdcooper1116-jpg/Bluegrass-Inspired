from __future__ import annotations

import argparse
import json

from bluegrass.research.baseline import (
    baseline_packet_summary,
    filter_priority_shortlist,
    load_baseline_combinations,
    load_baseline_pairs,
    load_baseline_runs,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Bluegrass baseline packet")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("summary", help="Show packet summary")

    counts = subparsers.add_parser("counts", help="Show row counts")
    counts.add_argument("--pretty", action="store_true")

    shortlist = subparsers.add_parser("shortlist", help="Show priority shortlist")
    shortlist.add_argument("--item-type", choices=["pair", "combination"], default=None)
    shortlist.add_argument("--session", choices=["Midday", "Evening", "Night"], default=None)
    shortlist.add_argument("--subtype", default=None)
    shortlist.add_argument("--limit", type=int, default=10)

    args = parser.parse_args()

    if args.command == "summary":
        print(json.dumps(baseline_packet_summary(), indent=2))
        return

    if args.command == "counts":
        payload = {
            "runs": len(load_baseline_runs()),
            "pairs": len(load_baseline_pairs()),
            "combinations": len(load_baseline_combinations()),
        }
        print(json.dumps(payload, indent=2 if args.pretty else None))
        return

    if args.command == "shortlist":
        rows = filter_priority_shortlist(
            item_type=args.item_type,
            session=args.session,
            subtype=args.subtype,
            limit=args.limit,
        )
        print(json.dumps(rows, indent=2))
        return


if __name__ == "__main__":
    main()
