"""The policy as text: three renderings of the whole policy, and the nudge for one turn.

Each is a Jinja template. The defaults, in `rulegrid/templates/`, are neutral English; a file of the same name in the
policy's `templates/` folder, next to `structure.yaml`, overrides one.
"""

from __future__ import annotations

import functools
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, PackageLoader, PrefixLoader, StrictUndefined

from rulegrid.policy import Policy
from rulegrid.rules import prescribe
from rulegrid.types import Classification, Hit, Values

type Rendering = Literal["prompt", "judge", "document"]


@functools.cache
def _environment(root: Path) -> Environment:
    env = Environment(
        # A policy's templates override the defaults, which stay reachable as `rulegrid/<name>` to extend.
        loader=ChoiceLoader(
            [
                FileSystemLoader(root / "templates"),
                PrefixLoader({"rulegrid": PackageLoader("rulegrid", "templates")}),
                PackageLoader("rulegrid", "templates"),
            ]
        ),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
        undefined=StrictUndefined,
    )
    env.filters["lcfirst"] = lambda text: text[:1].lower() + text[1:]
    env.filters["ucfirst"] = lambda text: text[:1].upper() + text[1:]
    env.filters["cell"] = lambda text: " ".join(str(text).split()).replace("|", "\\|")
    return env


def template(policy: Policy, name: str, **context: Any) -> str:
    """Render the template `name` of the policy, with `policy` and `context`."""
    return _environment(policy.root).get_template(name).render(policy=policy, **context).strip() + "\n"


def render(policy: Policy, rendering: Rendering) -> str:
    """The whole policy as text for one audience.

    - `prompt`: the agent's system-prompt section: principles, how turns are read, prohibitions.
    - `judge`: the whole policy with its ids, for a judge.
    - `document`: Markdown for people.
    """
    return template(policy, f"{rendering}.j2")


def nudge(policy: Policy, turn: Classification | Values, hits: Sequence[Hit] = ()) -> str | None:
    """The text the agent gets just before it responds to one turn: the prescription and the reminders.

    The reminders are the prohibitions the classifier found the turn invites a breach of (`turn.reminders`), and those
    a lexicon hit reminds, with the words hit. None when every allowed value is a default value and nothing is
    reminded: the agent would respond right unprompted.
    """
    values: Mapping[str, Any] = turn.values if isinstance(turn, Classification) else turn
    prescription = prescribe(policy, values)
    reminded: dict[str, list[Hit]] = {r: [] for r in (turn.reminders if isinstance(turn, Classification) else ())}
    for hit in hits:
        reminded.setdefault(hit.reminds, []).append(hit)
    allowed = {}
    if prescription is not None:
        allowed = {
            policy.response_axes[axis]: [policy.response_axes[axis].value(v) for v in ids]
            for axis, ids in prescription.allowed.items()
        }
    # An axis whose allowed values are all defaults asks nothing the agent wouldn't do unprompted.
    allowed = {axis: values_ for axis, values_ in allowed.items() if not all(v.default for v in values_)}
    needed = bool(allowed)
    if not needed and not reminded:
        return None
    tier = policy.tiers[prescription.tier] if prescription and needed else None
    return template(
        policy,
        "nudge.j2",
        turn=values,
        tier=tier,
        cell=tier.cell(values) if tier else None,
        allowed=allowed if tier else {},
        reminders=[{"prohibition": policy.prohibitions[p], "hits": h} for p, h in reminded.items()],
    )
