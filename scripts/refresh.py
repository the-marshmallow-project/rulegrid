"""Regenerate the shipped structure schema and each example's schema and Python types."""

import json
from pathlib import Path

from rulegrid import check, load
from rulegrid.generate import generate, structure_schema
from rulegrid.policy import load_structure

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    schema = ROOT / "src/rulegrid/schemas/structure.schema.json"
    schema.write_text(json.dumps(structure_schema(), indent=2, ensure_ascii=False) + "\n")
    for structure in sorted((ROOT / "examples").glob("*/structure.yaml")):
        generate(load_structure(structure))
    for profile in sorted((ROOT / "examples").glob("*/profiles/*/profile.yaml")):
        if problems := check(load(profile.parent)):
            raise SystemExit("\n".join(map(str, problems)))


if __name__ == "__main__":
    main()
