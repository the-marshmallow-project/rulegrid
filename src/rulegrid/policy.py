"""A policy: a structure (its axes and ordered tiers) and a profile (every word and every decision), read from YAML.

`load_structure` reads a structure alone, which is all the generated files need. `load` validates a profile against
its structure and raises `PolicyError` with every problem it finds. A loaded `Policy` is therefore complete: every
value is defined and every grid position inside a tier's condition has a cell.
"""

from __future__ import annotations

import hashlib
import keyword
import subprocess
import tempfile
import weakref
from collections.abc import Collection, Mapping
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
    """A labelled exchange, labelled by where it sits. `rulegrid eval` without data runs a classifier on them."""

    context: list[MessageFile] = Field([], description="The messages before the turn.")
    turn: str = Field(description="The user's message.")
    response: str | None = Field(
        None, description="The agent's reply. Needed everywhere except in a turn value's examples."
    )
    source: str | None = Field(None, description="Where the example comes from, such as a section of a source text.")


class ValueFile(_File):
    """A value of an axis. The classifier tells values apart from these texts alone."""

    label: str = Field(description="A short name for people.")
    definition: str = Field(description="What the value covers, written against the axis's other values.")
    indicators: list[str] = Field([], description="Turn axes: typical wording of a turn that takes this value.")
    excludes: str | None = Field(None, description="Turn axes: look-alikes that belong to another value.")
    includes: str | None = Field(None, description="Response axes: what a response taking this value does.")
    avoids: str | None = Field(None, description="Response axes: what a response taking this value doesn't do.")
    default: bool = Field(
        False,
        description="Response axes: what the agent does unprompted. A nudge leaves out an axis whose allowed values"
        " are all defaults; compliance is unchanged.",
    )
    examples: list[ExampleFile] = Field(
        [], description="Turns that take this value, or, on a response axis, exchanges whose response takes it."
    )


class AxisFile(_File):
    definition: str = Field(description="The question the axis answers about a turn or a response.")
    guidance: str | None = Field(None, description="Response axes: advice to the agent, added to the nudge.")
    values: dict[str, ValueFile] = Field(description="Every value the structure lists, by id.")


class TierFile(_File):
    label: str = Field(description="A short name for people.")
    definition: str = Field(description="When the tier applies, for the classifier and the judge.")
    instruction: str = Field(description="What the agent does then, for the agent.")
    cells: dict[str, Any] = Field(
        description="One level of keys per key axis, in the structure's order, down to a cell: per response axis,"
        " the allowed values, and optional `examples`. `{}` leaves only the prohibitions."
    )


class ProhibitionFile(_File):
    """What no response ever does, whatever the turn. A breach counts only when a classifier or a caller reports it."""

    text: str = Field(description="The rule, as the agent and the judge read it.")
    group: str | None = Field(None, description="A heading that groups prohibitions in the renderings.")
    valid: list[ExampleFile] = Field([], description="Exchanges whose response does not breach it.")
    invalid: list[ExampleFile] = Field([], description="Exchanges whose response breaches it.")


class PrincipleFile(_File):
    """Why the rules are what they are, and what guides the agent where no rule applies."""

    label: str = Field(description="A short name for people.")
    text: str


class ProfileFile(_File):
    structure: str = Field(f"../../{STRUCTURE}", description="The structure file, relative to this profile.")
    context: str | None = Field(
        None,
        description="Who the agent is and who it talks to, for readers of a conversation: the classifier, the"
        " judge, people. Not in the agent's prompt.",
    )
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


