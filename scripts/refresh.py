"""Regenerate the shipped structure schema and each example's schema and Python types."""

import json
from pathlib import Path

from rulegrid import check, load
from rulegrid.generate import generate, structure_schema

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    schema = ROOT / "src/rulegrid/schemas/structure.schema.json"
    schema.write_text(json.dumps(structure_schema(), indent=2, ensure_ascii=False) + "\n")
    for profile in sorted((ROOT / "examples").glob("*/profiles/*/profile.yaml")):
        policy = load(profile.parent)
        generate(policy)
        if problems := check(policy):
            raise SystemExit("\n".join(map(str, problems)))


if __name__ == "__main__":
    main()
