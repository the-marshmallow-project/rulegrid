// Forms built from the JSON Schema of what they edit, so they fit any structure. A field edits one node: it calls
// `edit(path, value)` with its path in the file, and `null` removes an optional node left empty or at its default.
import { useLayoutEffect, useRef } from "preact/hooks";
import { html, title } from "./ui.js";

// The labels the people who write a policy use, where they differ from the field's name.
const LABELS = {
  "ValueFile.indicators": "Typical wording", "ValueFile.excludes": "Not this",
  "ProhibitionFile.valid": "Examples that comply", "ProhibitionFile.invalid": "Examples that breach it",
  "ExampleFile.context": "Earlier messages", "ExampleFile.turn": "User", "ExampleFile.response": "Agent",
};
const label = (s, k, p) => LABELS[`${s.title}.${k}`] ?? p.title ?? title(k);

export const resolve = (s, root) => { while (s?.$ref) s = root.$defs[s.$ref.split("/").pop()]; return s; };
const unwrap = (s, root) => { s = resolve(s, root); return s.anyOf ? resolve(s.anyOf.find((x) => x.type !== "null"), root) : s; };
export function schemaAt(root, path) {
  let s = root;
  for (const key of path) {
    s = resolve(s, root);
    s = s.type === "array" ? s.items : s.properties?.[key] ?? s.additionalProperties;
  }
  return resolve(s, root);
}
const empty = (v, s) => v == null || v === "" || (Array.isArray(v) && !v.length) || v === s.default;
// A new item: its required fields, empty.
const blank = (s, root) => Object.fromEntries((s.required || []).map((k) => {
  const p = unwrap(s.properties[k], root);
  return [k, p.enum ? p.enum[0] : p.type === "array" ? [] : p.type === "boolean" ? false : ""];
}));

// A text box the page doesn't overwrite while it is typed in: it takes the file's value only when that changes.
function Text({ value, put, multiline, ...props }) {
  const el = useRef();
  useLayoutEffect(() => { if (el.current.value !== value) el.current.value = value; }, [value]);
  const rows = Math.min(10, Math.max(Math.ceil(value.length / 80), value.split("\n").length));
  const onChange = (e) => put(e.target.value);
  return multiline ? html`<textarea ref=${el} rows=${rows} onChange=${onChange} ...${props} />` : html`<input type="text" ref=${el} onChange=${onChange} ...${props} />`;
}

export function Field({ schema, root, value, at, edit, optional, compact }) {
  const s = unwrap(schema, root);
  const put = (v) => edit(at, optional && empty(v, s) ? null : v);
  if (s.enum) {
    return html`<select value=${value ?? ""} onChange=${(e) => put(e.target.value)}>
      ${value == null && html`<option value="">—</option>`}${s.enum.map((v) => html`<option value=${v}>${v}</option>`)}</select>`;
  }
  if (s.type === "boolean") return html`<input type="checkbox" checked=${!!value} onChange=${(e) => put(e.target.checked)} />`;
  if (s.type === "string") return html`<${Text} value=${value ?? ""} put=${(v) => put(v.trim())} multiline=${!compact} />`;
  const items = s.type === "array" && unwrap(s.items, root);
  if (items?.enum) {
    const on = new Set(value || []);
    const toggle = (v, checked) => put(items.enum.filter((x) => (x === v ? checked : on.has(x))));
    return html`<div class="choices">${items.enum.map((v) => html`<label><input type="checkbox" checked=${on.has(v)} onChange=${(e) => toggle(v, e.target.checked)} /> ${v}</label>`)}</div>`;
  }
  if (items?.type === "string") {
    const sep = compact ? ", " : "\n";
    const split = (v) => v.split(compact ? "," : "\n").map((x) => x.trim()).filter(Boolean);
    return html`<${Text} value=${(value || []).join(sep)} put=${(v) => put(split(v))} multiline=${!compact} placeholder=${compact ? "" : "One per line"} />`;
  }
  if (items) return html`<${ArrayField} items=${items} root=${root} list=${value || []} at=${at} edit=${edit} />`;
  return html`<${ObjectField} schema=${s} root=${root} value=${value || {}} at=${at} edit=${edit} />`;
}