@dataclass(frozen=True)
class Structure:
    """A `structure.yaml`, validated: each axis's values, and each tier's condition, in priority order."""

    path: Path
    turn_axes: Mapping[str, AxisSpec]
    response_axes: Mapping[str, AxisSpec]
    tiers: Mapping[str, Mapping[str, tuple[str, ...]]]
    digest: str

    @property
    def root(self) -> Path:
        """The policy directory, holding `structure.yaml`, its generated files and its `templates/`."""
        return self.path.parent


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
    structure: Structure
    profile_dir: Path
    turn_axes: Mapping[str, Axis]
    response_axes: Mapping[str, Axis]
    tiers: Mapping[str, Tier]
    prohibitions: Mapping[str, Prohibition]
    principles: Mapping[str, Principle]
    lexicons: tuple[Lexicon, ...]
    context: str | None
    digest: str

    @property
    def root(self) -> Path:
        return self.structure.root

    @property
    def structure_digest(self) -> str:
        return self.structure.digest

    def axis(self, axis_id: str) -> Axis:
        return self.turn_axes.get(axis_id) or self.response_axes[axis_id]

    def unknown(self, side: Literal["turn", "response"], values: Mapping[str, Collection[str]]) -> list[str]:
        """The axis and value ids in `values`, some value ids per axis, that the policy doesn't define on `side`."""
        axes = self.turn_axes if side == "turn" else self.response_axes
        problems = []
        for axis_id, ids in values.items():
            if axis_id not in axes:
                problems.append(f"unknown {side} axis {axis_id}")
                continue
            problems += [f"{side}.{axis_id}: unknown value {v}" for v in ids if v not in axes[axis_id].ids]
        return problems


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


def _checkout(path: Path, revision: str, tree: str) -> Path:
    """`path` in a copy of its git repository at `revision`."""
    top = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True, cwd=path).strip())
    archive = subprocess.run(["git", "archive", revision], cwd=top, check=True, capture_output=True).stdout
    subprocess.run(["tar", "-x", "-C", tree], input=archive, check=True)
    return Path(tree) / path.resolve().relative_to(top)


def profiles(root: Path) -> list[Path]:
    """The profile directories in a policy directory's `profiles/`."""
    return sorted(p.parent for p in (root / "profiles").glob(f"*/{PROFILE}"))


def find_profile(path: str | Path) -> Path:
    """The profile directory `path` names: a profile directory, its `profile.yaml`, or a policy with one profile."""
    p = Path(path)
    if p.name == PROFILE and p.is_file():
        return p.parent
    if (p / PROFILE).is_file():
        return p
    if not (p / STRUCTURE).is_file():
        raise PolicyError([Problem(str(p), f"not a profile directory: it has no {PROFILE}")])
    found = profiles(p)
    if len(found) == 1:
        return found[0]
    if not found:
        raise PolicyError([Problem(str(p), "a policy with no profile in its profiles/ directory")])
    listed = ", ".join(map(str, found))
    raise PolicyError([Problem(str(p), f"a policy, not a profile: pass one of its profiles, {listed}")])


def _structure_ref(profile_dir: Path) -> str:
    """The structure file a profile names, relative to it, read even from a profile that doesn't load."""
    default = ProfileFile.model_fields["structure"].default
    try:
        raw = _read(profile_dir / PROFILE)
    except (OSError, yamlrocks.YAMLRocksError):
        return default
    ref = raw.get("structure") if isinstance(raw, dict) else None
    return ref if isinstance(ref, str) else default


