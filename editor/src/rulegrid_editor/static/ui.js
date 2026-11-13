// What every page shares: the policy last loaded, links between ids and their previews, and a tier's grid.
import { h } from "preact";
import htm from "htm";

export const html = htm.bind(h);

// The last policy that loaded: the previews and lookups read it.
export const S = { policy: null };

export const axisOf = (id) => [...S.policy.turn_axes, ...S.policy.response_axes].find((a) => a.id === id);
export const sideOf = (id) => (S.policy.turn_axes.some((a) => a.id === id) ? "turn_axes" : "response_axes");
export const tierOf = (id) => S.policy.tiers.find((t) => t.id === id);
export const tierNumber = (id) => S.policy.tiers.findIndex((t) => t.id === id) + 1;
export const title = (id) => id.replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase());

// Each kind of id has a page: a value or an axis its axis's, a cell its tier's, and so on.
const PAGES = { value: "axes", axis: "axes", tier: "tiers", cell: "tiers", prohibition: "prohibitions", principle: "profile", lexicon: "lexicons" };
export const href = (kind, key) => "#/" + [PAGES[kind], ...key.split("/")].map(encodeURIComponent).join("/");
// The element a route points at, which the page scrolls to.
export function anchor(route) {
  const [page, ...key] = route;
  const kind = { axes: key.length > 1 ? "value" : "axis", tiers: key.length > 1 ? "cell" : null, prohibitions: "prohibition", profile: "principle" }[page];
  return kind && key.length ? `def-${kind}-${key.join("/")}` : null;
}

export const Ref = ({ kind, id, children }) =>
  html`<a class="ref" href=${href(kind, id)} data-ref=${`${kind}:${id}`}>${children ?? id.split("/").pop()}</a>`;
export const ValueRef = ({ axis, id }) => html`<${Ref} kind="value" id=${`${axis}/${id}`} />`;
export const Id = ({ children }) => html`<span class="id">${children}</span>`;
export const TierTitle = ({ tier }) => html`Tier ${tierNumber(tier.id)}: ${tier.label} <${Id}>${tier.id}<//>`;

const join = (items, sep) => items.flatMap((x, i) => (i ? [sep, x] : [x]));

export function preview(kind, key) {
  if (kind === "value") {
    const [axis, id] = key.split("/"), v = axisOf(axis)?.values.find((x) => x.id === id);
    return v && html`<b>${v.label}</b> <${Id}>${axis} ${id}<//><div>${v.definition}</div>`;
  }
  if (kind === "axis") {
    const a = axisOf(key);
    return a && html`<b>${title(a.id)}</b> <${Id}>${a.side} axis<//><div>${a.definition}</div>`;
  }
  if (kind === "prohibition") {
    const p = S.policy.prohibitions.find((x) => x.id === key);
    return p && html`<b>${p.id}</b><div>${p.text}</div>`;
  }
  if (kind === "principle") {
    const p = S.policy.principles.find((x) => x.id === key);
    return p && html`<b>${p.label}</b><div>${p.text}</div>`;
  }
  if (kind === "lexicon") {
    const l = S.policy.lexicons.find((x) => x.name === key);
    return l && html`<b>${l.name}</b><div>${l.size} entries, each reminds ${l.reminds}</div>`;
  }
  const t = tierOf(key.split("/")[0]);
  if (!t) return null;
  const head = html`<b>Tier ${tierNumber(t.id)}: ${t.label}</b> <${Id}>${kind === "cell" ? key : t.id}<//>`;
  return kind === "cell"
    ? html`${head}<div><${Allowed} allowed=${t.cells[key]?.allowed || {}} /></div>`
    : html`${head}<div>${t.definition} ${t.instruction}</div>`;
}

// A cell's rule: per response axis, the values a response may take.
export function Allowed({ allowed }) {
  const axes = S.policy.response_axes.filter((a) => allowed[a.id]);
  if (!axes.length) return html`<span class="muted">any</span>`;
  return join(axes.map((a) => html`<span class="axis">${a.id}</span> ${join(allowed[a.id].map((v) => html`<${ValueRef} axis=${a.id} id=${v} />`), ", ")}`), html`<br />`);
}

export const Table = ({ head, children }) =>
  html`<div class="table"><table><tr>${head.map((x) => html`<th>${x}</th>`)}</tr>${children}</table></div>`;

const product = (lists) => lists.reduce((acc, l) => acc.flatMap((a) => l.map((v) => [...a, v])), [[]]);

// A tier's grid: its first key axis down, the others across. `pick` makes its cells open their form; the cell a try
// lands in shows whether the response complies.
export function Grid({ tier, pick, selected, attempt }) {
  const keys = Object.keys(tier.condition);
  const columns = product(keys.slice(1).map((k) => tier.condition[k]));
  const landed = attempt?.prescription?.cell;
  const outcome = attempt?.compliance ? (attempt.compliance.ok ? " ok" : " ko") : "";
  const corner = join(keys.map((k) => html`<${Ref} kind="axis" id=${k} />`), keys.length > 1 ? " \\ " : "");
  return html`<div class="table"><table class=${"grid" + (pick ? " pickable" : "")}>
    <tr><th>${corner}</th>${columns.map((c) => html`<th>${c.length ? join(c.map((v, j) => html`<${ValueRef} axis=${keys[j + 1]} id=${v} />`), " / ") : "allowed"}</th>`)}</tr>
    ${tier.condition[keys[0]].map((row) => html`<tr><th><${ValueRef} axis=${keys[0]} id=${row} /></th>${columns.map((c) => {
      const id = [tier.id, row, ...c].join("/");
      const cls = "cell" + (id === selected ? " selected" : "") + (id === landed ? " landed" + outcome : "");
      const onClick = pick && ((e) => { e.preventDefault(); pick(id); });
      return html`<td class=${cls} onClick=${onClick}><${Allowed} allowed=${tier.cells[id].allowed} /></td>`;
    })}</tr>`)}
  </table></div>`;
}

export const Exchange = ({ e }) =>
  join([...e.context.map((m) => [m.role === "user" ? "User" : "Agent", m.content]), ["User", e.turn], ...(e.response == null ? [] : [["Agent", e.response]])]
    .map(([who, text]) => html`<b>${who}:</b> <i>${text}</i>`), html`<br />`);
