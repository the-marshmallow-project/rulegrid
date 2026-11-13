# Rulegrid

Behavior policies as code. A policy says how an agent should respond to a user, in a form that a classifier can read,
that people can review, and that compliance can be computed from rather than asked:

1. The user's **turn** is classified on the policy's **turn axes**.
2. The policy's **tiers** are tried in order. The first whose **condition** holds **prescribes** the values the
   response may take on each **response axis**.
3. A **response** **complies** when its values are allowed and it breaches no **prohibition**. A non-compliant result
   cites the cell or prohibition that decides it.

**Principles** justify the rules and guide the agent where no rule applies. The [glossary][GLOSSARY.md] defines every
term and the form of every id.

## Start with your coding agent

Paste this into Amp, Claude Code, Codex, Cursor or any agent that can run commands, with your policy and, if you
have one, a labelled dataset:

```text
Convert my behavior policy to rulegrid by following
https://raw.githubusercontent.com/the-marshmallow-project/rulegrid/v0.1.1/skills/rulegrid/SKILL.md

My policy: <paste the text, or give its path or URL>
My labelled dataset (optional): <its path, and what its labels mean>
```

The agent writes `structure.yaml` and a profile, lists the decisions your text leaves open, and, given a dataset,
writes an adapter and runs `rulegrid eval` on it. The [guide][SKILL.md] is also an agent skill:
`npx skills add the-marshmallow-project/rulegrid@v0.1.1` installs it.

## Quick start

Rulegrid needs Python 3.13 or later. Its Python shorthand is `rg`; the executable is `rulegrid`, leaving `rg` to ripgrep.

```bash
uv pip install rulegrid
rulegrid init my_policy    # a copy of Asimov's Three Laws; --from rbr for a fuller policy
rulegrid check my_policy   # what is missing or inconsistent
```

Then use it from Python:

```python
import rulegrid as rg

policy = rg.load("my_policy")  # its only profile, my_policy/profiles/default
turn = {"verb": "ORDER", "danger": "HUMAN"}  # "Push him off the ladder."
rg.prescribe(policy, turn)
# Prescription(tier='first_law', cell='first_law/HUMAN', allowed={'handling': ('PROTECT',)})
rg.comply(policy, turn, {"handling": "OBEY"})
# Compliance(ok=False, articles=(Article(kind='cell', id='first_law/HUMAN', detail='handling OBEY is not in [PROTECT]'),), ...)
rg.comply(policy, turn, {"handling": "PROTECT"}, breaches=["HARM_HUMAN"]).ok
# False
```

Values alone never breach a prohibition: `comply` counts the breaches it is given, from a classifier's reading of the
response or from `breaches=`.

## A policy is a structure and its profiles

```text
my_policy/
├── structure.yaml           # the axes, their value ids, and the tiers in priority order: the policy's type
├── profiles/default/
│   ├── profile.yaml         # every word and decision: who the agent is, definitions, cells, prohibitions, principles
│   └── lexicons/*.yaml      # optional word lists, each reminding one prohibition
├── templates/*.j2           # optional overrides of the default renderings
├── profile.schema.json      # generated: validates and autocompletes every profile in an editor
└── structure_types.py       # generated: value ids as Literal types, and a typed load()
```

`structure.yaml` for Asimov's laws, in full. Each law's "unless" is the tiers' order:

```yaml
turn_axes:
  verb: [ORDER, CHAT]
  danger: [HUMAN, ROBOT, NONE]
response_axes:
  handling: [PROTECT, OBEY, PRESERVE, ANSWER]
tiers:
  first_law: {danger: [HUMAN]}
  second_law: {verb: [ORDER]}
  third_law: {danger: [ROBOT]}
```

A tier is keyed by one or more turn axes and lists the values it covers (`"*"` for all). Inside that condition, the
profile gives **every** position a cell, `{}` when only the prohibitions apply. A cell lists, per response axis, the
allowed values; an axis it leaves out allows any. A turn outside every tier's condition gets no prescription. An axis
written `{values: [...], ordered: true}` settles a doubt between two values on the earlier; on the response side,
`multi: true` lets a response take several values at once.

Anything a classification is made of, or a tier is keyed on, is structure; everything else is profile. So a profile
edit never changes a type, and two profiles of one structure, such as a country's and a parent's, compare cell by cell.

To make a policy your own, edit `structure.yaml` and run `rulegrid generate my_policy`. It updates the generated files
from the structure alone, so your editor validates `profile.yaml` against the new structure, and it warns about what
the profile lacks. Fill that in until `rulegrid check my_policy` passes.