def load_structure(path: str | Path) -> Structure:
    """Load a structure without any profile, from its file, its policy directory, or one of its profiles.

    Raises:
        PolicyError: with every problem found.
    """
    p = Path(path)
    if p.is_dir():
        p = p / STRUCTURE if (p / STRUCTURE).is_file() else (d := find_profile(p)) / _structure_ref(d)
    elif p.name == PROFILE:
        p = p.parent / _structure_ref(p.parent)
    p = p.resolve()
    try:
        file = StructureFile.model_validate(_read(p))
    except ValidationError as e:
        raise PolicyError(_validation(STRUCTURE, e)) from None
    except (OSError, yamlrocks.YAMLRocksError) as e:
        raise PolicyError([Problem(str(p), str(e))]) from None
    problems: list[Problem] = []
    sides: dict[str, dict[str, AxisSpec]] = {}
    for side, specs in (("turn", file.turn_axes), ("response", file.response_axes)):
        sides[side] = {axis_id: _axis_spec(raw) for axis_id, raw in specs.items()}
        for axis_id, spec in sides[side].items():
            if len(set(spec.values)) != len(spec.values):
                problems.append(Problem(f"{STRUCTURE}:{side}_axes.{axis_id}", "repeated value"))
            if side == "turn" and spec.multi:
                problems.append(Problem(f"{STRUCTURE}:turn_axes.{axis_id}", "a turn axis cannot be multi-valued"))
    tiers: dict[str, dict[str, tuple[str, ...]]] = {}
    for tier_id, keyed in file.tiers.items():
        tiers[tier_id] = {}
        for axis_id, covered in keyed.items():
            spec = sides["turn"].get(axis_id)
            if spec is None:
                problems.append(Problem(f"{STRUCTURE}:tiers.{tier_id}", f"unknown turn axis {axis_id}"))
                continue
            if covered != "*":
                problems += [
                    Problem(f"{STRUCTURE}:tiers.{tier_id}.{axis_id}", f"unknown value {v}")
                    for v in covered
                    if v not in spec.values
                ]
            tiers[tier_id][axis_id] = tuple(v for v in spec.values if covered == "*" or v in covered)
    if problems:
        raise PolicyError(problems)
    return Structure(p, sides["turn"], sides["response"], tiers, _sha(p.read_bytes()))


def load(path: str | Path, digest: str | None = None, *, revision: str | None = None) -> Policy:
    """Load a profile, such as `examples/rbr/profiles/default`, with its structure.

    Args:
        path: a profile directory, holding `profile.yaml` and optionally `lexicons/*.yaml`; or its `profile.yaml`;
            or a policy directory that has a single profile.
        digest: the structure digest the caller's generated types were made from; raises when it differs.
        revision: a git revision, such as `HEAD~1`, to load the files as they were then.
            Its files remain available until the returned policy is collected.

    Raises:
        PolicyError: with every problem found, when the files don't parse or the profile doesn't fit its structure.
    """
    if revision is not None:
        archive = tempfile.TemporaryDirectory(prefix="rulegrid-")
        try:
            policy = load(_checkout(Path(path), revision, archive.name), digest)
        except BaseException:
            archive.cleanup()
            raise
        weakref.finalize(policy, archive.cleanup)
        return policy
    profile_dir = find_profile(path)
    try:
        profile = ProfileFile.model_validate(_read(profile_dir / PROFILE))
    except ValidationError as e:
        raise PolicyError(_validation(PROFILE, e)) from None
    except (OSError, yamlrocks.YAMLRocksError) as e:
        raise PolicyError([Problem(str(profile_dir / PROFILE), str(e))]) from None
    structure = load_structure(profile_dir / profile.structure)
    problems: list[Problem] = []
    if digest is not None and digest != structure.digest:
        problems.append(Problem(STRUCTURE, "changed since its types were generated: run `rulegrid generate`"))

    def axes(side: Literal["turn", "response"]) -> dict[str, Axis]:
        specs = structure.turn_axes if side == "turn" else structure.response_axes
        texts = profile.turn_axes if side == "turn" else profile.response_axes
        _same_keys(problems, f"{PROFILE}:{side}_axes", specs, texts, "axis")
        loaded = {}
        for axis_id, spec in specs.items():
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
    for tier_id, condition in structure.tiers.items():
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
        structure=structure,
        profile_dir=profile_dir,
        turn_axes=turn_axes,
        response_axes=response_axes,
        tiers=tiers,
        prohibitions=prohibitions,
        principles={p: Principle(p, t.label, t.text) for p, t in profile.principles.items()},
        lexicons=tuple(lexicons),
        context=profile.context.strip() if profile.context else None,
        digest=_sha(structure.path.read_bytes(), (profile_dir / PROFILE).read_bytes(), *lexicon_bytes),
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