// An object's fields, each under its label. `omit` leaves out the fields another part of the page edits.
export function ObjectField({ schema, root, value, at, edit, omit = [] }) {
  const s = resolve(schema, root);
  return Object.entries(s.properties).filter(([k]) => !omit.includes(k)).map(([k, p]) => {
    const optional = !s.required?.includes(k), kind = unwrap(p, root).type;
    return html`<div class="field">
      <label>${label(s, k, p)}${optional && kind !== "boolean" && html` <span class="hint">optional</span>`}</label>
      <${Field} schema=${p} root=${root} value=${value[k]} at=${[...at, k]} edit=${edit} optional=${optional} />
    </div>`;
  });
}

// A list of flat objects, such as a lexicon's entries, is a table; any other list is a stack of cards.
function ArrayField({ items, root, list, at, edit }) {
  const remove = (i) => edit(at, list.filter((_, j) => j !== i));
  const add = html`<button class="add" onClick=${() => edit(at, [...list, blank(items, root)])}>+ Add</button>`;
  const x = (i) => html`<button class="quiet remove" title="Remove" onClick=${() => remove(i)}>×</button>`;
  const props = Object.entries(items.properties || {});
  const flat = items.type === "object" && props.every(([, p]) => {
    p = unwrap(p, root);
    return p.enum || ["string", "boolean"].includes(p.type) || (p.type === "array" && p.items?.type === "string");
  });
  if (items.title === "ExampleFile") {
    return html`${list.map((item, i) => html`<${Example} e=${item} root=${root} at=${[...at, i]} edit=${edit} remove=${x(i)} />`)}${add}`;
  }
  if (!flat) {
    return html`${list.map((item, i) => html`<div class="card">${x(i)}
      <${ObjectField} schema=${items} root=${root} value=${item} at=${[...at, i]} edit=${edit} /></div>`)}${add}`;
  }
  return html`${list.length > 0 && html`<table class="rows">
    <tr>${props.map(([k, p]) => html`<th>${label(items, k, p)}</th>`)}<th></th></tr>
    ${list.map((item, i) => html`<tr>${props.map(([k, p]) => html`<td>
      <${Field} schema=${p} root=${root} value=${item[k]} at=${[...at, i, k]} edit=${edit} optional=${!items.required?.includes(k)} compact />
    </td>`)}<td class="x">${x(i)}</td></tr>`)}
  </table>`}${add}`;
}

// An example exchange, as it reads: the earlier messages, the user's turn and the agent's response, one line each.
function Example({ e, at, edit, remove }) {
  const line = (key, who, value, optional) => html`<div class="line"><b>${who}</b>
    <${Text} value=${value ?? ""} put=${(v) => edit([...at, ...key], optional && !v.trim() ? null : v.trim())} multiline placeholder=${optional ? "optional" : ""} /></div>`;
  const context = e.context || [];
  const message = (role) => edit([...at, "context"], [...context, { role, content: "" }]);
  return html`<div class="example">${remove}
    ${context.map((m, i) => html`<div class="line"><b>${m.role === "user" ? "User" : "Agent"}</b>
      <${Text} value=${m.content} put=${(v) => edit([...at, "context", i, "content"], v.trim())} multiline />
      <button class="quiet" title="Remove" onClick=${() => edit([...at, "context"], context.length > 1 ? context.filter((_, j) => j !== i) : null)}>×</button></div>`)}
    ${line(["turn"], "User", e.turn)}
    ${line(["response"], "Agent", e.response, true)}
    <div class="more">
      <button class="quiet" onClick=${() => message("user")}>+ earlier user message</button>
      <button class="quiet" onClick=${() => message("assistant")}>+ earlier agent message</button>
      <span class="muted">Source</span> <${Text} value=${e.source ?? ""} put=${(v) => edit([...at, "source"], v.trim() || null)} />
    </div>
  </div>`;
}
