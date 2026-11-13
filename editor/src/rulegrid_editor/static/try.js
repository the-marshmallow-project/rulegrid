// The try panel: where a turn and a response land, what the policy prescribes and nudges, and whether it complies.
import { useRef, useState } from "preact/hooks";
import { Id, Ref, S, ValueRef, html, tierNumber, tierOf } from "./ui.js";

const NoClassifier = () => html`<div class="note">No classifier: set the values by hand, or restart the editor with one, such as:
<pre>export RULEGRID_SYSTEMONE_URL=https://openrouter.ai/api
export RULEGRID_SYSTEMONE_KEY=$OPENROUTER_API_KEY
rulegrid-editor PROFILE --classifier systemone:liquid/d1-ultra</pre></div>`;

// A classifier's confidence: the top values' probabilities, or the evidence it quotes.
function Scores({ c, axis }) {
  const answer = c?.scores?.[axis.id];
  if (!answer?.probabilities) return c?.evidence?.[axis.id] ? html`<div class="scores">“${c.evidence[axis.id]}”</div>` : null;
  // A score's levels run from the low end up, which on an ordered axis is its last value (see SystemOne.read).
  const ids = axis.values.map((v) => v.id), last = ids.length - 1;
  const top = Object.entries(answer.probabilities).map(([k, p]) => [answer.type === "score" ? ids[last - k] : k, p]).sort((a, b) => b[1] - a[1]).slice(0, 3);
  return html`<div class="scores">${top.map(([k, p]) => `${k} ${p.toFixed(2)}`).join(" · ")}</div>`;
}

const Questions = ({ c }) => {
  const top = Object.entries(c?.scores || {}).filter(([k]) => k.includes(":")).sort((a, b) => (b[1].noul ?? 0) - (a[1].noul ?? 0)).slice(0, 4);
  return top.length > 0 && html`<div class="scores">${top.map(([k, a]) => `${k} ${(a.noul ?? 0).toFixed(2)}`).join(" · ")}</div>`;
};

// One row per axis: the value read, which the page can set by hand.
function Axes({ axes, c, set, failed = new Set() }) {
  return html`<table>${axes.map((axis) => {
    const value = c?.values?.[axis.id];
    let control;
    if (axis.multi) {
      const taken = Array.isArray(value) ? value : value ? [value] : [];
      const toggle = (v, on) => set(axis.id, axis.values.map((x) => x.id).filter((x) => (x === v ? on : taken.includes(x))));
      control = axis.values.map((v) => html`<label title=${v.label} style="white-space: nowrap; margin-right: 6px"><input type="checkbox" checked=${taken.includes(v.id)} onChange=${(e) => toggle(v.id, e.target.checked)} /> ${v.id}</label>`);
    } else {
      control = html`<select value=${value ?? ""} onChange=${(e) => set(axis.id, e.target.value || undefined)}>
        <option value="">—</option>${axis.values.map((v) => html`<option value=${v.id}>${v.id} · ${v.label}</option>`)}</select>`;
    }
    return html`<tr><th class=${failed.has(axis.id) ? "ko" : ""}><${Ref} kind="axis" id=${axis.id} /></th><td>${control}<${Scores} c=${c} axis=${axis} /></td></tr>`;
  })}</table>`;
}

