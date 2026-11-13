"""Static checks of a loaded policy, which need no model.

`load` already refuses a profile that does not fit its structure: unknown or missing ids, missing cells, a lexicon
reminding an unknown prohibition. `check` adds what a loadable policy can still get wrong: cells that earlier tiers
make unreachable, examples missing a response, and generated files out of date.
"""

from __future__ import annotations

from rulegrid.generate import generated
from rulegrid.policy import Example, Policy, positions
from rulegrid.types import Problem


def _unreachable(policy: Policy) -> list[Problem]:
    """Cells no turn reaches, because earlier tiers take every turn they cover."""
    reached: set[str] = set()
    taken_by: dict[str, set[str]] = {}
    for values in positions(policy):
        cells = [(tier.id, cell) for tier in policy.tiers.values() if (cell := tier.cell(values)) is not None]
        if not cells:
            continue
        (first, cell), *later = cells
        reached.add(cell.id)
        for _, shadowed in later:
            taken_by.setdefault(shadowed.id, set()).add(first)
    return [
        Problem(
            f"tiers.{cell.id.replace('/', '.')}",
            f"unreachable: tier {', '.join(sorted(taken_by[cell.id]))} applies first to every turn it covers",
        )
        for tier in policy.tiers.values()
        for cell in tier.cells.values()
        if cell.id not in reached
    ]


def check(policy: Policy) -> list[Problem]:
    """Unreachable cells, examples missing the response their position needs, and generated files out of date."""
    problems = _unreachable(policy)
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
