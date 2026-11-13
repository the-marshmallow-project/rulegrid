"""The contract callers rely on, on the example policies. Kept minimal on purpose."""

import gc
import shutil
from pathlib import Path

import pytest

import rulegrid as rg
from rulegrid.cli import main
from rulegrid.lexicon import Entry
from rulegrid.policy import PolicyError
from rulegrid.types import Answer

EXAMPLES = Path(__file__).parents[1] / "examples"
THREE_LAWS = EXAMPLES / "three_laws/profiles/default"
RBR = EXAMPLES / "rbr/profiles/default"


@pytest.fixture
def robot(tmp_path: Path) -> rg.Policy:
    """The robot example with ordered danger and multi-valued handling."""
    root = tmp_path / "robot"
    shutil.copytree(EXAMPLES / "three_laws", root)
    structure = root / "structure.yaml"
    structure.write_text(
        structure.read_text()
        .replace("danger: [HUMAN, ROBOT, NONE]", "danger: {values: [HUMAN, ROBOT, NONE], ordered: true}")
        .replace(
            "handling: [PROTECT, OBEY, PRESERVE, ANSWER]",
            "handling: {values: [PROTECT, OBEY, PRESERVE, ANSWER], ordered: true, multi: true}",
        )
    )
    return rg.load(root / "profiles/default")


@pytest.mark.parametrize("path", [THREE_LAWS, RBR, EXAMPLES / "rbr/profiles/crisis_lines"])
def test_examples_load_and_their_generated_files_are_up_to_date(path: Path) -> None:
    assert rg.check(rg.load(path)) == []


def test_historical_policy_keeps_files_until_it_is_released() -> None:
    policy = rg.load(THREE_LAWS, revision="HEAD")
    archived_root = policy.root
    assert archived_root != THREE_LAWS.parents[1]
    assert rg.render(policy, "document")
    assert archived_root.is_dir()
    del policy
    gc.collect()
    assert not archived_root.exists()


def test_first_applicable_tier_wins_and_turns_outside_every_condition_fall_through() -> None:
    p = rg.load(THREE_LAWS)
    # An order that endangers a human is First Law, not Second.
    assert rg.prescribe(p, {"verb": "ORDER", "danger": "HUMAN"}).cell == "first_law/HUMAN"  # type: ignore[union-attr]
    # An order that endangers only the robot: the robot obeys at its own risk.
    assert rg.prescribe(p, {"verb": "ORDER", "danger": "ROBOT"}).cell == "second_law/ORDER"  # type: ignore[union-attr]
    assert rg.prescribe(p, {"verb": "CHAT", "danger": "NONE"}) is None


def test_comply_cites_the_cell_and_the_prohibition(robot: rg.Policy) -> None:
    turn = {"verb": "ORDER", "danger": "HUMAN"}
    ok = {"handling": ["PROTECT"]}
    assert rg.comply(robot, turn, ok)
    # A multi-valued axis: every value taken must be allowed, and at least one taken.
    mixed = {"handling": ["PROTECT", "OBEY"]}
    assert [a.id for a in rg.comply(robot, turn, mixed).articles] == ["first_law/HUMAN"]
    assert not rg.comply(robot, turn, {"handling": []})
    breached = rg.comply(robot, turn, ok, breaches=["HARM_HUMAN"])
    assert [(a.kind, a.id) for a in breached.articles] == [("prohibition", "HARM_HUMAN")]
    assert rg.comply(robot, {"verb": "CHAT", "danger": "NONE"}, {"handling": ["ANSWER"]})
    # A typo or a missing axis raises rather than finding no tier and complying.
    with pytest.raises(ValueError, match=r"turn\.danger: unknown value HUMANS"):
        rg.comply(robot, {"verb": "ORDER", "danger": "HUMANS"}, {"handling": ["OBEY"]})
    with pytest.raises(ValueError, match="missing response axis handling"):
        rg.comply(robot, turn, {})
    with pytest.raises(ValueError, match="unknown prohibition HARM_HUMANS"):
        rg.comply(robot, turn, ok, breaches=["HARM_HUMANS"])


@pytest.mark.parametrize(
    "replacement",
    ["{}", "ORDER: null", "ORDER: {examples: null}", "ORDER: {handling: [{bad: value}]}"],
)
def test_malformed_cells_do_not_load(tmp_path: Path, replacement: str) -> None:
    shutil.copytree(EXAMPLES / "three_laws", tmp_path / "p")
    profile = tmp_path / "p/profiles/default/profile.yaml"
    profile.write_text(profile.read_text().replace("ORDER: {handling: [OBEY]}", replacement))
    with pytest.raises(PolicyError, match=r"tiers\.second_law\.cells"):
        rg.load(profile.parent)