export function Try({ attempt, setAttempt, classifier, run }) {
  const turn = useRef(), response = useRef();
  const [busy, setBusy] = useState(false), [error, setError] = useState(null), [blank, setBlank] = useState(true);
  const policy = S.policy;

  const go = async (values) => {
    setBusy(!values);
    setError(null);
    try {
      setAttempt(await run({ turn: turn.current.value, response: response.current.value, ...values }));
    } catch (e) {
      setError(e.message);
    }
    setBusy(false);
  };
  // A value set by hand: the try runs again on the values shown, which the classifier no longer reads.
  const values = (side) => ({ ...(attempt?.[side]?.values || {}) });
  const set = (side) => (axis, value) => {
    const next = { turn: values("turn"), response: attempt?.response ? values("response") : null };
    next[side] = { ...(next[side] || {}), [axis]: value };
    if (value === undefined) delete next[side][axis];
    go({ turn_values: next.turn, response_values: next.response });
  };
  const clear = () => {
    turn.current.value = response.current.value = "";
    setBlank(true);
    setAttempt(null);
    setError(null);
    turn.current.focus();
  };
  const onKeyDown = (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && classifier && !blank) go(); };
  const timer = useRef();
  const onInput = () => { setBlank(!turn.current.value.trim()); if (!classifier) { clearTimeout(timer.current); timer.current = setTimeout(() => go({ turn_values: values("turn"), response_values: attempt?.response ? values("response") : null }), 400); } };

  const a = attempt, p = a?.prescription, unset = a?.missing?.length > 0;
  const articles = a?.compliance?.articles || [];
  const failed = new Set(articles.filter((x) => x.kind === "cell").map((x) => x.detail.split(" ")[0]));
  return html`<aside>
    <textarea ref=${turn} rows="3" placeholder="A user's turn" aria-label="User's turn" onKeyDown=${onKeyDown} onInput=${onInput} />
    <textarea ref=${response} rows="2" placeholder="The agent's response (optional)" aria-label="Agent's response" onKeyDown=${onKeyDown} />
    ${classifier && html`<button class="primary" onClick=${() => go()} disabled=${busy || blank}>Classify</button> `}
    <button onClick=${clear}>Clear</button>
    ${busy && html` <span class="muted">classifying…</span>`}
    ${error && html`<p class="error">${error}</p>`}
    ${!classifier && html`<${NoClassifier} />`}
    ${a && html`<div class="verdict">
      ${a.compliance && html`<span class=${"pill " + (a.compliance.ok ? "ok" : "ko")}>${a.compliance.ok ? "Complies" : "Does not comply"}</span> `}
      ${unset ? html`<span class="muted">Set ${a.missing.join(", ")} to see where the turn lands.</span>`
        : p ? html`Tier ${tierNumber(p.tier)}: ${tierOf(p.tier)?.label}, cell <${Ref} kind="cell" id=${p.cell}>${p.cell}<//>` : "No tier applies"}
      ${articles.length > 0 && html`<ul>${articles.map((x) => html`<li>${x.kind === "cell" ? x.detail : html`breaches <${Ref} kind="prohibition" id=${x.id} />`}</li>`)}</ul>`}
    </div>`}
    ${(a || !classifier) && html`
      <h3>Turn</h3>
      <${Axes} axes=${policy.turn_axes} c=${a?.turn} set=${set("turn")} />
      <${Questions} c=${a?.turn} />
      ${a?.turn.reminders.map((r) => html`<div>Reminds <${Ref} kind="prohibition" id=${r} /></div>`)}
      ${a?.hits.map((h) => html`<div>“${h.text}” reminds <${Ref} kind="prohibition" id=${h.reminds} /> <span class="muted">${h.meaning}</span></div>`)}`}
    ${a && !unset && html`
      <h3>Prescription</h3>
      ${!p ? html`<p class="muted">Only the prohibitions constrain the response.</p>`
        : Object.keys(p.allowed).length ? Object.entries(p.allowed).map(([axis, ids]) => html`<div><${Ref} kind="axis" id=${axis} />: ${ids.map((id, i) => html`${i > 0 && " or "}<${ValueRef} axis=${axis} id=${id} />`)}</div>`)
        : html`<p class="muted">Any value: only the prohibitions apply.</p>`}
      <h3>Nudge</h3>
      ${a.nudge ? html`<pre class="nudge">${a.nudge}</pre>` : html`<p class="muted">None: the agent would respond right unprompted.</p>`}`}
    ${a && html`
      <h3>Response</h3>
      <${Axes} axes=${policy.response_axes} c=${a.response} set=${set("response")} failed=${failed} />
      <${Questions} c=${a.response} />
      ${(a.response?.breaches || []).filter((b) => b.quote).map((b) => html`<div class="scores"><${Id}>${b.prohibition}<//>: “${b.quote}” ${b.why}</div>`)}`}
  </aside>`;
}
