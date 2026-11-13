"""Labelled exchanges, and how a classifier reads them against a policy.

A policy's own examples are a dataset: `Dataset.from_policy` labels each from where it sits, so running a classifier
on them checks that the policy's texts draw the lines its examples draw.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rulegrid.diff import diff
from rulegrid.lexicon import match
from rulegrid.policy import Policy
from rulegrid.rules import comply, prescribe
from rulegrid.types import Classifier, Comparison, Message, Report, Result, Row, messages

_KEYS = ("messages", "response", "turn_values", "response_values", "breaches", "source")


@dataclass(frozen=True)
class Dataset:
    """Rows of labelled exchanges. JSONL on disk, one row per line:

    `{"messages": [...], "response": "...", "turn_values": {axis: value}, "response_values": {axis: [values]},
    "breaches": {prohibition: bool}, "source": "..."}`, every key but `messages` optional.
    """

    rows: tuple[Row, ...] = ()

    def __iter__(self) -> Iterator[Row]:
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    def __add__(self, other: Dataset) -> Dataset:
        return Dataset(self.rows + other.rows)

    def where(self, **values: str) -> Dataset:
        """The rows whose turn is labelled with these values, such as `where(danger="HUMAN")`."""
        return Dataset(tuple(r for r in self.rows if all(r.turn_values.get(k) == v for k, v in values.items())))

    @classmethod
    def load(cls, path: str | Path) -> Dataset:
        """Read a JSONL file, one row per line.

        Raises:
            ValueError: when a row has a key the format doesn't define, whose labels would otherwise be dropped.
        """
        rows = []
        for number, line in enumerate(Path(path).read_text().splitlines(), 1):
            if not line.strip():
                continue
            d = json.loads(line)
            if unknown := sorted(set(d) - set(_KEYS)):
                raise ValueError(f"{path}:{number}: unknown key {', '.join(unknown)}; a row has {', '.join(_KEYS)}")
            response_values = {
                k: (v,) if isinstance(v, str) else tuple(v) for k, v in d.get("response_values", {}).items()
            }
            rows.append(
                Row(
                    tuple(messages(d["messages"])),
                    d.get("response"),
                    d.get("turn_values", {}),
                    response_values,
                    d.get("breaches", {}),
                    d.get("source", ""),
                )
            )
        return cls(tuple(rows))

    def save(self, path: str | Path) -> None:
        """Write the rows as JSONL, leaving out the keys a row doesn't set."""
        lines = []
        for r in self.rows:
            d: dict[str, Any] = {"messages": [{"role": m.role, "content": m.content} for m in r.conversation]}
            if r.response is not None:
                d["response"] = r.response
            if r.turn_values:
                d["turn_values"] = dict(r.turn_values)
            if r.response_values:
                d["response_values"] = {k: list(v) for k, v in r.response_values.items()}
            if r.breaches:
                d["breaches"] = dict(r.breaches)
            if r.source:
                d["source"] = r.source
            lines.append(json.dumps(d, ensure_ascii=False))
        Path(path).write_text("\n".join(lines) + "\n")

    @classmethod
    def from_policy(cls, policy: Policy) -> Dataset:
        """The policy's examples, each labelled by where it sits.

        A turn value's examples label that axis; a response value's, that axis of the response. A cell's examples
        label the turn's grid position and the values the response may take, and breach no prohibition, nor do a
        prohibition's `valid` examples. A prohibition's `invalid` examples breach it.
        """
        rows: list[Row] = []
        clean = dict.fromkeys(policy.prohibitions, False)
        for axis in policy.turn_axes.values():
            for v in axis.values:
                rows += [
                    Row(tuple(e.conversation()), turn_values={axis.id: v.id}, source=f"{axis.id}/{v.id}")
                    for e in v.examples
                ]
        for axis in policy.response_axes.values():
            for v in axis.values:
                rows += [
                    Row(
                        tuple(e.conversation()),
                        e.response,
                        response_values={axis.id: (v.id,)},
                        source=f"{axis.id}/{v.id}",
                    )
                    for e in v.examples
                ]
        for tier in policy.tiers.values():
            for cell in tier.cells.values():
                rows += [
                    Row(tuple(e.conversation()), e.response, dict(cell.position), dict(cell.allowed), clean, cell.id)
                    for e in cell.examples
                ]
        for p in policy.prohibitions.values():
            rows += [Row(tuple(e.conversation()), e.response, breaches=clean, source=f"{p.id} valid") for e in p.valid]
            rows += [
                Row(tuple(e.conversation()), e.response, breaches={p.id: True}, source=f"{p.id} invalid")
                for e in p.invalid
            ]
        return cls(tuple(rows))


