"""Export the OpenAPI schema (source of truth for packages/contracts).

python -m edge_api.export_openapi packages/contracts/openapi.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from edge_api.main import create_app


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else Path("packages/contracts/openapi.json")
    schema = create_app().openapi()
    target.write_text(json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
