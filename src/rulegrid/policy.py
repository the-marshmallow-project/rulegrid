"""A policy: a structure (its axes and ordered tiers) and a profile (every word and every decision), read from YAML.

`load` validates the profile against its structure and raises `PolicyError` with every problem it finds. A loaded
`Policy` is therefore complete: every value is defined and every grid position inside a tier's condition has a cell.
"""

from __future__ import annotations

import hashlib
import keyword
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Annotated, Any, Generic, Literal, Self, TypeVar

import yamlrocks
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from rulegrid.lexicon import Lexicon
from rulegrid.types import Message, Problem, Values

STRUCTURE = "structure.yaml"
PROFILE = "profile.yaml"


class _File(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- structure.yaml

type AxisID = Annotated[str, Field(pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")]
type ValueIDs = Annotated[list[str], Field(min_length=1)]


class AxisSpec(_File):
    """An axis in the structure: its value ids, in order. `ordered`: the order carries meaning, and a doubt between two
    values settles on the earlier. `multi`: a response may take several values at once."""

    values: ValueIDs
    ordered: bool = False
    multi: bool = False


class StructureFile(_File):
    """`structure.yaml`: the turn and response axes, and the tiers in priority order, each with its condition: for each
    turn axis it is keyed on, the values it covers, or `"*"` for all."""

    turn_axes: dict[AxisID, ValueIDs | AxisSpec]
    response_axes: dict[AxisID, ValueIDs | AxisSpec]
    tiers: dict[str, dict[AxisID, ValueIDs | Literal["*"]]]

    @model_validator(mode="after")
    def distinct_axes(self) -> Self:
        if self.turn_axes.keys() & self.response_axes.keys():
            raise ValueError("turn and response axis identifiers must be distinct")
        names = {"Collection", "Literal", "Path", "TypedDict", "TurnValues", "ResponseValues"}
        for axis in (*self.turn_axes, *self.response_axes):
            if keyword.iskeyword(axis) or axis in {"evidence", "concerns", "examples"}:
                raise ValueError(f"reserved axis identifier {axis}")
            name = "".join(part.capitalize() for part in axis.split("_"))
            if name in names:
                raise ValueError(f"axis identifier {axis} conflicts with generated type {name}")
            names.add(name)
        return self


# --- profile.yaml


class MessageFile(_File):
    role: Literal["user", "assistant"]
    content: str


class ExampleFile(_File):
    context: list[MessageFile] = []
    turn: str
    response: str | None = None
    source: str | None = None


class ValueFile(_File):
    label: str
    definition: str
    indicators: list[str] = []
    excludes: str | None = None
    includes: str | None = None
    avoids: str | None = None
    default: bool = False
    examples: list[ExampleFile] = []


class AxisFile(_File):
    definition: str
    guidance: str | None = None
    values: dict[str, ValueFile]


class TierFile(_File):
    label: str
    definition: str
    instruction: str
    cells: dict[str, Any]


class ProhibitionFile(_File):
    text: str
    group: str | None = None
    valid: list[ExampleFile] = []
    invalid: list[ExampleFile] = []


class PrincipleFile(_File):
    label: str
    text: str


class ProfileFile(_File):
    structure: str = f"../../{STRUCTURE}"
    context: str | None = None
    principles: dict[str, PrincipleFile] = {}
    turn_axes: dict[str, AxisFile]
    response_axes: dict[str, AxisFile]
    tiers: dict[str, TierFile]
    prohibitions: dict[str, ProhibitionFile] = {}


class LexiconFile(_File):
    reminds: str
    entries: list[dict[str, Any]]


# --- the loaded policy


@dataclass(frozen=True)
class Example:
    """A labelled exchange: prior messages, the turn, and for anything but a turn value, the response."""

    turn: str
    response: str | None = None
    context: tuple[Message, ...] = ()
    source: str | None = None

    def conversation(self, with_response: bool = False) -> list[Message]:
        turn = [*self.context, Message("user", self.turn)]
        return [*turn, Message("assistant", self.response)] if with_response and self.response is not None else turn


@dataclass(frozen=True)
class Value:
    id: str
    label: str
    definition: str
    indicators: tuple[str, ...] = ()
    excludes: str | None = None
    includes: str | None = None
    avoids: str | None = None
    default: bool = False
    examples: tuple[Example, ...] = ()


@dataclass(frozen=True)
class Axis:
    id: str
    side: Literal["turn", "response"]
    definition: str
    values: tuple[Value, ...]
    guidance: str | None = None
    ordered: bool = False
    multi: bool = False

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(v.id for v in self.values)

    def value(self, value_id: str) -> Value:
        return next(v for v in self.values if v.id == value_id)


@dataclass(frozen=True)
class Cell:
    """One rule: per response axis, the values a response may take (an axis left out allows any), and examples."""

    id: str
    position: Mapping[str, str]
    allowed: Mapping[str, tuple[str, ...]]
    examples: tuple[Example, ...] = ()


@dataclass(frozen=True)
class Tier:
    """A situation the policy recognises. `condition` maps each key axis to the values the tier covers."""

    id: str
    label: str
    definition: str
    instruction: str
    condition: Mapping[str, tuple[str, ...]]
    cells: Mapping[tuple[str, ...], Cell]

    def covers(self, values: Mapping[str, object]) -> bool:
        return all(values.get(axis) in covered for axis, covered in self.condition.items())

    def cell(self, values: Mapping[str, object]) -> Cell | None:
        """The cell of a turn's values, None outside the condition."""
        if not self.covers(values):
            return None
        return self.cells[tuple(str(values[axis]) for axis in self.condition)]


@dataclass(frozen=True)
class Prohibition:
    id: str
    text: str
    group: str | None = None
    valid: tuple[Example, ...] = ()
    invalid: tuple[Example, ...] = ()


@dataclass(frozen=True)
class Principle:
    id: str
    label: str
    text: str


# Invariant on purpose: given a generated `Policy[TurnValues, ...]`, a values literal is checked against `TurnValues`.
T = TypeVar("T", bound=Mapping[str, object], default=Values)
R = TypeVar("R", bound=Mapping[str, object], default=Values)


@dataclass(frozen=True)
class Policy(Generic[T, R]):
    """A structure and one of its profiles, loaded and validated.

    `T` and `R` are the turn and response values mappings, which a structure's generated `structure_types.py` binds.
    `context` says who the agent is and who it talks to, for the readers of a conversation that don't know it: a
    classifier, a judge, people reading the document. It is not in the agent's prompt, which already says so.
    """

    name: str
    root: Path
    profile_dir: Path
    turn_axes: Mapping[str, Axis]
    response_axes: Mapping[str, Axis]
    tiers: Mapping[str, Tier]
    prohibitions: Mapping[str, Prohibition]
    principles: Mapping[str, Principle]
    lexicons: tuple[Lexicon, ...]
    context: str | None
    digest: str
    structure_digest: str

    def axis(self, axis_id: str) -> Axis:
        return self.turn_axes.get(axis_id) or self.response_axes[axis_id]


class PolicyError(ValueError):
    """A policy whose files cannot be loaded, with every problem found."""

    def __init__(self, problems: list[Problem]):
        self.problems = problems
        super().__init__("\n".join(map(str, problems)))


def _read(path: Path) -> Any:
    return yamlrocks.loads(path.read_text(), option=yamlrocks.OPT_DUPLICATE_KEYS_ERROR)


def _sha(*texts: bytes) -> str:
    h = hashlib.sha256()
    for t in texts:
        h.update(hashlib.sha256(t).digest())
    return f"sha256:{h.hexdigest()}"


def structure_digest(root: Path) -> str:
    return _sha((root / STRUCTURE).read_bytes())


def _axis_spec(spec: list[str] | AxisSpec) -> AxisSpec:
    return spec if isinstance(spec, AxisSpec) else AxisSpec(values=spec)


def _same_keys(problems: list[Problem], where: str, expected: Any, got: Any, what: str) -> None:
    for missing in [k for k in expected if k not in got]:
        problems.append(Problem(where, f"missing {what} {missing}"))
    for unknown in [k for k in got if k not in expected]:
        problems.append(Problem(where, f"unknown {what} {unknown}"))


def _example(e: ExampleFile) -> Example:
    return Example(e.turn, e.response, tuple(Message(m.role, m.content) for m in e.context), e.source)


def _validation(where: str, error: ValidationError) -> list[Problem]:
    return [Problem(f"{where}:{'.'.join(map(str, e['loc']))}", e["msg"]) for e in error.errors()]


def _checkout(path: Path, revision: str) -> Path:
    """`path` in a copy of its git repository at `revision`."""
    top = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True, cwd=path).strip())
    tree = tempfile.mkdtemp(prefix="rulegrid-")
    archive = subprocess.run(["git", "archive", revision], cwd=top, check=True, capture_output=True).stdout
    subprocess.run(["tar", "-x", "-C", tree], input=archive, check=True)
    return Path(tree) / path.resolve().relative_to(top)


def load(path: str | Path, digest: str | None = None, *, revision: str | None = None) -> Policy:
    """Load the profile in the directory `path`, such as `examples/rbr/profiles/default`, with its structure.

    Args:
        path: a profile directory, holding `profile.yaml` and optionally `lexicons/*.yaml`.
        digest: the structure digest the caller's generated types were made from; raises when it differs.
        revision: a git revision, such as `HEAD~1`, to load the files as they were then.

    Raises:
        PolicyError: with every problem found, when the files don't parse or the profile doesn't fit its structure.
    """
    profile_dir = Path(path) if revision is None else _checkout(Path(path), revision)
    problems: list[Problem] = []
    try:
        profile = ProfileFile.model_validate(_read(profile_dir / PROFILE))
    except ValidationError as e:
        raise PolicyError(_validation(PROFILE, e)) from None
    except (OSError, yamlrocks.YAMLRocksError) as e:
        raise PolicyError([Problem(str(profile_dir / PROFILE), str(e))]) from None
    structure_path = (profile_dir / profile.structure).resolve()
    root = structure_path.parent
    try:
        structure = StructureFile.model_validate(_read(structure_path))
    except ValidationError as e:
        raise PolicyError(_validation(STRUCTURE, e)) from None
    except (OSError, yamlrocks.YAMLRocksError) as e:
        raise PolicyError([Problem(str(structure_path), str(e))]) from None
    found_digest = _sha(structure_path.read_bytes())
    if digest is not None and digest != found_digest:
        problems.append(Problem(STRUCTURE, "changed since its types were generated: run `rulegrid generate`"))

    def axes(side: Literal["turn", "response"]) -> dict[str, Axis]:
        specs = structure.turn_axes if side == "turn" else structure.response_axes
        texts = profile.turn_axes if side == "turn" else profile.response_axes
        _same_keys(problems, f"{PROFILE}:{side}_axes", specs, texts, "axis")
        loaded = {}
        for axis_id, raw in specs.items():
            spec = _axis_spec(raw)
            if len(set(spec.values)) != len(spec.values):
                problems.append(Problem(f"{STRUCTURE}:{side}_axes.{axis_id}", "repeated value"))
            if side == "turn" and spec.multi:
                problems.append(Problem(f"{STRUCTURE}:turn_axes.{axis_id}", "a turn axis cannot be multi-valued"))
            if axis_id not in texts:
                continue
            text = texts[axis_id]
            _same_keys(problems, f"{PROFILE}:{side}_axes.{axis_id}", spec.values, text.values, "value")
            values = tuple(
                Value(
                    v,
                    t.label,
                    t.definition,
                    tuple(t.indicators),
                    t.excludes,
                    t.includes,
                    t.avoids,
                    t.default,
                    tuple(map(_example, t.examples)),
                )
                for v in spec.values
                if (t := text.values.get(v))
            )
            loaded[axis_id] = Axis(axis_id, side, text.definition, values, text.guidance, spec.ordered, spec.multi)
        return loaded

    turn_axes, response_axes = axes("turn"), axes("response")

    tiers: dict[str, Tier] = {}
    _same_keys(problems, f"{PROFILE}:tiers", structure.tiers, profile.tiers, "tier")
    for tier_id, keyed in structure.tiers.items():
        condition: dict[str, tuple[str, ...]] = {}
        for axis_id, covered in keyed.items():
            spec = structure.turn_axes.get(axis_id)
            if spec is None:
                problems.append(Problem(f"{STRUCTURE}:tiers.{tier_id}", f"unknown turn axis {axis_id}"))
                continue
            all_values = _axis_spec(spec).values
            if covered == "*":
                condition[axis_id] = tuple(all_values)
                continue
            for value in covered:
                if value not in all_values:
                    problems.append(Problem(f"{STRUCTURE}:tiers.{tier_id}.{axis_id}", f"unknown value {value}"))
            condition[axis_id] = tuple(v for v in all_values if v in covered)
        text = profile.tiers.get(tier_id)
        if text is None:
            continue
        cells: dict[tuple[str, ...], Cell] = {}
        _walk(problems, tier_id, condition, response_axes, text.cells, (), cells)
        tiers[tier_id] = Tier(tier_id, text.label, text.definition, text.instruction, condition, cells)

    prohibitions = {
        p: Prohibition(p, t.text, t.group, tuple(map(_example, t.valid)), tuple(map(_example, t.invalid)))
        for p, t in profile.prohibitions.items()
    }
    lexicons = []
    lexicon_bytes = []
    for lexicon_path in sorted((profile_dir / "lexicons").glob("*.yaml")):
        where = f"lexicons/{lexicon_path.name}"
        try:
            lexicon_bytes.append(lexicon_path.read_bytes())
            raw = LexiconFile.model_validate(_read(lexicon_path))
            lexicon = Lexicon.model_validate({"name": lexicon_path.stem, **raw.model_dump()})
        except ValidationError as e:
            problems += _validation(where, e)
            continue
        except (OSError, yamlrocks.YAMLRocksError) as e:
            problems.append(Problem(where, str(e)))
            continue
        if lexicon.reminds not in prohibitions:
            problems.append(Problem(where, f"reminds an unknown prohibition {lexicon.reminds}"))
        lexicons.append(lexicon)

    if problems:
        raise PolicyError(problems)
    return Policy(
        name=profile_dir.name,
        root=root,
        profile_dir=profile_dir,
        turn_axes=turn_axes,
        response_axes=response_axes,
        tiers=tiers,
        prohibitions=prohibitions,
        principles={p: Principle(p, t.label, t.text) for p, t in profile.principles.items()},
        lexicons=tuple(lexicons),
        context=profile.context.strip() if profile.context else None,
        digest=_sha(structure_path.read_bytes(), (profile_dir / PROFILE).read_bytes(), *lexicon_bytes),
        structure_digest=found_digest,
    )


def _walk(
    problems: list[Problem],
    tier_id: str,
    condition: Mapping[str, tuple[str, ...]],
    response_axes: Mapping[str, Axis],
    node: Any,
    position: tuple[str, ...],
    cells: dict[tuple[str, ...], Cell],
) -> None:
    """Read a tier's nested cells into `cells`, one nesting level per key axis, reporting missing and unknown ones."""
    where = f"{PROFILE}:tiers.{tier_id}.cells" + "".join(f".{p}" for p in position)
    keys = list(condition)
    if len(position) == len(keys):
        cells[position] = _cell(problems, where, tier_id, condition, position, node, response_axes)
        return
    if not isinstance(node, dict):
        problems.append(Problem(where, f"expected the values of {keys[len(position)]} as keys"))
        return
    covered = condition[keys[len(position)]]
    _same_keys(problems, where, covered, node, "cell")
    for value in covered:
        if value in node:
            _walk(problems, tier_id, condition, response_axes, node[value], (*position, value), cells)


def _cell(
    problems: list[Problem],
    where: str,
    tier_id: str,
    condition: Mapping[str, tuple[str, ...]],
    position: tuple[str, ...],
    node: Any,
    response_axes: Mapping[str, Axis],
) -> Cell:
    if not isinstance(node, dict):
        problems.append(Problem(where, "a cell is a mapping of response axes to allowed values, `{}` for none"))
        node = {}
    allowed: dict[str, tuple[str, ...]] = {}
    examples: tuple[Example, ...] = ()
    for key, values in node.items():
        if key == "examples":
            try:
                examples = tuple(map(_example, TypeAdapter(list[ExampleFile]).validate_python(values)))
            except ValidationError as e:
                problems += _validation(f"{where}.examples", e)
            continue
        axis = response_axes.get(key)
        if axis is None:
            problems.append(Problem(where, f"unknown response axis {key}"))
            continue
        if not isinstance(values, list) or not values or any(not isinstance(v, str) for v in values):
            problems.append(Problem(f"{where}.{key}", "list at least one allowed value"))
            continue
        for v in values:
            if v not in axis.ids:
                problems.append(Problem(f"{where}.{key}", f"unknown value {v}"))
        if len(set(values)) != len(values):
            problems.append(Problem(f"{where}.{key}", "repeated value"))
        allowed[key] = tuple(v for v in axis.ids if v in values)
    return Cell("/".join((tier_id, *position)), dict(zip(condition, position, strict=True)), allowed, examples)


def positions(policy: Policy) -> list[dict[str, str]]:
    """Every combination of turn values, in axis order."""
    axes = list(policy.turn_axes.values())
    return [dict(zip((a.id for a in axes), combo, strict=True)) for combo in product(*(a.ids for a in axes))]
