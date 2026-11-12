"""The difference between two versions of a policy, article by article and prescription by prescription. No model."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from rulegrid.policy import Cell, Policy, positions
from rulegrid.rules import prescribe
from rulegrid.types import Change, PolicyDiff


def _compare[X](
    kind: Any, old: Mapping[str, X], new: Mapping[str, X], how: Callable[[X, X], Any] = lambda a, b: "changed"
) -> list[Change]:
    changes = [Change(kind, k, "removed") for k in old if k not in new]
    changes += [Change(kind, k, "added") for k in new if k not in old]
    changes += [Change(kind, k, how(old[k], new[k])) for k in old if k in new and old[k] != new[k]]
    return changes


def _cell_change(old: Cell, new: Cell, every: Mapping[str, tuple[str, ...]]) -> str:
    """Tightened when no axis allows more and one allows less, loosened the other way round."""
    narrower = wider = False
    for axis, values in every.items():
        before, after = set(old.allowed.get(axis, values)), set(new.allowed.get(axis, values))
        narrower |= bool(before - after)
        wider |= bool(after - before)
    if narrower and wider:
        return "mixed"
    return "tightened" if narrower else "loosened" if wider else "changed"


def diff(old: Policy, new: Policy) -> PolicyDiff:
    """The articles that changed from `old` to `new`, and every turn classification whose prescription changes.

    Labels each changed cell as tightened (fewer allowed values), loosened, or mixed, so a review sees at once
    whether an edit makes the policy stricter.
    """
    changes: list[Change] = []
    if old.structure_digest != new.structure_digest:
        changes.append(Change("structure", "structure.yaml", "changed"))
    changes += _compare("principle", old.principles, new.principles)
    for side in ("turn_axes", "response_axes"):
        a, b = getattr(old, side), getattr(new, side)
        changes += _compare(
            "axis",
            {k: (v.definition, v.guidance) for k, v in a.items()},
            {k: (v.definition, v.guidance) for k, v in b.items()},
        )
        changes += _compare(
            "value",
            {f"{k}/{v.id}": v for k, ax in a.items() for v in ax.values},
            {f"{k}/{v.id}": v for k, ax in b.items() for v in ax.values},
        )
    text = {"label", "definition", "instruction"}
    changes += _compare(
        "tier",
        {k: [getattr(t, f) for f in text] for k, t in old.tiers.items()},
        {k: [getattr(t, f) for f in text] for k, t in new.tiers.items()},
    )
    every = {a.id: a.ids for a in new.response_axes.values()}
    changes += _compare(
        "cell",
        {c.id: c for t in old.tiers.values() for c in t.cells.values()},
        {c.id: c for t in new.tiers.values() for c in t.cells.values()},
        lambda a, b: _cell_change(a, b, every),
    )
    changes += _compare("prohibition", old.prohibitions, new.prohibitions)
    changes += _compare("lexicon", {lx.name: lx for lx in old.lexicons}, {lx.name: lx for lx in new.lexicons})
    flips = []
    if old.structure_digest == new.structure_digest:
        for values in positions(new):
            before, after = prescribe(old, values), prescribe(new, values)
            if before != after:
                flips.append((values, before, after))
    return PolicyDiff(tuple(changes), tuple(flips))
