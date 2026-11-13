// The editor's shell: the rail of concepts, the page the route names, the try panel, and the unsaved text under them.
import { render } from "preact";
import { useEffect, useLayoutEffect, useRef, useState } from "preact/hooks";
import { Axis, Changes, Document, Lexicon, Profile, Prohibitions, Structure, Tier, Yaml } from "./pages.js";
import { Try } from "./try.js";
import { S, anchor, html, preview, tierNumber, title } from "./ui.js";

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error);
  return data;
}

const route = () => (location.hash.slice(2) || "document").split("/").map(decodeURIComponent);
const lexiconFile = (texts, name) => Object.keys(texts).find((n) => n.endsWith(`/lexicons/${name}.yaml`));

function Rail({ policy, at }) {
  const here = at.join("/");
  const link = (to, label) => html`<a href=${"#/" + to} class=${here === to || here.startsWith(to + "/") ? "on" : ""}>${label}</a>`;
  const axes = (side) => policy[side].map((a) => link(`axes/${a.id}`, title(a.id)));
  return html`<nav>
    ${link("document", "Document")}
    ${link("changes", "Changes")}
    <h4>Policy</h4>
    ${link("profile", "Profile")}
    ${link("structure", "Structure")}
    <h4>Turn axes</h4>${axes("turn_axes")}
    <h4>Response axes</h4>${axes("response_axes")}
    <h4>Tiers</h4>${policy.tiers.map((t) => link(`tiers/${t.id}`, `${tierNumber(t.id)}. ${t.label}`))}
    <h4>Every tier</h4>${link("prohibitions", "Prohibitions")}
    ${policy.lexicons.length > 0 && html`<h4>Lexicons</h4>${policy.lexicons.map((l) => link(`lexicons/${l.name}`, l.name))}`}
    <hr />
    ${link("yaml", "YAML files")}
  </nav>`;
}

// The preview of the id under the pointer.
function Peek() {
  const [peek, setPeek] = useState(null), box = useRef();
  useEffect(() => {
    let timer;
    const over = (e) => {
      const a = e.target.closest?.(".ref");
      clearTimeout(timer);
      if (!a) return setPeek(null);
      timer = setTimeout(() => {
        const [kind, ...key] = a.dataset.ref.split(":");
        const content = preview(kind, key.join(":"));
        if (content) setPeek({ content, at: a.getBoundingClientRect() });
      }, 250);
    };
    const hide = () => setPeek(null);
    document.addEventListener("mouseover", over);
    document.addEventListener("click", hide);
    return () => { document.removeEventListener("mouseover", over); document.removeEventListener("click", hide); };
  }, []);
  useLayoutEffect(() => {
    if (!peek) return;
    const el = box.current, { at } = peek;
    el.style.left = Math.max(8, Math.min(at.left, innerWidth - el.offsetWidth - 8)) + "px";
    el.style.top = (at.bottom + 6 + el.offsetHeight > innerHeight ? at.top - el.offsetHeight - 6 : at.bottom + 6) + "px";
  });
  return peek && html`<div class="peek" ref=${box}>${peek.content}</div>`;
}

