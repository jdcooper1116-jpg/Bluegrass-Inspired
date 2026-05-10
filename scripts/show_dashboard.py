from __future__ import annotations

import json

from bluegrass.app.dashboard import get_dashboard_payload


if __name__ == "__main__":
    print(json.dumps(get_dashboard_payload(), indent=2))
