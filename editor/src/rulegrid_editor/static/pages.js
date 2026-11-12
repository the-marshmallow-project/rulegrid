// One page per concept of a policy, each editing it with forms built from the profile's schema.
import { ObjectField, schemaAt } from "./forms.js";
import { Exchange, Grid, Id, Ref, S, Table, TierTitle, ValueRef, axisOf, html, sideOf, tierNumber, title } from "./ui.js";

// The value fields one side doesn't use: a turn value is recognised, a response value is written.
const UNUSED = { turn_axes: ["includes", "avoids"], response_axes: ["indicators", "excludes"] };
const SIDES = [["turn_axes", "The turn", "Turn axis"], ["response_axes", "The response", "Response axis"]];

const Remove = ({ onClick }) => html`<button class="quiet remove" onClick=${onClick}>Remove</button>`;
const ask = (what) => prompt(`Id of the new ${what}, such as ${what === "principle" ? "kindness" : "NO_SPOILERS"}`)?.trim();

export function Document({ policy }) {
  const values = (axis, columns) => html`<${Table} head=${["Value", ...columns.map(([h]) => h)]}>
    ${axis.values.map((v) => html`<tr><td><b>${v.label}</b> <${ValueRef} axis=${axis.id} id=${v.id} />${v.default && " · default"}</td>${columns.map(([, f]) => html`<td>${f(v)}</td>`)}</tr>`)}<//>`;
  const columns = {
    turn_axes: [["Definition", (v) => v.definition], ["Typical wording", (v) => v.indicators.join(", ")], ["Not this", (v) => v.excludes]],
    response_axes: [["Definition", (v) => v.definition], ["Includes", (v) => v.includes], ["Avoids", (v) => v.avoids]],
  };
  const examples = (tier) => {
    const rows = Object.entries(tier.cells).flatMap(([id, c]) => c.examples.map((e) => html`<tr><td><${Ref} kind="cell" id=${id}>${id}<//></td><td><${Exchange} e=${e} /></td></tr>`));
    return rows.length > 0 && html`<${Table} head=${["Cell", "Compliant exchange"]}>${rows}<//>`;
  };
  const prohibitions = policy.prohibitions.flatMap((p) => [
    html`<tr><td colspan="3"><b><${Ref} kind="prohibition" id=${p.id} /></b>: ${p.text}</td></tr>`,
    ...p.valid.map((e) => html`<tr><td></td><td><${Exchange} e=${e} /></td><td>yes</td></tr>`),
    ...p.invalid.map((e) => html`<tr><td></td><td><${Exchange} e=${e} /></td><td><b>no</b></td></tr>`),
  ]);
  return html`<article class="page">
    <h1>${policy.name}</h1>
    ${policy.context && html`<p>${policy.context}</p>`}
    ${policy.principles.length > 0 && html`<h2>Principles</h2><ol>${policy.principles.map((p) => html`<li><b><${Ref} kind="principle" id=${p.id}>${p.label}<//>.</b> ${p.text}</li>`)}</ol>`}
    <h2>Priority</h2>
    <p>At each turn, the response is set in this order. The prohibitions hold for every response.</p>
    <ol>${policy.tiers.map((t) => html`<li><b><${Ref} kind="tier" id=${t.id}>${t.label}<//>.</b> ${t.definition} ${t.instruction}</li>`)}</ol>
    <p>When no tier applies, only the prohibitions constrain the response.</p>
    ${SIDES.map(([side, heading]) => html`<h2>${heading}</h2>${policy[side].map((a) => html`
      <h3><${Ref} kind="axis" id=${a.id}>${title(a.id)}<//></h3><p>${a.definition}${a.guidance && " " + a.guidance}</p>${values(a, columns[side])}`)}`)}
    ${policy.tiers.map((t) => html`<h2><${TierTitle} tier=${t} /></h2><p>${t.definition} ${t.instruction}</p><${Grid} tier=${t} />${examples(t)}`)}
    ${prohibitions.length > 0 && html`<h2>Prohibitions</h2><p>No response ever does these, whatever the tier.</p><${Table} head=${["Prohibition", "Exchange", "Complies"]}>${prohibitions}<//>`}
  </article>`;
}

export function Profile({ policy, data, schemas, edit }) {
  const root = schemas.profile;
  return html`<div class="page">
    <h1><span class="kind">Profile</span>${policy.name}</h1>
    <div class="card"><${ObjectField} schema=${root} root=${root} value=${data} at=${[]} edit=${edit} omit=${["structure", "principles", "turn_axes", "response_axes", "tiers", "prohibitions"]} /></div>
    <h2>Principles</h2>
    <p class="muted">They justify the rules, and guide the agent where no rule applies.</p>
    ${policy.principles.map((p) => html`<div class="card" id=${`def-principle-${p.id}`}>
      <${Remove} onClick=${() => edit(["principles", p.id], null)} /><h3>${p.label} <${Id}>${p.id}<//></h3>
      <${ObjectField} schema=${schemaAt(root, ["principles", p.id])} root=${root} value=${data.principles[p.id]} at=${["principles", p.id]} edit=${edit} />
    </div>`)}
    <button class="add" onClick=${() => { const id = ask("principle"); if (id) edit(["principles", id], { label: title(id), text: "" }); }}>+ New principle</button>
  </div>`;
}

export function Structure({ policy }) {
  const flags = (a) => [a.ordered && "ordered, most protective first", a.multi && "several values at once"].filter(Boolean).join("; ");
  const axes = (side) => html`<${Table} head=${["Axis", "Values", ""]}>${policy[side].map((a) => html`<tr>
    <td><${Ref} kind="axis" id=${a.id} /></td><td>${a.values.map((v, i) => html`${i > 0 && ", "}<${ValueRef} axis=${a.id} id=${v.id} />`)}</td><td class="muted">${flags(a)}</td></tr>`)}<//>`;
  return html`<div class="page">
    <h1><span class="kind">Structure</span>${policy.name.split(" · ")[0]}</h1>
    <p class="muted">What every profile of this policy shares: its axes, their values, and the tiers' conditions. Edit <code>structure.yaml</code>, then run <code>rulegrid generate</code>.</p>
    <h2>Turn axes</h2>${axes("turn_axes")}
    <h2>Response axes</h2>${axes("response_axes")}
    <h2>Tiers</h2>
    <p>Tried in order: the first whose condition holds prescribes the response.</p>
    <ol>${policy.tiers.map((t) => html`<li><${Ref} kind="tier" id=${t.id}>${t.label}<//> applies when${" "}${Object.entries(t.condition).map(([axis, ids], i) => html`${i > 0 && " and "}<${Ref} kind="axis" id=${axis} /> is ${ids.map((v, j) => html`${j > 0 && ", "}<${ValueRef} axis=${axis} id=${v} />`)}`)}</li>`)}</ol>
  </div>`;
}

export function Axis({ id, data, schemas, edit }) {
  const axis = axisOf(id), side = sideOf(id), root = schemas.profile;
  if (!axis) return html`<p class="muted">No axis ${id}.</p>`;
  const at = [side, id];
  const valueSchema = schemaAt(root, [...at, "values", axis.values[0].id]);
  return html`<div class="page">
    <h1><span class="kind">${SIDES.find(([s]) => s === side)[2]}</span>${title(id)} <${Id}>${id}<//></h1>
    <div class="card" id=${`def-axis-${id}`}><${ObjectField} schema=${schemaAt(root, at)} root=${root} value=${data[side][id]} at=${at} edit=${edit} omit=${["values"]} /></div>
    <h2>Values</h2>
    ${axis.values.map((v) => html`<div class="card" id=${`def-value-${id}/${v.id}`}>
      <h3>${v.label} <${Id}>${v.id}<//></h3>
      <${ObjectField} schema=${valueSchema} root=${root} value=${data[side][id].values[v.id]} at=${[...at, "values", v.id]} edit=${edit} omit=${UNUSED[side]} />
    </div>`)}
  </div>`;
}

export function Tier({ id, cell, policy, data, schemas, edit, attempt }) {
  const tier = policy.tiers.find((t) => t.id === id), root = schemas.profile;
  if (!tier) return html`<p class="muted">No tier ${id}.</p>`;
  const at = ["tiers", id], pick = (c) => (location.hash = "#/tiers/" + c.split("/").map(encodeURIComponent).join("/"));
  return html`<div class="page">
    <h1><span class="kind">Tier ${tierNumber(id)} of ${policy.tiers.length}</span>${tier.label} <${Id}>${id}<//></h1>
    <div class="card"><${ObjectField} schema=${schemaAt(root, at)} root=${root} value=${data.tiers[id]} at=${at} edit=${edit} omit=${["cells"]} /></div>
    <h2>Cells</h2>
    <p class="muted">One per turn the tier covers: the values the response may take. Pick one to edit it.</p>
    <${Grid} tier=${tier} pick=${pick} selected=${cell} attempt=${attempt} />
    ${cell && tier.cells[cell] && html`<${Cell} id=${cell} root=${root} data=${data} edit=${edit} />`}
  </div>`;
}

function Cell({ id, root, data, edit }) {
  const at = ["tiers", ...id.split("/").flatMap((k, i) => (i ? [k] : [k, "cells"]))];
  const cell = at.reduce((n, k) => n?.[k], data) || {};
  const toggle = (axis, v, on) => {
    const now = new Set(cell[axis.id] || []);
    on ? now.add(v) : now.delete(v);
    edit([...at, axis.id], now.size ? axis.ids.filter((x) => now.has(x)) : null);
  };
  return html`<div class="card" id=${`def-cell-${id}`}>
    <h3>Cell <${Id}>${id}<//></h3>
    <p class="muted">An axis with nothing checked allows any value.</p>
    ${S.policy.response_axes.map((axis) => html`<div class="field"><label><${Ref} kind="axis" id=${axis.id} /></label><div class="choices">
      ${axis.values.map((v) => html`<label title=${`${v.label}: ${v.definition}`}><input type="checkbox" checked=${(cell[axis.id] || []).includes(v.id)} onChange=${(e) => toggle({ ...axis, ids: axis.values.map((x) => x.id) }, v.id, e.target.checked)} /> ${v.id}</label>`)}
    </div></div>`)}
    <${ObjectField} schema=${schemaAt(root, at)} root=${root} value=${cell} at=${at} edit=${edit} omit=${S.policy.response_axes.map((a) => a.id)} />
  </div>`;
}

export function Prohibitions({ policy, data, schemas, edit }) {
  const root = schemas.profile;
  const groups = [...new Set(policy.prohibitions.map((p) => p.group))];
  return html`<div class="page">
    <h1><span class="kind">Prohibitions</span>What no response ever does</h1>
    <p class="muted">They hold whatever the tier. A response that breaches one does not comply.</p>
    ${groups.map((g) => html`${(g || groups.length > 1) && html`<h2>${g ? title(g) : "No group"}</h2>`}
      ${policy.prohibitions.filter((p) => p.group === g).map((p) => html`<div class="card" id=${`def-prohibition-${p.id}`}>
        <${Remove} onClick=${() => edit(["prohibitions", p.id], null)} /><h3>${p.id}</h3>
        <${ObjectField} schema=${schemaAt(root, ["prohibitions", p.id])} root=${root} value=${data.prohibitions[p.id]} at=${["prohibitions", p.id]} edit=${edit} />
      </div>`)}`)}
    <button class="add" onClick=${() => { const id = ask("prohibition"); if (id) edit(["prohibitions", id], { text: "" }); }}>+ New prohibition</button>
  </div>`;
}

export function Lexicon({ name, data, schemas, edit }) {
  return html`<div class="page">
    <h1><span class="kind">Lexicon</span>${name}</h1>
    <p class="muted">Words matched in a turn, before any classifier: each reminds the agent of a prohibition.</p>
    <div class="card"><${ObjectField} schema=${schemas.lexicon} root=${schemas.profile} value=${data} at=${[]} edit=${edit} /></div>
  </div>`;
}

export function Changes({ changes }) {
  if (changes.error) return html`<div class="page"><h1>Changes</h1><p class="muted">${changes.error}.</p></div>`;
  const files = Object.entries(changes.files);
  const kind = (line) => ({ "+": "ins", "-": "del", "@": "hunk" })[line[0]] || "";
  return html`<div class="page">
    <h1><span class="kind">Changes</span>Since git HEAD</h1>
    ${!files.length ? html`<p class="muted">No changes.</p>` : html`
      <h2>Articles</h2><pre class="articles">${changes.articles}</pre>
      ${files.map(([name, lines]) => html`<h2><code>${name}</code></h2><pre class="diff">${lines.map((l) => html`<div class=${kind(l)}>${l}</div>`)}</pre>`)}`}
  </div>`;
}

export function Yaml({ texts, saved, file, setText }) {
  const names = Object.keys(texts);
  const current = names.includes(file) ? file : names.find((n) => n.endsWith("profile.yaml"));
  const onKeyDown = (e) => {
    if (e.key !== "Tab") return;
    e.preventDefault();
    e.target.setRangeText("  ", e.target.selectionStart, e.target.selectionEnd, "end");
    setText(current, e.target.value);
  };
  return html`<div class="yaml">
    <select value=${current} onChange=${(e) => (location.hash = "#/yaml/" + encodeURIComponent(e.target.value))}>
      ${names.map((n) => html`<option value=${n}>${n}${texts[n] !== saved[n] ? " •" : ""}</option>`)}
    </select>
    <textarea spellcheck="false" value=${texts[current]} onInput=${(e) => setText(current, e.target.value)} onKeyDown=${onKeyDown} />
  </div>`;
}
