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
    """A prohibition a response breaches: its id, the words that breach it (`quote`), and how (`why`)."""

    prohibition: str
    quote: str = ""
    why: str = ""


@dataclass(frozen=True)
class Classification[V: Mapping[str, object] = Values]:
    """A turn or a response classified on the policy's axes.

    `values` maps each axis id to a value id, or to a frozenset of them on a multi-valued axis. `scores` holds what the
    classifier answered, for the caller to log. `evidence` maps an axis id to the words it rests on. `reminders` are,
    for a turn, the prohibitions it invites the response to breach; `breaches`, for a response, the ones it breaches.
    """

    values: V
    scores: Mapping[str, Any] = field(default_factory=dict)
    evidence: Mapping[str, str] = field(default_factory=dict)
    reminders: tuple[str, ...] = ()
    breaches: tuple[Breach, ...] = ()


@dataclass(frozen=True)
class Prescription:
    """What a tier allows a response to a turn: per response axis, the allowed values, in the axis's order.

    An axis absent from `allowed` allows any value. `cell` is the cell id, such as `first_law/HUMAN`.
    """

    tier: str
    cell: str
    allowed: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class Article:
    """An article of the policy that decides a compliance: a cell, by its cell id, or a prohibition, by its id.

    `detail` says, for a cell, which value the response takes that the cell doesn't allow.
    """

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
    """A judge's reading of one exchange, by its index in the conversation.

    `prescription` and `compliance` are computed from the two classifications, never asked of the judge.
    """

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


# The System One API: POST {model, state, questions} -> {answers}.
type State = str | Mapping[str, Any] | Sequence[Any]
"""What a System One model is asked about, as JSON."""


class Question(TypedDict):
    """A System One question: yes or no (`noul`), one of several `choice`s, or a `score` on a scale."""

    type: Literal["noul", "choice", "score"]
    instructions: str
    criteria: NotRequired[Mapping[str, Any] | Sequence[str]]


class Answer(TypedDict):
    """A System One answer: the probability of yes (`noul`), or the `choice` or `score` with its `probabilities`."""

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
    response breaches it. A row with a response and no response labels is audited: its compliance is computed.
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
        """Per label, such as `turn.verb` or `breach.HARM_HUMAN`, how many rows agree out of how many have it."""
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
        """The report as Markdown: agreement per label, compliance per cell, each disagreement, each breach."""

        def table(head: str, counts: dict[str, tuple[int, int]]) -> list[str]:
            ok, total = sum(c[0] for c in counts.values()), sum(c[1] for c in counts.values())
            rows = [*counts.items(), ("**All**", (ok, total))]
            return [f"| {head} | Rows | Rate |", "|---|---|---|"] + [
                f"| {k} | {n} of {t} | {n / t:.0%} |" for k, (n, t) in rows if t
            ]

        failing = sum(not r.ok for r in self.results)
        lines = [f"{len(self.results)} rows, {failing} with a disagreement.", ""]
        lines += table("Label agreeing", self.agreement())
        if audited := self.compliance():
            lines += ["", *table("Cell complying", audited)]

        def row(r: Result) -> str:
            """The row's source and its turn, so a line can be found without opening the data."""
            turn = r.row.conversation[-1].content
            turn = turn if len(turn) <= 80 else turn[:79] + "…"
            return f"{r.row.source} {turn!r}".lstrip()

        wrong = [(r, c) for r in self.results for c in r.checks if not c[1]]
        if wrong:
            lines += ["", "## Disagreements", ""]
            lines += [f"- {row(r)}: {label} {detail}" for r, (label, _, detail) in wrong]
        breached = [(r, r.compliance) for r in self.results if r.compliance is not None and not r.compliance.ok]
        if breached:
            lines += ["", "## Non-compliant", ""]
            lines += [
                f"- {row(r)}: " + "; ".join(f"{a.id} {a.detail}".rstrip() for a in c.articles) for r, c in breached
            ]
        return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class Comparison:
    """Two versions of a policy on one dataset: their diff, both reports, and the rows whose result flips."""

    diff: PolicyDiff
    old: Report
    new: Report
    flips: tuple[int, ...]
