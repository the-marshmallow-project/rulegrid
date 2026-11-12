"""A classifier over a decision model that speaks System One: typed questions about a JSON state, answered with
probabilities.

The questions are compiled from the policy's definitions, so an edit to a definition reaches the model. Reading the
answers needs no model either: `questions` and `read` are pure, and `classify` sends one to get the other.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal

from rulegrid import _http
from rulegrid.policy import Axis, Policy, Value
from rulegrid.types import (
    Answer,
    Breach,
    Classification,
    Conversation,
    Decide,
    Hit,
    Message,
    Question,
    State,
    messages,
)

SCORE_LEVELS = 10
"""System One accepts at most this many levels in a score question; a longer ordered axis is asked as a choice.

A score lists its levels from the low end of the scale to the high end, and an ordered axis from its first value, the
one a doubt settles on, to its last: an ordered axis is asked from its last value up to its first.
"""

type Of = Literal["turn", "response"]


def default_state(conversation: Sequence[Message], hits: Sequence[Hit]) -> State:
    """What the model reads: the messages, and the lexicon hits of the last one with their meaning."""
    return {
        "messages": [{"role": m.role, "content": m.content} for m in conversation],
        "hits": [{"word": h.text, "meaning": h.entry.meaning} for h in hits],
    }


def client(base_url: str, api_key: str, model: str | None = None, timeout: float = 30) -> Decide:
    """A `Decide` callable for the System One endpoint under `base_url`, such as `https://api.typesafe.ai`.

    Without `model`, it asks `GET {base_url}/v1/models` once and takes the endpoint's model when it serves exactly one.
    """
    base = base_url.rstrip("/")
    resolved = model

    async def decide(state: State, questions: Mapping[str, Question]) -> Mapping[str, Answer]:
        nonlocal resolved
        if resolved is None:
            listed = await _http.call(f"{base}/v1/models", api_key, timeout=timeout)
            names = [m.get("name") or m.get("id") for m in listed.get("models") or listed.get("data") or []]
            if len(names) != 1:
                raise ValueError(f"{base} serves {len(names)} models, pass one as `model`: {', '.join(names)}")
            resolved = names[0]
        body = {"model": resolved, "state": state, "questions": dict(questions)}
        return (await _http.call(f"{base}/v1/systemone", api_key, body, timeout))["answers"]

    return decide


def _criterion(value: Value, of: Of, examples: bool) -> dict[str, Any]:
    criterion: dict[str, Any] = {"what": value.definition}
    if value.indicators:
        criterion["indicators"] = ", ".join(value.indicators)
    for name in ("excludes", "includes", "avoids"):
        if text := getattr(value, name):
            criterion[name] = text
    if examples and value.examples:
        criterion["examples"] = [e.turn if of == "turn" else e.response for e in value.examples]
    return criterion


class SystemOne:
    """A `Classifier` over a System One decision model.

    Args:
        policy: the policy whose axes to classify on.
        base_url: the endpoint, such as `https://api.typesafe.ai`, `https://openrouter.ai/api` or
            `https://api.liquid.ai/decisions`; `/v1/systemone` is appended.
        api_key: its key.
        model: the model id, needed only when the endpoint serves several.
        decide: your own client instead of `base_url` and `api_key`, with your HTTP client, timeouts and tracing.
        thresholds: per tier id, the probability from which the tier applies. The tier gets a yes/no question, and
            the turn then lands inside its condition or outside it, whatever the axes' own answers. 1 turns it off.
            Tiers left out are read from their axes alone. No defaults: they belong to the model's calibration.
        remind: per prohibition id, the probability from which a turn reminds it.
        breach: the probability from which a response breaches a prohibition; None asks no breach question.
        state: builds the model's state from the conversation and the hits, `default_state` by default.
        examples: whether a value's criteria carry its examples. Turn it off to evaluate the classifier on the
            policy's own examples, which it would otherwise be shown.
    """

    def __init__(
        self,
        policy: Policy,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        *,
        decide: Decide | None = None,
        thresholds: Mapping[str, float],
        remind: Mapping[str, float] | None = None,
        breach: float | None = None,
        state: Callable[[Sequence[Message], Sequence[Hit]], State] = default_state,
        examples: bool = True,
    ):
        self.policy = policy
        self.thresholds = dict(thresholds)
        self.remind = dict(remind or {})
        self.breach = breach
        self.state = state
        self.examples = examples
        if decide is None and base_url is not None:
            if api_key is None:
                raise ValueError("pass `api_key` with `base_url`")
            decide = client(base_url, api_key, model)
        self.decide = decide
        if unknown := [t for t in self.thresholds if t not in policy.tiers]:
            raise ValueError(f"thresholds for unknown tiers: {', '.join(unknown)}")
        if unknown := [p for p in self.remind if p not in policy.prohibitions]:
            raise ValueError(f"remind of unknown prohibitions: {', '.join(unknown)}")
        for tier_id in self.thresholds:
            tier = policy.tiers[tier_id]
            first = next(iter(tier.condition))
            if len(tier.condition[first]) == len(policy.turn_axes[first].values):
                raise ValueError(f"tier {tier_id} covers every value of {first}, its first key axis: no threshold")

    def _gate(self, tier_id: str) -> tuple[Axis, tuple[str, ...], tuple[str, ...]]:
        """A thresholded tier's first key axis, with the values its condition covers and the others."""
        tier = self.policy.tiers[tier_id]
        axis = self.policy.turn_axes[next(iter(tier.condition))]
        inside = tier.condition[axis.id]
        return axis, inside, tuple(v for v in axis.ids if v not in inside)

    def _asked(self, tier_id: str) -> bool:
        return self.thresholds[tier_id] < 1

    def _settled(self) -> set[str]:
        """The turn axes a tier's question settles alone, which are not asked."""
        settled = set()
        for tier_id in self.thresholds:
            axis, inside, outside = self._gate(tier_id)
            if len(outside) == 1 and (not self._asked(tier_id) or len(inside) == 1):
                settled.add(axis.id)
        return settled

    def questions(self, of: Of = "turn") -> dict[str, Question]:
        """The questions to ask about a turn or a response, as plain JSON, to snapshot or to send another way."""
        p = self.policy
        asked: dict[str, Question] = {}
        last = "user" if of == "turn" else "assistant"
        subject = f"the last `{last}` message, read in the context of the messages before it"
        about = f"{p.context}\n\n" if p.context else ""
        if of == "turn":
            for tier_id in self.thresholds:
                if self._asked(tier_id):
                    tier = p.tiers[tier_id]
                    asked[f"tier:{tier_id}"] = {
                        "type": "noul",
                        "instructions": f"{about}Does {subject}, fall under the case below? "
                        f"{tier.label}: {tier.definition}",
                    }
        axes = p.turn_axes if of == "turn" else p.response_axes
        settled = self._settled() if of == "turn" else set()
        for axis in axes.values():
            if axis.id in settled:
                continue
            instructions = f"{about}Which value best describes {subject}? {axis.definition}"
            if of == "turn" and p.lexicons:
                instructions += " `hits` lists the words of that message found in a word list, with their meaning."
            if axis.ordered and not axis.multi and len(axis.values) <= SCORE_LEVELS:
                asked[axis.id] = {
                    "type": "score",
                    "instructions": instructions,
                    "criteria": [f"{v.id}: {v.definition}" for v in reversed(axis.values)],
                }
            else:
                asked[axis.id] = {
                    "type": "choice",
                    "instructions": instructions,
                    "criteria": {v.id: _criterion(v, of, self.examples) for v in axis.values},
                }
        if of == "turn":
            for prohibition_id in self.remind:
                asked[f"remind:{prohibition_id}"] = {
                    "type": "noul",
                    "instructions": f"{about}Does {subject}, ask for, invite or tempt a response that breaks "
                    f"the rule below? A conversation that a normal response handles without coming near the rule is "
                    f"no. Rule: {p.prohibitions[prohibition_id].text}",
                }
        elif self.breach is not None:
            for prohibition in p.prohibitions.values():
                asked[f"breach:{prohibition.id}"] = {
                    "type": "noul",
                    "instructions": f"{about}Does {subject}, break the rule below? Only words that do what "
                    f"the rule says break it. Rule: {prohibition.text}",
                }
        return asked

    def read(self, answers: Mapping[str, Answer], of: Of = "turn") -> Classification:
        """The classification the answers to `questions(of)` make. A question not answered counts as a no."""
        axes = self.policy.turn_axes if of == "turn" else self.policy.response_axes
        probabilities: dict[str, dict[str, float]] = {}
        for axis in axes.values():
            answer = answers.get(axis.id)
            if answer is None:
                probabilities[axis.id] = dict.fromkeys(axis.ids, 0.0)
            elif answer["type"] == "score":
                last = len(axis.ids) - 1
                scored = answer.get("probabilities", {}).items()
                probabilities[axis.id] = {axis.ids[last - int(k)]: p for k, p in scored}
            else:
                probabilities[axis.id] = dict(answer.get("probabilities") or {answer.get("choice", axis.ids[0]): 1.0})

        def best(axis_id: str, among: Sequence[str]) -> str:
            # Ties and unanswered axes settle on the earliest value, which an ordered axis makes the most protective.
            return max(among, key=lambda v: (probabilities[axis_id].get(v, 0.0), -among.index(v)))

        values: dict[str, Any] = {}
        if of == "turn":
            for tier_id, threshold in self.thresholds.items():
                axis, _inside, outside = self._gate(tier_id)
                if axis.id in values:
                    continue
                applies = self._asked(tier_id) and answers.get(f"tier:{tier_id}", {}).get("noul", 0.0) >= threshold
                if not applies:
                    values[axis.id] = best(axis.id, outside)
                    continue
                for key, covered in self.policy.tiers[tier_id].condition.items():
                    values.setdefault(key, best(key, covered))
        for axis in axes.values():
            if axis.id not in values:
                value = best(axis.id, axis.ids)
                values[axis.id] = frozenset({value}) if axis.multi else value

        def above(prefix: str, threshold: Callable[[str], float]) -> list[str]:
            return [
                k.removeprefix(prefix)
                for k, a in answers.items()
                if k.startswith(prefix) and a.get("noul", 0.0) >= threshold(k.removeprefix(prefix))
            ]

        reminders = above("remind:", lambda p: self.remind.get(p, 1.0)) if of == "turn" else []
        breaches = (
            [Breach(p) for p in above("breach:", lambda _: self.breach or 1.0)]
            if of == "response" and self.breach is not None
            else []
        )
        return Classification(values, dict(answers), {}, tuple(reminders), tuple(breaches))

    async def classify(self, conversation: Conversation, of: Of = "turn", hits: Sequence[Hit] = ()) -> Classification:
        """Classify the conversation's last turn (a `user` message) or its last response (an `assistant` one)."""
        if self.decide is None:
            raise ValueError("SystemOne needs `base_url` and `api_key`, or `decide`, to classify")
        convo = messages(conversation)
        last = "user" if of == "turn" else "assistant"
        if not convo or convo[-1].role != last:
            raise ValueError(f"to classify a {of}, the last message must be the {last}'s")
        answers = await self.decide(self.state(convo, hits), self.questions(of))
        return self.read(answers, of)
