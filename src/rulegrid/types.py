"""The data types that flow between rulegrid's functions. None of them calls a model or reads a file."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, NotRequired, Protocol, TypedDict

if TYPE_CHECKING:
    from pydantic import BaseModel

    from rulegrid.lexicon import Entry

type Values = Mapping[str, str | Collection[str]]
"""A classification's values: axis id to value id, or to a set of value ids on a multi-valued axis."""


@dataclass(frozen=True)
class Message:
    """One chat message. The user writes the turn, the agent (`assistant`) the response."""

    role: Literal["user", "assistant"]
    content: str


type Conversation = Sequence[Message | Mapping[str, str]]
"""Chat messages, as `Message`s or as `{"role": ..., "content": ...}` dicts."""


@dataclass(frozen=True)
class Breach:
    """A prohibition a response breaks: its id, and the words that break it, with how."""

    prohibition: str
    quote: str = ""
    why: str = ""


@dataclass(frozen=True)
class Classification[V: Mapping[str, object] = Values]:
    """A turn or a response classified on the policy's axes.

    `values` maps each axis id to a value id, or to a frozenset of them on a multi-valued axis. `scores` holds what the
    classifier answered, for the caller to log. `evidence` maps an axis id to the words it rests on. `reminders` are,
    for a turn, the prohibitions it invites the response to breach; `breaches`, for a response, the ones it breaks.
    """

    values: V
    scores: Mapping[str, Any] = field(default_factory=dict)
    evidence: Mapping[str, str] = field(default_factory=dict)
    reminders: tuple[str, ...] = ()
    breaches: tuple[Breach, ...] = ()


@dataclass(frozen=True)
class Prescription:
    """What a tier allows a response to a turn: per response axis, the allowed values, in the axis's order.

    An axis absent from `allowed` allows any value. `cell` is the position id, such as `alert/SEVERE/SHARE`.
    """

    tier: str
    cell: str
    allowed: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class Article:
    """A rule that decides a compliance: a cell, by its position id, or a prohibition, by its id."""

    kind: Literal["cell", "prohibition"]
    id: str
    detail: str = ""


@dataclass(frozen=True)
class Compliance:
    """Whether a response complies, with the articles that decide it and the digest of the policy that decided."""

    ok: bool
    articles: tuple[Article, ...]
    digest: str

    def __bool__(self) -> bool:
        return self.ok


@dataclass(frozen=True)
class Hit:
    """A lexicon entry found in a text, `text` as written, and the prohibition the entry's lexicon reminds."""

    text: str
    entry: Entry
    reminds: str


@dataclass(frozen=True)
class Problem:
    """Something wrong with a policy's files, at `where` (a file, or a path inside the policy)."""

    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.where}: {self.message}"


@dataclass(frozen=True)
class Assessment:
    """One exchange judged against the policy. `prescription` and `compliance` are computed, never asked."""

    exchange: int
    turn: Classification
    response: Classification
    rationale: str
    prescription: Prescription | None
    compliance: Compliance


class Classifier(Protocol):
    """Anything that classifies the last turn or the last response of a conversation on a policy's axes."""

    async def classify(
        self, conversation: Conversation, of: Literal["turn", "response"] = "turn", hits: Sequence[Hit] = ()
    ) -> Classification: ...


# System One, the API decision models share: POST {model, state, questions} -> {answers}.
type State = str | Mapping[str, Any] | Sequence[Any]


class Question(TypedDict):
    type: Literal["noul", "choice", "score"]
    instructions: str
    criteria: NotRequired[Mapping[str, Any] | Sequence[str]]


class Answer(TypedDict):
    type: Literal["noul", "choice", "score"]
    noul: NotRequired[float]
    choice: NotRequired[str]
    score: NotRequired[float]
    probabilities: NotRequired[Mapping[str, float]]


type Decide = Callable[[State, Mapping[str, Question]], Awaitable[Mapping[str, Answer]]]
"""Ask a decision model `questions` about `state`, and return its answers by question id."""

type Complete = Callable[[list[dict[str, str]], type[BaseModel]], Awaitable[str]]
"""Send chat messages to an LLM constrained to a schema, and return the JSON it answered."""


def messages(conversation: Conversation) -> list[Message]:
    """A conversation as `Message`s."""
    return [m if isinstance(m, Message) else Message(m["role"], m["content"]) for m in conversation]  # type: ignore[arg-type]