function App() {
  const [saved, setSaved] = useState(null), [texts, setTexts] = useState({});
  const [view, setView] = useState(null), [problems, setProblems] = useState([]);
  const [classifier, setClassifier] = useState(false), [attempt, setAttempt] = useState(null);
  const [at, setAt] = useState(route()), [showTry, setShowTry] = useState(true);
  const timer = useRef(), last = useRef(texts);
  last.current = texts;

  // Only the files that differ from disk travel: the server reads the others.
  const unsaved = (t = last.current) => Object.fromEntries(Object.entries(t).filter(([n, x]) => x !== saved?.[n]));
  const refresh = async (t) => {
    const v = await api("/api/view", { files: unsaved(t) });
    setProblems(v.problems);
    if (v.policy) { S.policy = v.policy; setView(v); } // when the files don't load, the last policy that did stays
  };
  const update = (next, soon) => {
    setTexts(next);
    last.current = next;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => refresh(next), soon ? 400 : 0);
  };
  const edit = (file) => async (path, value) => {
    try {
      const { text } = await api("/api/edit", { files: unsaved(), file, path, value });
      update({ ...last.current, [file]: text });
    } catch (e) { alert(e.message); }
  };
  const save = async () => {
    const files = unsaved();
    if (!Object.keys(files).length) return;
    if (problems.length && !confirm(`Save with ${problems.length} problem${problems.length > 1 ? "s" : ""}?`)) return;
    await api("/api/save", { files });
    setSaved({ ...saved, ...files });
    refresh(last.current);
  };

  useEffect(() => {
    (async () => {
      const start = await api("/api/files");
      setSaved(start.files);
      setTexts(start.files);
      last.current = start.files;
      setClassifier(start.classifier);
      const v = await api("/api/view", { files: {} });
      setProblems(v.problems);
      S.policy = v.policy;
      setView(v);
    })();
    const onHash = () => setAt(route());
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => {
    const onKey = (e) => { if ((e.metaKey || e.ctrlKey) && e.key === "s") { e.preventDefault(); save(); } };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  });
  // A link scrolls to the definition it names, once the page shows it.
  const shown = useRef(null);
  useEffect(() => {
    if (!view) return;
    // Picking another cell of the grid on screen keeps the grid where it is.
    const same = shown.current && at[0] === "tiers" && shown.current[0] === "tiers" && shown.current[1] === at[1];
    shown.current = at;
    if (same) return;
    const el = document.getElementById(anchor(at) || "");
    if (!el) return void scrollTo(0, 0);
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
  }, [at.join("/"), !!view]);

  if (!view) return html`<header><b>rulegrid</b> <span class="muted">${problems.join("\n") || "loading…"}</span></header>`;
  const { policy, data, schemas, changes } = view;
  const profile = Object.keys(texts).find((n) => n.endsWith("profile.yaml") && !n.includes("/lexicons/"));
  const props = { policy, data: data[profile], schemas, edit: edit(profile), attempt };
  const [page, ...key] = at;
  const pages = {
    document: () => html`<${Document} policy=${policy} />`,
    profile: () => html`<${Profile} ...${props} />`,
    structure: () => html`<${Structure} policy=${policy} />`,
    axes: () => html`<${Axis} id=${key[0]} ...${props} />`,
    tiers: () => html`<${Tier} id=${key[0]} cell=${key.length > 1 ? key.join("/") : null} ...${props} />`,
    prohibitions: () => html`<${Prohibitions} ...${props} />`,
    lexicons: () => {
      const file = lexiconFile(texts, key[0]);
      return file ? html`<${Lexicon} name=${key[0]} data=${data[file]} schemas=${schemas} edit=${edit(file)} />` : html`<p class="muted">No lexicon ${key[0]}.</p>`;
    },
    changes: () => html`<${Changes} changes=${changes} />`,
    yaml: () => html`<${Yaml} texts=${texts} saved=${saved} file=${key.join("/")} setText=${(n, t) => update({ ...last.current, [n]: t }, true)} />`,
  };
  const dirty = Object.keys(unsaved(texts));
  const n = problems.length;
  return html`
    <header>
      <b>${policy.name}</b>
      <span class=${n ? "warn" : "muted"}>${n ? `${n} problem${n > 1 ? "s" : ""}` : "no problems"}</span>
      <span style="flex: 1"></span>
      ${dirty.length > 0 && html`<a class="muted" href="#/changes">unsaved: ${dirty.map((d) => d.split("/").pop()).join(", ")}</a>`}
      <button class="primary" disabled=${!dirty.length} onClick=${save}>Save</button>
      <button onClick=${() => setShowTry(!showTry)} title="Show or hide the try panel">${showTry ? "Hide try" : "Try"}</button>
    </header>
    <div class=${"layout" + (showTry ? "" : " no-try")}>
      <${Rail} policy=${policy} at=${at} />
      <main>
        ${n > 0 && html`<div class="problems">${problems.join("\n")}</div>`}
        ${(pages[page] || pages.document)()}
      </main>
      ${showTry && html`<${Try} attempt=${attempt} setAttempt=${setAttempt} classifier=${classifier} run=${(body) => api("/api/try", { files: unsaved(), ...body })} />`}
    </div>
    <${Peek} />`;
}

render(html`<${App} />`, document.body);
