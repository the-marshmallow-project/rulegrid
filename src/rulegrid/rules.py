"""From a turn's classification to a prescription, and from a response's to its compliance. No model, no I/O."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any

from rulegrid.policy import Policy
from rulegrid.types import Article, Breach, Classification, Compliance, Prescription


def _values(c: Classification[Any] | Mapping[str, Any]) -> Mapping[str, Any]:
    return c.values if isinstance(c, Classification) else c


def prescribe[T: Mapping[str, object], R: Mapping[str, object]](
    policy: Policy[T, R], turn: Classification[T] | T
) -> Prescription | None:
    """The tiers in priority order: the first whose condition holds for the turn prescribes. None when none applies.

    Args:
        policy: the policy whose tiers to try.
        turn: the turn's classification, or its bare values.
    """
    values = _values(turn)
    for tier in policy.tiers.values():
        if (cell := tier.cell(values)) is not None:
            return Prescription(tier.id, cell.id, cell.allowed)
    return None


def comply[T: Mapping[str, object], R: Mapping[str, object]](
    policy: Policy[T, R],
    turn: Classification[T] | T,
    response: Classification[R] | R,
    breaches: Collection[Breach | str] = (),
) -> Compliance:
    """Whether a response complies: it breaches no prohibition, and its value on each axis its cell lists is allowed.

    On a multi-valued axis the cell lists, the response takes at least one value and every value it takes is allowed.

    Args:
        policy: the policy.
        turn: the turn's classification, or its values.
        response: the response's classification, or its values. A classification's `breaches` count.
        breaches: more breaches, as `Breach`es or prohibition ids, for a caller passing bare values.
    """
    articles: list[Article] = []
    found = [*(response.breaches if isinstance(response, Classification) else ()), *breaches]
    for breach in dict.fromkeys(b if isinstance(b, str) else b.prohibition for b in found):
        articles.append(Article("prohibition", breach))
    prescription = prescribe(policy, turn)
    if prescription is not None:
        values = _values(response)
        for axis, allowed in prescription.allowed.items():
            taken = values.get(axis)
            if policy.response_axes[axis].multi:
                taken_set = {taken} if isinstance(taken, str) else set(taken or ())
                ok = bool(taken_set) and taken_set <= set(allowed)
                shown = ", ".join(sorted(taken_set)) or "none"
            else:
                ok = taken in allowed
                shown = str(taken)
            if not ok:
                articles.append(Article("cell", prescription.cell, f"{axis} {shown} is not in [{', '.join(allowed)}]"))
    return Compliance(not articles, tuple(articles), policy.digest)
