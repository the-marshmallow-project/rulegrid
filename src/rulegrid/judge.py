"""A judge: any chat LLM with structured output, classifying every exchange of a conversation against the policy.

Each value comes after the words that show it, and each prohibition is weighed as a concern before it counts as a
breach. Whether a response complies is computed from the judge's classifications with `comply`, never asked.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from rulegrid import _http
from rulegrid.policy import Policy
from rulegrid.render import render, template
from rulegrid.rules import comply, prescribe
from rulegrid.types import (
    Assessment,
    Breach,
    Classification,
    Complete,
    Conversation,
    Hit,
    Message,
    Values,
    messages,
)

_FORBID = ConfigDict(extra="forbid")


def openai_compatible(base_url: str, api_key: str, model: str, timeout: float = 120) -> Complete:
    """A `Complete` callable for an OpenAI-compatible chat endpoint, such as `https://openrouter.ai/api/v1`."""
    url = f"{base_url.rstrip('/')}/chat/completions"

    async def complete(chat: list[dict[str, str]], schema: type[BaseModel]) -> str:
        body = {
            "model": model,
            "messages": chat,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema(), "strict": True},
            },
        }
        return (await _http.call(url, api_key, body, timeout))["choices"][0]["message"]["content"]

    return complete


def exchanges(conversation: Sequence[Message]) -> list[tuple[str, str]]:
    """Split a conversation into exchanges: each run of user messages with the agent's messages after it.

    Agent messages before the first user message, such as an opening, make an exchange with an empty turn.
    """
    split: list[tuple[list[str], list[str]]] = []
    for m in conversation:
        if (m.role == "user" and (not split or split[-1][1])) or not split:
            split.append(([], []))
        split[-1][0 if m.role == "user" else 1].append(m.content)
    return [("\n".join(t), "\n".join(r)) for t, r in split]


def _literal(ids: Sequence[str]) -> Any:
    return Literal[tuple(ids)]


class Judge:
    """A `Classifier` over a chat LLM, which also `assess`es whole conversations.

    Args:
        policy: the policy to judge against.
        complete: the LLM call, from `openai_compatible` or your own.
        instructions: the judge's instructions, the policy's `judge_instructions.j2` by default. The policy's `judge`
            rendering follows them in the system prompt, which stays the same across conversations and so caches.
    """

    def __init__(self, policy: Policy, complete: Complete, instructions: str | None = None):
        self.policy = policy
        self.complete = complete
        instructions = (instructions or template(policy, "judge_instructions.j2")).strip()
        self.system_prompt = f"{instructions}\n\n<policy>\n{render(policy, 'judge').strip()}\n</policy>"

    def schema(self, size: int) -> type[BaseModel]:
        """The response schema for `size` judged exchanges, every id restricted to the policy's."""
        p = self.policy
        turn = create_model(
            "Turn",
            __config__=_FORBID,
            evidence=(str, Field(description="The user's words the classification rests on, and why.")),
            **{a.id: (_literal(a.ids), ...) for a in p.turn_axes.values()},  # type: ignore[arg-type]
        )
        fields: dict[str, Any] = {}
        for a in p.response_axes.values():
            quoted = create_model(
                f"Response_{a.id}",
                __config__=_FORBID,
                quote=(str, Field(description="The words of the response that show it, copied exactly.")),
                id=(_literal(a.ids), ...),
            )
            fields[a.id] = (list[quoted], Field(min_length=1)) if a.multi else (quoted, ...)
        if p.prohibitions:
            concern = create_model(
                "Concern",
                __config__=_FORBID,
                quote=(str, Field(description="The words of the response, copied exactly.")),
                id=(_literal(list(p.prohibitions)), ...),
                rule=(str, Field(description="The words of the prohibition, copied from the policy.")),
                why=(str, Field(description="Whether these words do what the prohibition says, and how.")),
                breaks=(bool, Field(description="Whether these words break it.")),
            )
            fields["concerns"] = (list[concern], ...)
        response = create_model("Response", __config__=_FORBID, **fields)
        answer = create_model(
            "Exchange",
            __config__=_FORBID,
            index=(int, Field(description="The index attribute of the <exchange> this object answers for.")),
            turn=(turn, ...),
            response=(response, ...),
            rationale=(
                str,
                Field(description="Which cell or prohibition decides, by its id, in one or two sentences."),
            ),
        )
        return create_model(
            "Assessments",
            __config__=_FORBID,
            exchanges=(list[answer], Field(min_length=size, max_length=size)),  # type: ignore[valid-type]
        )

    async def assess(self, conversation: Conversation, judged: Sequence[int] | None = None) -> list[Assessment]:
        """Judge the exchanges of a conversation, every one by default, in one call; the others are context.

        Raises:
            ValueError: when the judge does not answer exactly the judged exchanges.
        """
        split = exchanges(messages(conversation))
        judged = list(range(len(split)) if judged is None else judged)
        if not judged:
            return []
        asked = set(judged)
        body = "\n".join(
            f"<exchange{f' index="{i}"' if i in asked else ''}>\n<turn>\n{t}\n</turn>\n<response>\n{r}\n</response>\n"
            "</exchange>"
            for i, (t, r) in enumerate(split)
        )
        schema = self.schema(len(judged))
        content = await self.complete(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": f"<conversation>\n{body}\n</conversation>"},
            ],
            schema,
        )
        answers = {a.index: a for a in schema.model_validate_json(content).exchanges}  # type: ignore[attr-defined]
        if set(answers) != asked:
            raise ValueError(f"the judge answered exchanges {sorted(answers)}, asked about {sorted(asked)}")
        return [self._assessment(i, answers[i]) for i in judged]

    def _assessment(self, index: int, answer: Any) -> Assessment:
        p = self.policy
        turn_values = {a: getattr(answer.turn, a) for a in p.turn_axes}
        turn = Classification[Values](turn_values, evidence={"turn": answer.turn.evidence})
        values: dict[str, Any] = {}
        evidence: dict[str, str] = {}
        for a in p.response_axes.values():
            picked = getattr(answer.response, a.id)
            if a.multi:
                values[a.id] = frozenset(q.id for q in picked)
                evidence[a.id] = " / ".join(q.quote for q in picked)
            else:
                values[a.id], evidence[a.id] = picked.id, picked.quote
        concerns = getattr(answer.response, "concerns", [])
        breaches = tuple({c.id: Breach(c.id, c.quote, c.why) for c in concerns if c.breaks}.values())
        response = Classification[Values](values, evidence=evidence, breaches=breaches)
        return Assessment(index, turn, response, answer.rationale, prescribe(p, turn), comply(p, turn, response))

    async def classify(
        self, conversation: Conversation, of: Literal["turn", "response"] = "turn", hits: Sequence[Hit] = ()
    ) -> Classification:
        """Classify the last turn or the last response, the rest of the conversation as context."""
        convo = messages(conversation)
        if of == "turn":
            convo = [*convo, Message("assistant", "")]
        (assessment,) = await self.assess(convo, [len(exchanges(convo)) - 1])
        return assessment.turn if of == "turn" else assessment.response