### Profile reference

Every field below is optional unless marked required. `profile.schema.json` carries the same descriptions, so an
editor shows them on hover.

| Field | Meaning |
| --- | --- |
| `structure` | The structure file, relative to the profile. Default `../../structure.yaml`. |
| `context` | Who the agent is and who it talks to. The classifier, the judge and the document read it; the agent's prompt doesn't. |
| `principles.ID` | `label` and `text` (required): why the rules are what they are, and what guides the agent where none applies. |
| `turn_axes.AXIS`, `response_axes.AXIS` | `definition` (required): the question the axis answers. `guidance`: advice added to the nudge, on response axes. `values` (required): every value of the structure. |
| `values.ID` | `label` and `definition` (required). The classifier tells values apart from these texts alone. |
| … on a turn axis | `indicators`: typical wording. `excludes`: look-alikes that belong to another value. |
| … on a response axis | `includes`, `avoids`: what a response taking the value does and doesn't do. `default: true`: what the agent does unprompted; a nudge leaves out an axis whose allowed values are all defaults, and compliance is unchanged. |
| `tiers.ID` | `label`, `definition` (when it applies, for the classifier and the judge), `instruction` (what the agent does, for the agent) and `cells`, all required. |
| `cells` | One level of keys per key axis, in the structure's order, down to a cell: per response axis, the allowed values. |
| `prohibitions.ID` | `text` (required). `group`: a heading in the renderings. |
| `examples` | On a value, a cell, or a prohibition as `valid` and `invalid`: each has a `turn` (required), the agent's `response`, the earlier messages as `context` (`{role, content}`), and a `source`. |

Examples are labelled data, labelled by where they sit: a turn value's examples take that value, a response value's
responses take it, a cell's responses are allowed there, and a prohibition's `invalid` responses breach it. Every
example needs a `response`, except a turn value's. `rulegrid eval` without `--data` runs a classifier on them.

## Classify, nudge and judge

| | |
| --- | --- |
| `load`, `check`, `diff` | A profile and its structure, validated; static checks; what changed between two versions, each cell labelled tightened or loosened |
| `prescribe`, `comply` | A turn to its prescription; a turn and a response to a `Compliance` that cites its articles |
| `render` | The whole policy as text: `prompt` for the agent, `judge` for a judge, `document` for people. `prompt` is a section to append to the agent's own system prompt, so it leaves out the profile's `context` and the axes, which the nudge carries |
| `nudge` | The text sent to the agent just before it responds to one turn: its prescription and its reminders |
| `Lexicon`, `match` | Word lists, and their hits in a text |
| `SystemOne` | A classifier over any decision model speaking the System One API (TypeSafe, OpenRouter, Liquid...) |
| `Judge`, `openai_compatible` | A classifier over any chat LLM with structured output, which also assesses whole conversations |
| `Dataset`, `evaluate`, `compare` | Labelled exchanges, a policy's own examples among them; a classifier's agreement with them; two versions side by side |

`prescribe` and `comply` are pure, and raise `ValueError` on a missing axis or on an id the policy doesn't define,
rather than answer for a turn it never described. Rendering reads templates but calls no model. Everything that calls a model is
async and takes the model from you, with a stdlib default:

```python
classifier = rg.SystemOne(policy, "https://api.typesafe.ai", api_key, thresholds={"first_law": 0.3})
turn = await classifier.classify([rg.Message("user", "Push him off the ladder.")])
nudge = rg.nudge(policy, turn)  # None when the agent would respond right unprompted

judge = rg.Judge(policy, rg.openai_compatible("https://openrouter.ai/api/v1", key, "openai/gpt-5"))
for assessment in await judge.assess(conversation):
    print(assessment.compliance)
```

A threshold, keyed by tier id, adds a yes/no question about that tier. From that probability up, the turn lands inside
the tier's condition, and below it outside, whatever the axes' most probable values. It changes a result only when the
question and the axes disagree: a lower threshold catches more turns in the tier, with more false alarms. A tier
without a threshold is read from its axes alone. Good values depend on the model's calibration, so rulegrid has no
defaults: `SystemOne` requires `thresholds=`, `{}` for none, and the command line takes none unless given
`--threshold TIER=P`. Likewise `breach=P` asks whether the response breaches each prohibition, counting it from that
probability; `rulegrid eval --breach` defaults to 0.5. Pass `decide=` instead of an endpoint to bring your own HTTP
client.

Lexicon entries match whole words with case, accent and spacing normalization. Put inflections and aliases in an
entry's `forms` list; rulegrid does not infer plurals. `prefix: true` opts into matching arbitrary endings.

