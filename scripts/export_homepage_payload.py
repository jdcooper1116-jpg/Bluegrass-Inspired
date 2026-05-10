from __future__ import annotations

import json
from pathlib import Path

from bluegrass.app.dashboard import get_dashboard_payload


def main() -> None:
    output_dir = Path("data/processed")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / "homepage_payload.json"
    payload = get_dashboard_payload()

    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
