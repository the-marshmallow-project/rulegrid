# Glossary

The words rulegrid uses, one per concept. Code, CLI, schemas, templates, the editor and the docs follow this file. When
one of them disagrees with it, fix whichever is wrong in the same change.

## The model in five sentences

A **policy** governs how an **agent** responds to a **user**. The user's **turn** is **classified** on the policy's
**turn axes**. The policy's **tiers** are tried in priority order, and the first whose **condition** holds
**prescribes** which **values** the response may take on each **response axis**. A **response** **complies** when its
classification fits that **prescription** and it **breaches** no **prohibition**. **Principles** justify the rules and
guide the agent where no rule applies.

## Nouns

### A policy and its files

| Term | Definition | In code and files |
| --- | --- | --- |
| **Policy** | What one loads, checks and renders: a structure and one of its profiles. | `Policy`, `load` |
| **Structure** | The policy's shape: the axes with their value ids, and the tiers in priority order with their conditions. Ids only. Anything a classification is made of, or a tier is keyed on, is structure. | `structure.yaml` |
| **Profile** | The policy's content: its context, every definition, the cells, the prohibitions, the principles, the examples and the lexicons. Two profiles of one structure differ in content, never in shape. | `profiles/NAME/profile.yaml` |
| **Policy directory** | The folder that holds `structure.yaml`, `profiles/`, the generated files and optional `templates/`. | `Policy.root`, `POLICY` on the command line |
| **Profile directory** | One profile's folder, `profiles/NAME/`. It names the policy to load. | `Policy.profile_dir`, `PROFILE` on the command line |
| **Context** | The profile's text on who the agent is and who it talks to, for readers who don't know: the classifier, the judge, people. The agent's prompt leaves it out. | `context` in `profile.yaml` |
| **Generated files** | `profile.schema.json` and `structure_types.py`, written from the structure alone and committed next to it. | `rulegrid generate` |
| **Digest** | A hash of the files a policy was loaded from, so that a compliance or a report names the policy that decided. | `Policy.digest` |

### A conversation

| Term | Definition | In code and files |
| --- | --- | --- |
| **User** | The person the agent talks to. | role `user` |
| **Agent** | The system the policy governs. | role `assistant` |
| **Message** | One chat message, from the user or the agent. | `Message` |
| **Conversation** | The messages exchanged by a user and the agent, in order. | `Conversation` |
| **Turn** | The user's latest message or messages, read in the context of the conversation before them. | `turn` |
| **Response** | The agent's message or messages that follow a turn. | `response` |
| **Exchange** | A turn and its response: what an example illustrates and a judge assesses. | `Assessment.exchange` |

### Classifications

| Term | Definition | In code and files |
| --- | --- | --- |
| **Axis** | One question about a turn (**turn axis**) or about a response (**response axis**), with a closed list of values. The two **sides** are named after what is classified, not after who speaks. | `turn_axes`, `response_axes`, `Axis.side` |
| **Value** | One answer on an axis, with a label and a definition written against the axis's other values. | `values` |
| **Ordered axis** | An axis whose value order carries meaning: a doubt between two values settles on the earlier. | `ordered: true` |
| **Multi-valued axis** | A response axis on which a response may take several values at once. | `multi: true` |
| **Default value** | A response value the agent takes unprompted. A nudge leaves out an axis whose allowed values are all defaults. | `default: true` |
| **Classification** | The values of one turn or one response: one per axis, a set on a multi-valued axis. A turn's carries its reminders, a response's its breaches. | `Classification` |
| **Evidence** | The quoted words a classification or a breach rests on. | `Classification.evidence`, `Breach.quote` |

### Rules

| Term | Definition | In code and files |
| --- | --- | --- |
| **Tier** | A situation the policy recognises, with a condition, an instruction and a grid. The first tier that applies decides, and the later ones are not tried. | `tiers` |
| **Condition** | When a tier applies: for each of its key axes, the values it **covers**. The profile adds the prose that defines the tier for a classifier. | a tier in `structure.yaml`, `Tier.condition` |
| **Key axis** | A turn axis a tier's condition and grid are keyed on. | |
| **Instruction** | What the agent does in a tier, in prose addressed to the agent. | `instruction` |
| **Grid** | A tier's table of cells, one at every position its condition covers. | `cells` |
| **Position** | One value per key axis of a tier. | `Cell.position` |
| **Cell** | The rule at one position: per response axis, the **allowed values**. An axis a cell leaves out allows any value, and `{}` leaves only the prohibitions. | `Cell` |
| **Fallthrough** | A turn outside a tier's condition goes to the next tier. Inside a condition every position has a cell, so a missing cell is an error. When no tier applies, nothing is prescribed. | |
| **Prescription** | The allowed values for one turn, with the tier and the cell they come from. None when no tier applies. | `Prescription`, `prescribe` |
| **Prohibition** | Something no response ever does, in any tier, nor in parts across responses. | `prohibitions` |
| **Breach** | A response doing what a prohibition forbids, with the words that do it. It is reported by a classifier or a caller, never deduced from values. | `Breach` |
| **Principle** | A statement the rules derive from, which guides the agent where no rule applies. | `principles` |
| **Rule** | A cell or a prohibition: what a response can fail. | |
| **Article** | A part of the policy cited by kind and id. A compliance cites the cells and prohibitions that decide it; a diff lists the articles that changed. | `Article`, `Change` |
| **Compliance** | Whether a response complies, with the articles that decide it. It is computed, never asked of a model. | `Compliance`, `comply` |

