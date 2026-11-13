"""Regenerate the shipped structure schema and each example's schema and Python types, and pin links into this
repository to the release tag of the current version, so the README, the skill and the examples match the release."""

import json
import re
import tomllib
from pathlib import Path

from rulegrid import check, load
from rulegrid.generate import generate, structure_schema
from rulegrid.policy import load_structure

ROOT = Path(__file__).resolve().parents[1]


def pin(path: Path, tag: str) -> None:
    text = path.read_text()
    text = re.sub(r"(the-marshmallow-project/rulegrid(?:/blob|/tree)?)/(?:main|v[\d.]+)/", rf"\1/{tag}/", text)
    text = re.sub(r"(npx skills add the-marshmallow-project/rulegrid)(?:@v[\d.]+)?", rf"\1@{tag}", text)
    path.write_text(text)


def main() -> None:
    tag = "v" + tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    for path in [ROOT / "README.md", ROOT / "skills/rulegrid/SKILL.md", *(ROOT / "examples").glob("*/structure.yaml")]:
        pin(path, tag)
    schema = ROOT / "src/rulegrid/schemas/structure.schema.json"
    schema.write_text(json.dumps(structure_schema(), indent=2, ensure_ascii=False) + "\n")
    for structure in sorted((ROOT / "examples").glob("*/structure.yaml")):
        generate(load_structure(structure))
    for profile in sorted((ROOT / "examples").glob("*/profiles/*/profile.yaml")):
        if problems := check(load(profile.parent)):
            raise SystemExit("\n".join(map(str, problems)))


if __name__ == "__main__":
    main()