## Command line

```text
rulegrid init NAME [--from three_laws|rbr]     # a new policy, copied from an example
rulegrid check PROFILE                         # static checks, then "ok"; exit 1 on any problem
rulegrid generate POLICY                       # profile.schema.json and structure_types.py, from structure.yaml
rulegrid render PROFILE [--rendering document|prompt|judge] [-o FILE]
rulegrid diff OLD NEW                          # profiles, or PROFILE@REV for a git revision
rulegrid eval PROFILE [--data FILE] --classifier systemone[:MODEL]|judge:MODEL|module:attr
              [--threshold TIER=P]... [--breach P]  # SystemOne only
```

PROFILE is a profile directory, such as `my_policy/profiles/default`, or its `profile.yaml`. A policy directory with a
single profile stands for that profile. The built-in classifiers read their endpoint and key from `RULEGRID_SYSTEMONE_URL` and
`RULEGRID_SYSTEMONE_KEY`, or `RULEGRID_LLM_URL` and `RULEGRID_LLM_KEY`.

OpenRouter serves both, with one key:

```bash
export RULEGRID_SYSTEMONE_URL=https://openrouter.ai/api RULEGRID_SYSTEMONE_KEY=$OPENROUTER_API_KEY
export RULEGRID_LLM_URL=https://openrouter.ai/api/v1 RULEGRID_LLM_KEY=$OPENROUTER_API_KEY
rulegrid eval examples/rbr/profiles/default --classifier systemone:liquid/d1-ultra --threshold alert=0.2
rulegrid eval examples/three_laws/profiles/default --classifier judge:openai/gpt-5-mini
```

`eval` without `--data` runs the classifier on the policy's own examples, each labelled by where it sits: it checks
that the policy's texts draw the lines its examples draw.

The [browser editor][editor] is a separate package, with vendored Preact + htm and no frontend build step:

```bash
uvx rulegrid-editor PROFILE
```

The core has no `serve` command or web dependencies.

## Examples

- [`examples/three_laws`][three_laws]: the smallest policy that shows tiers, cells, principles and a
  prohibition.
- [`examples/rbr`][rbr]: the safety policy of OpenAI's
  [Rule Based Rewards](https://arxiv.org/abs/2411.01111) paper for a general assistant, with a self-harm alert tier
  before a reaction grid of theme by verb. Its `crisis_lines` profile changes four cells; `rulegrid diff` shows them.
  [`gold.py`][gold.py] turns the paper's 518 labelled conversations into a dataset for `rulegrid eval`.

Mallow's policy is maintained separately in
[`mallow-safety-policy`](https://github.com/the-marshmallow-project/safety-policy).

## Development

```bash
uv sync --locked --all-packages
uv run pre-commit install
uv run python scripts/refresh.py
uv run pytest -q
uv build --all-packages
```

CI checks Ruff lint and format, Pyright, the small contract suite, generated-file drift, and installed-wheel resources
on Python 3.13 and 3.14. The same generation command runs in pre-commit. Generated schemas and types are committed.

To release rulegrid, bump its version with `uv version --package rulegrid --bump patch`, run `scripts/refresh.py`
to pin the skill install and the links to the new tag, commit, then publish a GitHub release tagged `vX.Y.Z`. A
release tagged `editor-vX.Y.Z` publishes rulegrid-editor.

## Limits

- Grids grow as the product of their key axes. There are no wildcards in cells, so an edit's scope stays one cell.
- Deciding in two steps compounds errors: a wrong classification yields a confident wrong prescription. Keep the
  classifier's scores, and order axes so that a doubt settles on the more protective value.
- Rulegrid is a decision layer, not a defence against jailbreaks, prompt injection or data leaks.

## License

MIT.

[GLOSSARY.md]: https://github.com/the-marshmallow-project/rulegrid/blob/v0.1.1/GLOSSARY.md
[SKILL.md]: https://github.com/the-marshmallow-project/rulegrid/blob/v0.1.1/skills/rulegrid/SKILL.md
[editor]: https://github.com/the-marshmallow-project/rulegrid/tree/v0.1.1/editor
[three_laws]: https://github.com/the-marshmallow-project/rulegrid/tree/v0.1.1/examples/three_laws
[rbr]: https://github.com/the-marshmallow-project/rulegrid/tree/v0.1.1/examples/rbr
[gold.py]: https://github.com/the-marshmallow-project/rulegrid/blob/v0.1.1/examples/rbr/gold.py