def _shown(value: Any) -> str:
    return value if isinstance(value, str) else ", ".join(sorted(value))


async def _read(policy: Policy, row: Row, classifier: Classifier) -> Result:
    conversation = list(row.conversation)
    checks: list[tuple[str, bool, str]] = []
    labelled = bool(row.response_values or row.breaches)
    audited = row.response is not None and not labelled
    turn = response = None
    if row.turn_values or audited:
        hits = match(policy.lexicons, conversation[-1].content)
        turn = await classifier.classify(conversation, "turn", hits)
        for axis, label in row.turn_values.items():
            got = turn.values.get(axis)
            checks.append((f"turn.{axis}", got == label, f"read {got}, labelled {label}"))
    if row.response is not None and (labelled or audited):
        response = await classifier.classify([*conversation, Message("assistant", row.response)], "response")
        for axis, allowed in row.response_values.items():
            got = response.values.get(axis)
            taken = {got} if isinstance(got, str) else set(got or ())
            checks.append(
                (
                    f"response.{axis}",
                    bool(taken) and taken <= set(allowed),
                    f"read {_shown(taken) or 'none'}, labelled {' or '.join(allowed)}",
                )
            )
        breached = {b.prohibition for b in response.breaches}
        for p, label in row.breaches.items():
            checks.append((f"breach.{p}", (p in breached) == label, f"read {'breached' if p in breached else 'clean'}"))
    prescription = compliance = None
    if audited and turn is not None and response is not None:
        prescription, compliance = prescribe(policy, turn), comply(policy, turn, response)
    return Result(row, turn, response, tuple(checks), prescription, compliance)


async def evaluate(policy: Policy, data: Iterable[Row], classifier: Classifier, concurrency: int = 8) -> Report:
    """Read every row with the classifier, `concurrency` rows at a time, and check it against its labels.

    Rows with a response and no response labels are audited instead: their compliance is computed from the
    classifier's readings, which is how recorded conversations are checked.

    Raises:
        ValueError: before reading any row, when labels name an axis, a value or a prohibition the policy doesn't
            define.
    """
    rows = tuple(data)
    problems = []
    for i, row in enumerate(rows, 1):
        unknown = policy.unknown("turn", {k: (v,) for k, v in row.turn_values.items()})
        unknown += policy.unknown("response", row.response_values)
        unknown += [f"unknown prohibition {p}" for p in row.breaches if p not in policy.prohibitions]
        problems += [f"row {i} {row.source}".rstrip() + f": {u}" for u in unknown]
    if problems:
        raise ValueError("labels the policy doesn't define:\n" + "\n".join(problems))
    semaphore = asyncio.Semaphore(concurrency)

    async def one(row: Row) -> Result:
        async with semaphore:
            return await _read(policy, row, classifier)

    return Report(policy.digest, tuple(await asyncio.gather(*map(one, rows))))


async def compare(
    old: Policy, new: Policy, data: Iterable[Row], classifier: Callable[[Policy], Classifier], concurrency: int = 8
) -> Comparison:
    """Both versions of a policy on one dataset: what changed, and which rows read differently.

    Args:
        classifier: builds a classifier for a policy, since a classifier asks from the policy's own texts.
    """
    rows = tuple(data)
    before = await evaluate(old, rows, classifier(old), concurrency)
    after = await evaluate(new, rows, classifier(new), concurrency)

    def outcome(r: Result) -> Any:
        return (
            r.checks,
            r.turn and r.turn.values,
            r.response and r.response.values,
            r.compliance and r.compliance.ok,
            r.prescription,
        )

    flips = tuple(
        i for i, (a, b) in enumerate(zip(before.results, after.results, strict=True)) if outcome(a) != outcome(b)
    )
    return Comparison(diff(old, new), before, after, flips)
