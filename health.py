from __future__ import annotations

import json


def check_health() -> dict:
    return {"ok": True, "status": "healthy"}


if __name__ == "__main__":
    print(json.dumps(check_health(), separators=(",", ":")))