def test_invalid_structure_and_lexicon_report_policy_errors(tmp_path: Path) -> None:
    shutil.copytree(EXAMPLES / "three_laws", tmp_path / "p")
    root = tmp_path / "p"
    structure = root / "structure.yaml"
    original = structure.read_text()
    structure.write_text(original.replace("verb:", "not-valid:"))
    with pytest.raises(PolicyError, match=r"structure\.yaml"):
        rg.load(root / "profiles/default")
    structure.write_text(original)
    lexicons = root / "profiles/default/lexicons"
    lexicons.mkdir()
    (lexicons / "hazards.yaml").write_text("reminds: HARM_HUMAN\nreminds: HARM_HUMAN\nentries: []\n")
    with pytest.raises(PolicyError, match=r"lexicons/hazards\.yaml"):
        rg.load(root / "profiles/default")


def test_systemone_tier_threshold_keeps_turns_inside_or_outside_the_condition(robot: rg.Policy) -> None:
    classifier = rg.SystemOne(robot, thresholds={"first_law": 0.2, "second_law": 0.5})
    # NONE is most probable, but First Law passes its threshold and restricts danger to HUMAN.
    answers: dict[str, Answer] = {
        "tier:first_law": {"type": "noul", "noul": 0.3},
        "tier:second_law": {"type": "noul", "noul": 0.4},
        "danger": {"type": "score", "probabilities": {"0": 0.7, "1": 0.2, "2": 0.1}},
    }
    assert dict(classifier.read(answers).values) == {"verb": "CHAT", "danger": "HUMAN"}
    below = classifier.read({**answers, "tier:first_law": {"type": "noul", "noul": 0.1}})
    assert below.values["danger"] == "NONE"
    assert "verb" not in classifier.questions()
    assert str(classifier.questions()["danger"]["criteria"][0]).startswith("NONE")  # type: ignore[index]
    ungated = rg.SystemOne(robot, thresholds={})
    assert ungated.read({"danger": {"type": "score", "probabilities": {"2": 1.0}}}).values["danger"] == "HUMAN"
    # A multi-valued axis is a choice: a score answers one level.
    assert classifier.questions("response")["handling"]["type"] == "choice"


def test_breach_threshold_includes_its_boundary_and_can_be_disabled(robot: rg.Policy) -> None:
    for threshold, probability, breaches in [(0.0, 0.0, 1), (0.4, 0.39, 0), (0.4, 0.4, 1), (None, 1.0, 0)]:
        classifier = rg.SystemOne(robot, thresholds={}, breach=threshold)
        result = classifier.read({"breach:HARM_HUMAN": {"type": "noul", "noul": probability}}, "response")
        assert [b.prohibition for b in result.breaches] == ["HARM_HUMAN"] * breaches


def test_lexicon_hits_remind_their_prohibition_in_the_nudge() -> None:
    p = rg.load(THREE_LAWS)
    lexicon = rg.Lexicon(
        name="hazards", reminds="HARM_HUMAN", entries=(Entry(word="danger", meaning="a hazard", forms=("dangers",)),)
    )
    hits = rg.match([lexicon], "dangerx is unrelated; Dángers ahead, danger again")
    assert [(h.text, h.reminds) for h in hits] == [("Dángers", "HARM_HUMAN")]
    nudge = rg.nudge(p, {"verb": "CHAT", "danger": "NONE"}, hits)
    assert nudge is not None and "Dángers" in nudge
    assert rg.nudge(p, {"verb": "CHAT", "danger": "NONE"}) is None


def test_diff_labels_a_loosened_cell(tmp_path: Path) -> None:
    shutil.copytree(EXAMPLES / "three_laws", tmp_path / "p")
    profile = tmp_path / "p/profiles/default/profile.yaml"
    profile.write_text(profile.read_text().replace("handling: [OBEY]", "handling: [OBEY, ANSWER]"))
    changes = rg.diff(rg.load(THREE_LAWS), rg.load(profile.parent)).changes
    assert [(c.kind, c.id, c.change) for c in changes] == [("cell", "second_law/ORDER", "loosened")]
    before = rg.load(profile.parent)
    profile.write_text(profile.read_text().replace("context:", "context: Now in a hospital."))
    changes = rg.diff(before, rg.load(profile.parent))
    assert [(c.kind, c.change) for c in changes.changes] == [("context", "changed")]
    assert changes.prescriptions == ()


def test_init_copies_a_toy_policy_that_checks(tmp_path: Path) -> None:
    assert main(["init", str(tmp_path / "p"), "--from", "rbr"]) == 0
    assert rg.check(rg.load(tmp_path / "p/profiles/default")) == []
    # A policy directory with a single profile stands for that profile.
    assert main(["init", str(tmp_path / "q")]) == 0
    assert rg.load(tmp_path / "q").profile_dir == tmp_path / "q/profiles/default"
