"""Static checks of a loaded policy, which need no model.

`load` already refuses a profile that does not fit its structure: unknown or missing ids, missing cells, a lexicon
reminding an unknown prohibition. `check` adds what a loadable policy can still get wrong.
"""

from __future__ import annotations

from rulegrid.generate import generated
from rulegrid.policy import Example, Policy
from rulegrid.types import Problem


def check(policy: Policy) -> list[Problem]:
    """Examples missing the response their position needs, and generated files out of date with the structure."""
    problems: list[Problem] = []
    responded: list[tuple[str, tuple[Example, ...]]] = [
        (f"tiers.{cell.id.replace('/', '.')}", cell.examples)
        for t in policy.tiers.values()
        for cell in t.cells.values()
    ]
    responded += [(f"prohibitions.{p.id}", p.valid + p.invalid) for p in policy.prohibitions.values()]
    responded += [(f"response_axes.{a.id}.{v.id}", v.examples) for a in policy.response_axes.values() for v in a.values]
    problems += [
        Problem(where, f"example without a response: {e.turn!r}")
        for where, examples in responded
        for e in examples
        if e.response is None
    ]
    for name, text in generated(policy.structure).items():
        path = policy.root / name
        if path.exists() and path.read_text() != text:
            problems.append(Problem(name, "out of date with structure.yaml: run `rulegrid generate`"))
    return problems