@dataclass(frozen=True)
class Change:
    """One article that differs between two versions of a policy.

    `kind` is what the article is (a cell, a value, a prohibition...), `id` where it sits, and `change` how it moved. A
    cell whose allowed values shrink is `tightened`, one whose allowed values grow `loosened`.
    """

    kind: Literal["structure", "context", "principle", "axis", "value", "tier", "cell", "prohibition", "lexicon"]
    id: str
    change: Literal["added", "removed", "changed", "tightened", "loosened", "mixed"]

    def __str__(self) -> str:
        return f"{self.change:<9} {self.kind} {self.id}"


@dataclass(frozen=True)
class PolicyDiff:
    """What changed between two versions of a policy: its articles, and each turn whose prescription changes."""

    changes: tuple[Change, ...]
    prescriptions: tuple[tuple[Mapping[str, str], Prescription | None, Prescription | None], ...]

    def __bool__(self) -> bool:
        return bool(self.changes)

    def __str__(self) -> str:
        lines = [str(c) for c in self.changes]
        if self.prescriptions:
            lines.append(f"{len(self.prescriptions)} turn classifications change prescription")
        return "\n".join(lines) or "no change"


@dataclass(frozen=True)
class Row:
    """A labelled exchange: the conversation up to the turn, the response if any, and partial labels.

    `turn_values` labels some turn axes. `response_values` lists, per response axis, the values the response may
    take: one for an exact label, several for a cell's allowed values. `breaches` says, per prohibition, whether the
    response breaks it. A row with a response and no response labels is audited: its compliance is computed.
    """

    conversation: tuple[Message, ...]
    response: str | None = None
    turn_values: Mapping[str, str] = field(default_factory=dict)
    response_values: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    breaches: Mapping[str, bool] = field(default_factory=dict)
    source: str = ""


@dataclass(frozen=True)
class Result:
    """A row read by a classifier. `checks` holds one `(label, agrees, detail)` per label, such as `turn.verb`."""

    row: Row
    turn: Classification | None
    response: Classification | None
    checks: tuple[tuple[str, bool, str], ...]
    prescription: Prescription | None = None
    compliance: Compliance | None = None

    @property
    def ok(self) -> bool:
        return all(agrees for _, agrees, _ in self.checks)


@dataclass(frozen=True)
class Report:
    """A classifier's results on a dataset, against one version of a policy."""

    digest: str
    results: tuple[Result, ...]

    def agreement(self) -> dict[str, tuple[int, int]]:
        """Per label, such as `turn.verb` or `breach.CLAIM_REAL`, how many rows agree out of how many have it."""
        counts: dict[str, tuple[int, int]] = {}
        for result in self.results:
            for label, agrees, _ in result.checks:
                ok, total = counts.get(label, (0, 0))
                counts[label] = (ok + agrees, total + 1)
        return dict(sorted(counts.items()))

    def compliance(self) -> dict[str, tuple[int, int]]:
        """For audited rows, per cell id (`-` when no tier applies), how many comply out of how many."""
        counts: dict[str, tuple[int, int]] = {}
        for result in self.results:
            if result.compliance is None:
                continue
            cell = result.prescription.cell if result.prescription else "-"
            ok, total = counts.get(cell, (0, 0))
            counts[cell] = (ok + result.compliance.ok, total + 1)
        return dict(sorted(counts.items()))

    def markdown(self) -> str:
        lines = ["| Label | Agree | Rows |", "|---|---|---|"]
        lines += [f"| {label} | {ok} | {total} |" for label, (ok, total) in self.agreement().items()]
        if audited := self.compliance():
            lines += ["", "| Cell | Complies | Rows |", "|---|---|---|"]
            lines += [f"| {cell} | {ok} | {total} |" for cell, (ok, total) in audited.items()]
        wrong = [(r, c) for r in self.results for c in r.checks if not c[1]]
        if wrong:
            lines += ["", "## Disagreements", ""]
            lines += [
                f"- {r.row.source or r.row.conversation[-1].content!r}: {label} {detail}"
                for r, (label, _, detail) in wrong
            ]
        return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class Comparison:
    """Two versions of a policy on one dataset: their diff, both reports, and the rows whose result flips."""

    diff: PolicyDiff
    old: Report
    new: Report
    flips: tuple[int, ...]
