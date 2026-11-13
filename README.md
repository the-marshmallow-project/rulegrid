# Rulegrid

Behavior policies as code. A policy says how an agent should respond to a user, in a form that a classifier can read,
that people can review, and that compliance can be computed from rather than asked:

1. The user's **turn** is classified on the policy's **turn axes**.
2. The policy's **tiers** are tried in order. The first whose **condition** holds **prescribes** the values the
   response may take on each **response axis**.
3. A **response** **complies** when its values are allowed and it breaches no **prohibition**. A non-compliant result
   cites the cell or prohibition that decides it.

**Principles** justify the rules and guide the agent where no rule applies.

## Start with your coding agent

Paste this into Amp, Claude Code, Codex, Cursor or any agent that can run commands, with your policy and, if you
have one, a labelled dataset:

```text
Convert my behavior policy to rulegrid by following
https://raw.githubusercontent.com/the-marshmallow-project/rulegrid/main/skills/rulegrid/SKILL.md

My policy: <paste the text, or give its path or URL>
My labelled dataset (optional): <its path, and what its labels mean>
```

The agent writes `structure.yaml` and a profile, lists the decisions your text leaves open, and, given a dataset,
writes an adapter and runs `rulegrid eval` on it. The [guide](skills/rulegrid/SKILL.md) is also an agent skill:
`npx skills add the-marshmallow-project/rulegrid` installs it.

## Quick start

Rulegrid needs Python 3.13 or later. Its Python shorthand is `rg`; the executable is `rulegrid`, leaving `rg` to ripgrep.

```bash
uv pip install git+https://github.com/the-marshmallow-project/rulegrid
rulegrid init my_policy                     # a copy of Asimov's Three Laws; --from rbr for a fuller policy
rulegrid check my_policy/profiles/default   # what is missing or inconsistent
```

Then use it from Python:

```python
import rulegrid as rg

policy = rg.load("my_policy/profiles/default")
turn = {"verb": "ORDER", "danger": "HUMAN"}  # "Push him off the ladder."
rg.prescribe(policy, turn)
# Prescription(tier='first_law', cell='first_law/HUMAN', allowed={'handling': ('PROTECT',)})
rg.comply(policy, turn, {"handling": "OBEY"})
# Compliance(ok=False, articles=(Article(kind='cell', id='first_law/HUMAN', detail='handling OBEY is not in [PROTECT]'),), ...)
```

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
can be `ordered` (a doubt between two values settles on the earlier) and, on the response side, `multi`.

Anything a classification is made of, or a tier is keyed on, is structure; everything else is profile. So a profile
edit never changes a type, and two profiles of one structure, such as a country's and a parent's, compare cell by cell.

To make a policy your own, edit `structure.yaml`, then run `rulegrid check` on the profile: it lists every value and
cell the profile must now define. Fill them in `profile.yaml`, and `rulegrid generate` updates the generated files.

## Classify, nudge and judge

| | |
| --- | --- |
| `load`, `check`, `diff` | A profile and its structure, validated; static checks; what changed between two versions, each cell labelled tightened or loosened |
| `prescribe`, `comply` | A turn to its prescription; a turn and a response to a `Compliance` that cites its articles |
| `render` | The whole policy as text: `prompt` for the agent, `judge` for a grader, `document` for people |
| `nudge` | The note sent to the agent before it responds to one turn: its prescription and its reminders |
| `Lexicon`, `match` | Word lists, and their hits in a text |
| `SystemOne` | A classifier over any decision model speaking the System One API (TypeSafe, OpenRouter, Liquid...) |
| `Judge`, `openai_compatible` | A classifier over any chat LLM with structured output, which also assesses whole conversations |
| `Dataset`, `evaluate`, `compare` | Labelled exchanges, a policy's own examples among them; a classifier's agreement with them; two versions side by side |

`prescribe` and `comply` are pure. Rendering reads templates but calls no model. Everything that calls a model is
async and takes the model from you, with a stdlib default:

```python
classifier = rg.SystemOne(policy, "https://api.typesafe.ai", api_key, thresholds={"first_law": 0.3})
turn = await classifier.classify([rg.Message("user", "Push him off the ladder.")])
note = rg.nudge(policy, turn)  # None when the agent would respond right unprompted

judge = rg.Judge(policy, rg.openai_compatible("https://openrouter.ai/api/v1", key, "openai/gpt-5"))
for assessment in await judge.assess(conversation):
    print(assessment.compliance)
```

A threshold, keyed by tier id, asks the decision model whether that tier applies. Thresholds have no defaults: they
belong to the model's calibration. Pass `decide=` instead of an endpoint to bring your own HTTP client.

Lexicon entries match whole words with case, accent and spacing normalization. Put inflections and aliases in an
entry's `forms` list; Rulegrid does not infer plurals. `prefix: true` opts into matching arbitrary endings.

## Command line

```text
rulegrid init NAME [--from three_laws|rbr]     # a new policy, copied from a toy one
rulegrid check POLICY                          # static checks; exit 1 on any problem
rulegrid generate POLICY                       # profile.schema.json and structure_types.py, from structure.yaml
rulegrid render POLICY [--rendering document|prompt|judge] [-o FILE]
rulegrid diff OLD NEW                          # profile directories, or DIR@REV for a git revision
rulegrid eval POLICY [--data FILE] --classifier systemone[:MODEL]|judge:MODEL|module:attr
```

POLICY is a profile directory. The built-in classifiers read their endpoint and key from `RULEGRID_SYSTEMONE_URL` and
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

The [browser editor](editor/README.md) is a separate package, with vendored Preact + htm and no frontend build step:

```bash
uvx --from "git+https://github.com/the-marshmallow-project/rulegrid#subdirectory=editor" rulegrid-editor POLICY
```

The core has no `serve` command or web dependencies.

## Examples

- [`examples/three_laws`](examples/three_laws): the smallest policy that shows tiers, cells, principles and a
  prohibition.
- [`examples/rbr`](examples/rbr): the safety policy of OpenAI's
  [Rule Based Rewards](https://arxiv.org/abs/2411.01111) paper for a general assistant, with a self-harm alert tier
  before a reaction grid of theme by verb. Its `crisis_lines` profile changes four cells; `rulegrid diff` shows them.
  [`gold.py`](examples/rbr/gold.py) turns the paper's 518 labelled conversations into a dataset for `rulegrid eval`.

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

## Limits

- Grids grow as the product of their key axes. There are no wildcards in cells, so an edit's scope stays one cell.
- Deciding in two steps compounds errors: a wrong classification yields a confident wrong prescription. Keep the
  classifier's scores, and order axes so that a doubt settles on the more protective value.
- Rulegrid is a decision layer, not a defence against jailbreaks, prompt injection or data leaks.

## License

MIT. Derived from [`felix-martel/ruleswitch`](https://github.com/felix-martel/ruleswitch) at
[`028d627`](https://github.com/felix-martel/ruleswitch/commit/028d627f6dc8c4cc127f0cdcc7729b1c444ae687),
itself developed from Mallow's safety-policy library built by Grégoire Lothe.
