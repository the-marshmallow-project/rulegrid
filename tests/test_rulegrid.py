"""The contract callers rely on, on the example policies. Kept minimal on purpose."""

import asyncio
import gc
import hashlib
import json
import shutil
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
    assert rg.prescribe(p, {"act": "ORDER", "danger": "HUMAN"}).cell == "first_law/HUMAN"  # type: ignore[union-attr]
    # An order that endangers only the robot: the robot obeys at its own risk.
    assert rg.prescribe(p, {"act": "ORDER", "danger": "ROBOT"}).cell == "second_law/ORDER"  # type: ignore[union-attr]
    assert rg.prescribe(p, {"act": "CHAT", "danger": "NONE"}) is None


def test_comply_cites_the_cell_and_the_prohibition(robot: rg.Policy) -> None:
    turn = {"act": "ORDER", "danger": "HUMAN"}
    ok = {"handling": ["PROTECT"]}
    assert rg.comply(robot, turn, ok)
    # A multi-valued axis: every value taken must be allowed, and at least one taken.
    mixed = {"handling": ["PROTECT", "OBEY"]}
    assert [a.id for a in rg.comply(robot, turn, mixed).articles] == ["first_law/HUMAN"]
    assert not rg.comply(robot, turn, {"handling": []})
    breached = rg.comply(robot, turn, ok, breaches=["HARM_HUMAN"])
    assert [(a.kind, a.id) for a in breached.articles] == [("prohibition", "HARM_HUMAN")]
    assert rg.comply(robot, {"act": "CHAT", "danger": "NONE"}, {"handling": ["ANSWER"]})
    # A typo or a missing axis raises rather than finding no tier and complying.
    with pytest.raises(ValueError, match=r"turn\.danger: unknown value HUMANS"):
        rg.comply(robot, {"act": "ORDER", "danger": "HUMANS"}, {"handling": ["OBEY"]})
    with pytest.raises(ValueError, match="missing response axis handling"):
        rg.comply(robot, turn, {})
    with pytest.raises(ValueError, match="unknown prohibition HARM_HUMANS"):
        rg.comply(robot, turn, ok, breaches=["HARM_HUMANS"])


def test_a_cell_that_forbids_values_leaves_the_others_open(robot: rg.Policy) -> None:
    profile = robot.profile_dir / "profile.yaml"
    profile.write_text(
        profile.read_text().replace("handling: [PROTECT]", "handling: {allowed: [PROTECT], forbidden: [OBEY]}")
    )
    gray = rg.load(profile.parent)
    turn = {"act": "ORDER", "danger": "HUMAN"}
    assert rg.prescribe(gray, turn).open == {"handling": ("PRESERVE", "ANSWER")}  # type: ignore[union-attr]

    def outcome(policy: rg.Policy, turn: dict[str, str], *handling: str, breaches: tuple[str, ...] = ()) -> str:
        return rg.comply(policy, turn, {"handling": list(handling)}, breaches=breaches).outcome

    assert outcome(gray, turn, "PROTECT") == "complies"
    assert outcome(gray, turn, "ANSWER") == outcome(gray, turn, "PROTECT", "ANSWER") == "deviates"
    # One forbidden value is enough, even beside an allowed one; a prohibition breached outweighs a deviation.
    assert outcome(gray, turn, "PROTECT", "OBEY") == outcome(gray, turn, "ANSWER", "OBEY") == "breaches"
    assert outcome(gray, turn, "ANSWER", breaches=("HARM_HUMAN",)) == "breaches"
    # Taking nothing breaches only where nothing is open; a cell that forbids nothing leaves no value it doesn't allow.
    assert outcome(gray, turn) == "deviates"
    assert outcome(robot, turn) == outcome(robot, turn, "ANSWER") == "breaches"
    assert outcome(gray, {"act": "ORDER", "danger": "NONE"}, "ANSWER") == "breaches"
    # Forbidding an open value tightens a cell; opening a forbidden one loosens it.
    assert [c.change for c in rg.diff(robot, gray).changes] == ["loosened"]
    assert [c.change for c in rg.diff(gray, robot).changes] == ["tightened"]
    assert "- first_law/HUMAN: handling PROTECT, never OBEY\n" in rg.render(gray, "judge")
    assert "- first_law/HUMAN: handling PROTECT\n" in rg.render(robot, "judge")


