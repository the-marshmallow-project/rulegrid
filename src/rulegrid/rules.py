"""From a turn's classification to a prescription, and from a response's to its compliance. No model, no I/O.

Both refuse values the policy doesn't define, and a turn or response missing an axis: a typo or a classifier bug
raises instead of returning a prescription or a compliance that looks sound.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any, Literal

from rulegrid.policy import Policy
from rulegrid.types import Article, Breach, Classification, Compliance, Prescription


def _values(
    policy: Policy[Any, Any], side: Literal["turn", "response"], c: Classification[Any] | Mapping[str, Any]
) -> Mapping[str, Any]:
    """The values of a classification, or bare values, checked: one defined value per axis, a set on a multi one."""
    values = c.values if isinstance(c, Classification) else c
    axes = policy.turn_axes if side == "turn" else policy.response_axes
    problems = [f"missing {side} axis {a}" for a in axes if a not in values]
    taken: dict[str, Collection[str]] = {}
    for axis_id, value in values.items():
        if isinstance(value, str):
            taken[axis_id] = (value,)
        elif axis_id in axes and axes[axis_id].multi and isinstance(value, Collection):
            taken[axis_id] = value
        else:
            problems.append(f"{side}.{axis_id}: expected a value id, got {value!r}")
    problems += policy.unknown(side, taken)
    if problems:
        raise ValueError("; ".join(problems))
    return values


def prescribe[T: Mapping[str, object], R: Mapping[str, object]](
    policy: Policy[T, R], turn: Classification[T] | T
) -> Prescription | None:
    """The tiers in priority order: the first whose condition holds for the turn prescribes. None when none applies.

    Args:
        policy: the policy whose tiers to try.
        turn: the turn's classification, or its bare values.

    Raises:
        ValueError: when the turn misses an axis, or takes a value or an axis the policy doesn't define.
    """
    values = _values(policy, "turn", turn)
    for tier in policy.tiers.values():
        if (cell := tier.cell(values)) is not None:
            return Prescription(tier.id, cell.id, cell.allowed, cell.open)
    return None


def comply[T: Mapping[str, object], R: Mapping[str, object]](
    policy: Policy[T, R],
    turn: Classification[T] | T,
    response: Classification[R] | R,
    breaches: Collection[Breach | str] = (),
) -> Compliance:
    """How a response stands: it complies, deviates or breaches, with the articles that decide it.

    It breaches when it breaches a prohibition or takes a value its cell forbids. Otherwise it deviates when it takes
    a value its cell leaves open, and complies when every value it takes on each axis its cell lists is allowed. On a
    multi-valued axis the response takes at least one value; taking none deviates where the cell leaves values open,
    and breaches elsewhere.

    Args:
        policy: the policy.
        turn: the turn's classification, or its values.
        response: the response's classification, or its values. A classification's `breaches` count.
        breaches: more breaches, as `Breach`es or prohibition ids, for a caller passing bare values. A prohibition
            counts only when breached here or in `response.breaches`: nothing else checks the response's text.

    Raises:
        ValueError: when the turn or response misses an axis, or either takes a value, an axis or a prohibition the
            policy doesn't define.
    """
    values = _values(policy, "response", response)
    found = [*(response.breaches if isinstance(response, Classification) else ()), *breaches]
    breached = dict.fromkeys(b if isinstance(b, str) else b.prohibition for b in found)
    if unknown := [p for p in breached if p not in policy.prohibitions]:
        raise ValueError(f"unknown prohibition {', '.join(unknown)}")
    articles = [Article("prohibition", p) for p in breached]
    prescription = prescribe(policy, turn)
    if prescription is not None:
        for axis, allowed in prescription.allowed.items():
            taken = values.get(axis)
            taken_set = {taken} if isinstance(taken, str) else set(taken or ())
            if taken_set and taken_set <= set(allowed):
                continue
            open_ = prescription.open.get(axis, ())
            severity = "deviates" if taken_set <= {*allowed, *open_} and (taken_set or open_) else "breaches"
            shown = ", ".join(sorted(taken_set)) or "none"
            detail = f"{axis} {shown} is not in [{', '.join(allowed)}]"
            articles.append(Article("cell", prescription.cell, detail, severity))
    outcome = "breaches" if any(a.outcome == "breaches" for a in articles) else "deviates" if articles else "complies"
    return Compliance(outcome, tuple(articles), policy.digest)