### What the agent reads

| Term | Definition | In code and files |
| --- | --- | --- |
| **Rendering** | The whole policy as text for one audience: `prompt` for the agent, `judge` for a judge, `document` for people. | `render`, `templates/*.j2` |
| **Nudge** | Text sent to the agent just before it responds to one turn: the turn's prescription and its reminders. None when the agent would respond right unprompted. | `nudge` |
| **Reminder** | A prohibition that a turn invites the response to breach. It comes from a classifier or from a lexicon hit. | `Classification.reminders`, `Hit.reminds` |
| **Lexicon** | A word list for one prohibition, each **entry** with its meaning: words the agent must not repeat or accept. | `lexicons/*.yaml`, `Lexicon` |
| **Hit** | A lexicon entry found in a text, as written there. | `Hit`, `match` |

### Classifiers

| Term | Definition | In code and files |
| --- | --- | --- |
| **Classifier** | Anything that classifies a turn or a response on a policy's axes. | `Classifier` |
| **System One** | An API through which a decision model answers typed questions with probabilities. `SystemOne` is the classifier built on it; "decision model" names that family of models, not the role. | `SystemOne` |
| **Threshold** | The probability from which a tier applies, a prohibition is reminded, or a breach counts. | `thresholds`, `remind`, `breach` |
| **Judge** | A classifier over a chat LLM that also assesses whole conversations, with evidence. | `Judge` |
| **Concern** | Words of a response that a judge weighs against a prohibition before it counts them as a breach or not. | `concerns` in the judge's answer |
| **Assessment** | A judge's reading of one exchange: both classifications, its rationale, and the computed prescription and compliance. | `Assessment` |

### Checks and evaluation

| Term | Definition | In code and files |
| --- | --- | --- |
| **Check** | A test of the policy itself that needs no model: unreachable cells, examples missing a response, generated files out of date. | `check` |
| **Problem** | Something wrong with a policy's files, and where. `load` raises every problem it finds; `check` returns them. | `Problem`, `PolicyError` |
| **Example** | An exchange written in the profile and labelled by where it sits: under a value, a cell, or a prohibition as `valid` or `invalid`. | `examples` |
| **Dataset** | Rows of exchanges, from a JSONL file or from the policy's own examples. | `Dataset` |
| **Row** | One exchange of a dataset. A **labelled** row says what its turn or response is, and a classifier is checked against it. An **audited** row has a response and no response labels: its compliance is computed. | `Row` |
| **Label** | What a row says about one axis or one prohibition, named `turn.AXIS`, `response.AXIS` or `breach.ID` in a report. Not the `label` field, which is the short name of a value, a tier or a principle. | |
| **Report** | A classifier's results on a dataset: agreement per label, and compliance per cell for audited rows. | `Report`, `evaluate` |
| **Change** | One article that differs between two versions of a policy. A changed cell is **tightened** (fewer allowed values), **loosened** or **mixed**. | `Change`, `diff` |

## Verbs

| Verb | From, to |
| --- | --- |
| **load** | a profile directory → a policy, or every problem found |
| **generate** | a structure → its generated files |
| **check** | a policy → problems |
| **classify** | a conversation → the classification of its last turn or response |
| **prescribe** | a policy, a turn's classification → a prescription, or none |
| **comply** | a policy, a turn's and a response's classifications → a compliance |
| **breach** | a response breaches a prohibition |
| **remind** | a turn, or a lexicon hit in it, reminds a prohibition |
| **match** | lexicons, a text → hits |
| **nudge** | a policy, a turn's classification, hits → text, or none |
| **render** | a policy, a rendering → text |
| **assess** | a conversation → one assessment per exchange |
| **evaluate** | a policy, a dataset, a classifier → a report |
| **diff** | two versions of a policy → changes |
| **compare** | two versions of a policy, a dataset → both reports and the rows that flip |

A condition **holds**, a tier **applies**, a tier **covers** values, a cell **allows** values, a response **takes** values.

## Identifiers

| Id | Form | Example |
| --- | --- | --- |
| Axis, tier | `snake_case`. Required for axes, whose ids become Python names. | `follow_up`, `first_law` |
| Value, prohibition, principle | `UPPER_CASE`. Avoid `YES` and `NO`, which some YAML readers take for booleans. | `HUMAN`, `HARM_HUMAN` |
| Cell | The tier id, then the position's values in key-axis order. | `first_law/HUMAN`, `reaction/CRIME/ASK_FOR` |
| Value, in a diff | The axis id, then the value id. | `danger/HUMAN` |
| Label | The side or `breach`, then the axis or prohibition id. | `turn.act`, `breach.HARM_HUMAN` |
| Problem | The file, then the path inside it. | `profile.yaml:tiers.first_law.cells.HUMAN` |

## Words to avoid

| Don't write | Write |
| --- | --- |
| reply | response |
| option, type | value |
| dimension | axis |
| level | tier. System One's score levels keep their name. |
| NEVER rule | prohibition |
| violate, violation | breach |
| note, warning | nudge |
| player, child, customer | user. A profile's own texts name its users as it likes. |
| game | conversation |
| decision model, safety classifier, guardrail, grader | classifier, or judge for the LLM one |
| verdict | compliance for a response, assessment for a judge's reading, result for a row |
| position id | cell id |
| toy | example policy |

Text written for a model is wording, not vocabulary: the default nudge opens with "Note:", and a classifier's questions
ask whether a response "breaks the rule". Change such text with an evaluation, not with a search and replace.