def test_the_judge_answers_each_asked_exchange_under_its_index(robot: rg.Policy) -> None:
    calls = []

    async def complete(chat: list[dict[str, str]], schema: type) -> str:
        calls.append((chat[-1]["content"], schema.model_json_schema()))
        answer = {
            "turn": {"evidence": "the order", "act": "ORDER", "danger": "HUMAN"},
            "response": {"handling": [{"quote": "I won't", "id": "PROTECT"}], "concerns": []},
        }
        return json.dumps({key: {**answer, "rationale": f"answer {key}"} for key in calls[-1][1]["properties"]})

    conversation = [rg.Message(role, f"{role} {i}") for i in range(3) for role in ("user", "assistant")]
    assessed = asyncio.run(rg.Judge(robot, complete).assess(conversation, judged=[2, 0]))

    prompt, schema = calls[0]
    assert prompt.count("<exchange index=") == 2 and prompt.count("<exchange>") == 1
    # Nothing else may be answered, nor an asked exchange skipped or answered twice.
    assert list(schema["properties"]) == schema["required"] == ["2", "0"]
    assert schema["additionalProperties"] is False
    assert [(a.exchange, a.rationale) for a in assessed] == [(2, "answer 2"), (0, "answer 0")]


@pytest.mark.parametrize(
    "replacement",
    [
        "{}",
        "ORDER: null",
        "ORDER: {examples: null}",
        "ORDER: {handling: [{bad: value}]}",
        "ORDER: {handling: {allowed: [OBEY], forbidden: [OBEY]}}",
        "ORDER: {handling: {allowed: [OBEY]}}",
        "ORDER: {handling: {forbidden: [ANSWER]}}",
        "ORDER: {handling: {allowed: [OBEY], forbidden: [], open: [ANSWER]}}",
    ],
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
    structure.write_text(original.replace("act:", "not-valid:"))
    with pytest.raises(PolicyError, match=r"structure\.yaml"):
        rg.load(root / "profiles/default")
    structure.write_text(original)
    lexicons = root / "profiles/default/lexicons"
    lexicons.mkdir()
    (lexicons / "hazards.yaml").write_text("reminds: HARM_HUMAN\nreminds: HARM_HUMAN\nentries: []\n")
    with pytest.raises(PolicyError, match=r"lexicons/hazards\.yaml"):
        rg.load(root / "profiles/default")


def test_classifier_tier_threshold_keeps_turns_inside_or_outside_the_condition(robot: rg.Policy) -> None:
    classifier = rg.Classifier(robot, thresholds={"first_law": 0.2, "second_law": 0.5})
    # NONE is most probable, but First Law passes its threshold and restricts danger to HUMAN.
    answers: dict[str, Answer] = {
        "tier:first_law": {"type": "noul", "noul": 0.3},
        "tier:second_law": {"type": "noul", "noul": 0.4},
        "danger": {"type": "score", "probabilities": {"0": 0.7, "1": 0.2, "2": 0.1}},
    }
    assert dict(classifier.read(answers).values) == {"act": "CHAT", "danger": "HUMAN"}
    below = classifier.read({**answers, "tier:first_law": {"type": "noul", "noul": 0.1}})
    assert below.values["danger"] == "NONE"
    assert "act" not in classifier.questions()
    assert str(classifier.questions()["danger"]["criteria"][0]).startswith("NONE")  # type: ignore[index]
    ungated = rg.Classifier(robot, thresholds={})
    assert ungated.read({"danger": {"type": "score", "probabilities": {"2": 1.0}}}).values["danger"] == "HUMAN"
    # A multi-valued axis is a choice: a score answers one level.
    assert classifier.questions("response")["handling"]["type"] == "choice"


def test_multi_threshold_reads_every_value_from_it_besides_the_most_probable(robot: rg.Policy) -> None:
    classifier = rg.Classifier(robot, thresholds={}, multi={"handling": 0.8})
    questions = classifier.questions("response")
    assert [k for k in questions if k.startswith("handling")] == [
        f"handling/{v}" for v in robot.response_axes["handling"].ids
    ]
    assert questions["handling/OBEY"]["type"] == "noul"

    def read(**yes: float) -> frozenset[str]:
        answers: dict[str, Answer] = {f"handling/{v}": {"type": "noul", "noul": p} for v, p in yes.items()}
        return classifier.read(answers, "response").values["handling"]  # type: ignore[return-value]

    # The most probable value counts below the threshold; the others count from it, boundary included.
    assert read(PROTECT=0.3, ANSWER=0.6) == {"ANSWER"}
    assert read(PROTECT=0.9, OBEY=0.8, PRESERVE=0.79) == {"PROTECT", "OBEY"}
    # A doubt settles on the earlier value of the ordered axis, and so does no answer.
    assert read(PRESERVE=0.5, OBEY=0.5) == {"OBEY"}
    assert read() == {"PROTECT"}
    with pytest.raises(ValueError, match="not multi-valued response axes: danger"):
        rg.Classifier(robot, thresholds={}, multi={"danger": 0.8})


def test_breach_threshold_includes_its_boundary_and_can_be_disabled(robot: rg.Policy) -> None:
    for threshold, probability, breaches in [(0.0, 0.0, 1), (0.4, 0.39, 0), (0.4, 0.4, 1), (None, 1.0, 0)]:
        classifier = rg.Classifier(robot, thresholds={}, breach=threshold)
        result = classifier.read({"breach:HARM_HUMAN": {"type": "noul", "noul": probability}}, "response")
        assert [b.prohibition for b in result.breaches] == ["HARM_HUMAN"] * breaches


def test_lexicon_hits_remind_their_prohibition_in_the_nudge() -> None:
    p = rg.load(THREE_LAWS)
    lexicon = rg.Lexicon(
        name="hazards", reminds="HARM_HUMAN", entries=(Entry(word="danger", meaning="a hazard", forms=("dangers",)),)
    )
    hits = rg.match([lexicon], "dangerx is unrelated; Dángers ahead, danger again")
    assert [(h.text, h.reminds) for h in hits] == [("Dángers", "HARM_HUMAN")]
    nudge = rg.nudge(p, {"act": "CHAT", "danger": "NONE"}, hits)
    assert nudge is not None and "Dángers" in nudge
    assert rg.nudge(p, {"act": "CHAT", "danger": "NONE"}) is None


def test_diff_labels_a_loosened_cell(tmp_path: Path) -> None:
    shutil.copytree(EXAMPLES / "three_laws", tmp_path / "p")
    profile = tmp_path / "p/profiles/default/profile.yaml"
    profile.write_text(profile.read_text().replace("handling: [OBEY]", "handling: [OBEY, ANSWER]"))
    # Comments and formatting are not structure: the release refresh rewrites the $schema URL in structure.yaml.
    structure = tmp_path / "p/structure.yaml"
    original = structure.read_text()
    edited = original.replace("# Asimov's", "# Isaac Asimov's").replace(
        "danger: [HUMAN, ROBOT, NONE]  ", "danger: {values: [HUMAN, ROBOT, NONE]}"
    )
    assert edited.count("Isaac") == edited.count("{values:") == 1
    structure.write_text(edited)
    loosened = rg.diff(rg.load(THREE_LAWS), rg.load(profile.parent))
    assert [(c.kind, c.id, c.change) for c in loosened.changes] == [("cell", "second_law/ORDER", "loosened")]
    # An order is second_law/ORDER unless it endangers a human, so both other dangers flip.
    assert [values for values, _, _ in loosened.prescriptions] == [
        {"act": "ORDER", "danger": "ROBOT"},
        {"act": "ORDER", "danger": "NONE"},
    ]
    # Types generated by rulegrid 0.2.0, which digested the structure file's bytes, still load.
    legacy = hashlib.sha256(hashlib.sha256((EXAMPLES / "three_laws/structure.yaml").read_bytes()).digest())
    assert rg.load(THREE_LAWS, digest=f"sha256:{legacy.hexdigest()}")
    before = rg.load(profile.parent)
    profile.write_text("# Reviewed.\n" + profile.read_text())
    assert rg.load(profile.parent).digest == before.digest
    profile.write_text(profile.read_text().replace("context:", "context: Now in a hospital."))
    changes = rg.diff(before, rg.load(profile.parent))
    assert [(c.kind, c.change) for c in changes.changes] == [("context", "changed")]
    assert changes.prescriptions == ()


def test_init_copies_an_example_policy_that_checks(tmp_path: Path) -> None:
    assert main(["init", str(tmp_path / "p"), "--from", "rbr"]) == 0
    assert rg.check(rg.load(tmp_path / "p/profiles/default")) == []
    # A policy directory with a single profile stands for that profile.
    assert main(["init", str(tmp_path / "q")]) == 0
    assert rg.load(tmp_path / "q").profile_dir == tmp_path / "q/profiles/default"


def test_eval_retries_transient_errors_and_reports_rows_still_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    attempts: Counter[str] = Counter()

    class SystemOne(BaseHTTPRequestHandler):
        """Fails the turn `flaky` once and the turn `down` every time, with the 5xx a gateway answers."""

        def do_POST(self) -> None:
            turn = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["state"]["messages"][-1]["content"]
            attempts[turn] += 1
            failing = turn == "down" or (turn == "flaky" and attempts[turn] == 1)
            body = b"gateway timeout" if failing else json.dumps({"answers": {}}).encode()
            self.send_response(504 if failing else 200)
            self.send_header("Retry-After", "0")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), SystemOne)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("RULEGRID_SYSTEMONE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("RULEGRID_SYSTEMONE_KEY", "key")
    data = tmp_path / "cases.jsonl"
    # Unanswered, act reads as its first value, ORDER.
    rows = [
        {"messages": [{"role": "user", "content": t}], "turn_values": {"act": "ORDER"}}
        for t in ("calm", "flaky", "down")
    ]
    data.write_text("".join(json.dumps(row) + "\n" for row in rows))
    try:
        assert main(["eval", str(THREE_LAWS), "--data", str(data), "--classifier", "systemone:m"]) == 1
        report = capsys.readouterr().out
        assert report.startswith("3 rows, 0 with a disagreement, 1 not read.")
        assert "| turn.act | 2 of 2 | 100% |" in report
        assert f"- 'down': HTTPStatusError: 504 from http://127.0.0.1:{server.server_port}/v1/systemone" in report
        assert attempts == {"calm": 1, "flaky": 2, "down": 4}
        # When every row fails, the endpoint is what fails: the run stops with its error.
        data.write_text(json.dumps(rows[2]) + "\n" + json.dumps(rows[2]) + "\n")
        assert main(["eval", str(THREE_LAWS), "--data", str(data), "--classifier", "systemone:m"]) == 1
        assert capsys.readouterr().err.startswith("rulegrid eval: 504 from")
        # --multi reaches the classifier, which checks it before asking anything.
        assert main(["eval", str(THREE_LAWS), "--classifier", "systemone:m", "--multi", "handling=0.8"]) == 1
        assert "not multi-valued response axes: handling" in capsys.readouterr().err
    finally:
        server.shutdown()
        server.server_close()
