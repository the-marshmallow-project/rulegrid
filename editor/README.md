# rulegrid-editor

Browse, edit and try a [rulegrid](https://github.com/the-marshmallow-project/rulegrid) policy in the browser, with
one command:

```bash
uvx rulegrid-editor PROFILE
```

PROFILE is a profile directory, such as `examples/rbr/profiles/default`. The page mirrors the policy's concepts: its
profile (context and principles), its structure, its turn and response axes and their values, its tiers and their
grids of cells, its prohibitions and its lexicons. Every id links to its definition and previews it on hover.

- **Document** reads the policy as people do.
- Each concept's page edits it with forms built from the profile's JSON Schema; a tier's grid opens a cell's form.
  The structure is read-only: edit `structure.yaml` and run `rulegrid generate`.
- **Changes** compares the policy with git `HEAD`, article by article and line by line.
- **YAML** edits the files as text.
- The **Try** panel classifies a turn and a response, and shows the cell they land in, the nudge and the compliance.

Edits stay unsaved until **Save** (or Ctrl+S), which writes the files in place and keeps their comments.
The server binds to loopback and has no authentication; do not expose it without an authenticated proxy.

The try panel classifies with `--classifier`, which reads its endpoint and key from the environment, as
`rulegrid eval` does. OpenRouter serves both built-in classifiers:

```bash
export RULEGRID_SYSTEMONE_URL=https://openrouter.ai/api RULEGRID_SYSTEMONE_KEY=$OPENROUTER_API_KEY
rulegrid-editor examples/rbr/profiles/default --classifier systemone:liquid/d1-ultra --threshold alert=0.2

export RULEGRID_LLM_URL=https://openrouter.ai/api/v1 RULEGRID_LLM_KEY=$OPENROUTER_API_KEY
rulegrid-editor examples/three_laws/profiles/default --classifier judge:openai/gpt-5-mini
```

Without one, the panel takes the values set by hand.

The page is [Preact](https://preactjs.com) and [htm](https://github.com/developit/htm), vendored in
`static/vendor` (7 KB gzipped): there is no build step and nothing to install from npm.
