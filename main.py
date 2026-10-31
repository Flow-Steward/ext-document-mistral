from __future__ import annotations

import json
import sys
from typing import Any

from mistral_extension import handle_payload


def main() -> int:
    try:
        payload: dict[str, Any] = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError as exc:
        response = {
            "ok": False,
            "error_code": "invalid_json",
            "error": f"Malformed JSON input: {exc.msg}",
            "errors": [
                {
                    "code": "invalid_json",
                    "message": f"Malformed JSON input: {exc.msg}",
                }
            ],
        }
        print(json.dumps(response, ensure_ascii=False, separators=(",", ":")))
        return 2
    if not isinstance(payload, dict):
        response = {
            "ok": False,
            "error_code": "invalid_payload",
            "error": "Input payload must be a JSON object",
            "errors": [
                {
                    "code": "invalid_payload",
                    "message": "Input payload must be a JSON object",
                }
            ],
        }
    else:
        response = handle_payload(payload)
    print(json.dumps(response, ensure_ascii=False, separators=(",", ":")))
    return 0 if response.get("ok") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
