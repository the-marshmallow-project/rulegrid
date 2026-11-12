"""The editor's server: a stdlib web server over one profile, and the page in `static/`.

Every view runs on the page's unsaved text: the server loads the policy from it, checks it, compares it with git `HEAD`
and tries a turn on it. Every edit goes through `edit`, which rewrites only what changed, so comments and layout stay.
Saving writes the files in place, and git is the versioning. It binds to localhost and has no auth.
"""

from __future__ import annotations

import asyncio
import contextlib
import difflib
import json
import mimetypes
import os
import shutil
import subprocess
import tempfile
import threading
import weakref
from collections.abc import Callable, Mapping
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files as package_files
from pathlib import Path
from typing import Any, Literal

import yamlrocks

from rulegrid.check import check
from rulegrid.diff import diff
from rulegrid.generate import profile_schema
from rulegrid.lexicon import Entry, match
from rulegrid.policy import PROFILE, STRUCTURE, Policy, PolicyError, load
from rulegrid.render import nudge
from rulegrid.rules import comply, prescribe
from rulegrid.types import Classification, Classifier, Message

Path_ = list[str | int]


def edit(text: str, path: Path_, value: Any) -> str:
    """`text`, a YAML document, with the node at `path` set to `value`, or removed when `value` is None.

    Only the keys and items that differ are rewritten, so the comments and layout around them stay; a mapping missing
    on the way is created. A list keeps its layout when items are removed or appended, as the page does.
    """
    doc = yamlrocks.loads(text, option=yamlrocks.OPT_ROUND_TRIP)
    parent, old = doc, yamlrocks.loads(text) or {}
    for key in path[:-1]:
        if not _has(old, key) or old[key] is None:
            parent[key], old[key] = {}, {}
        parent, old = parent[key], old[key]
    splices: list[tuple[Path_, list[Any]]] = []
    if not path:  # the whole file
        _merge({"": doc}, "", old, value, [], splices)
    elif value is None:
        if _has(old, path[-1]):
            del parent[path[-1]]
    elif _has(old, path[-1]):
        _merge(parent, path[-1], old[path[-1]], value, path, splices)
    else:
        parent[path[-1]] = value
    out = yamlrocks.dumps(doc, option=yamlrocks.OPT_ROUND_TRIP)
    for at, items in splices:
        out = _splice(out, at, items)
    return out.decode()


def _has(node: Any, key: str | int) -> bool:
    return 0 <= key < len(node) if isinstance(node, list) and isinstance(key, int) else key in node


def _merge(parent: Any, key: str | int, old: Any, new: Any, at: Path_, splices: list[tuple[Path_, list[Any]]]) -> None:
    """Set `parent[key]`, which holds `old`, to `new`, descending into what both share.

    A list that grows by its end, or flow-style, is left to a splice of the dumped text: assigning a whole list would
    re-indent it and drop its comments.
    """
    if old == new:
        return
    if isinstance(old, dict) and isinstance(new, dict):
        node = parent[key]
        for k in [k for k in old if k not in new]:
            del node[k]
        for k, v in new.items():
            if k in old:
                _merge(node, k, old[k], v, [*at, k], splices)
            else:
                node[k] = v
        return
    if not (isinstance(old, list) and isinstance(new, list) and old):
        parent[key] = new
        return
    if parent[key].node.style == "flow":
        splices.append((at, new))
        return
    keys = [json.dumps(x, sort_keys=True) for x in old], [json.dumps(x, sort_keys=True) for x in new]
    ops = difflib.SequenceMatcher(None, *keys, autojunk=False).get_opcodes()
    if all(op in ("equal", "delete") for op, *_ in ops):  # items removed: delete them, and their comments stay put
        for op, i1, i2, *_ in reversed(ops):
            for i in reversed(range(i1, i2) if op == "delete" else ()):
                del parent[key][i]
        return
    if len(new) < len(old):
        parent[key] = new
        return
    for i, (a, b) in enumerate(zip(old, new[: len(old)], strict=True)):
        _merge(parent[key], i, a, b, [*at, i], splices)
    if len(new) > len(old):
        splices.append((at, new[len(old) :]))


def _splice(text: bytes, at: Path_, items: list[Any]) -> bytes:
    """`text` with the flow list at `at` set to `items`, or the block list at `at` followed by `items`."""
    node = yamlrocks.loads(text, option=yamlrocks.OPT_ROUND_TRIP)
    for key in at:
        node = node[key]
    if node.node.style == "flow":
        start, end = node.node.offset, text.index(b"]", node.node.end_offset - 1) + 1
        flow = "[" + ", ".join(json.dumps(x, ensure_ascii=False) for x in items) + "]"
        return text[:start] + flow.encode() + text[end:]
    last = node[len(node.unwrap()) - 1].node
    indent = " " * (last.column - 3)  # the column of the item's content, past its "- "
    end = text.find(b"\n", last.end_offset) + 1 or len(text)
    block = "".join(indent + line for line in yamlrocks.dumps(items).decode().splitlines(keepends=True))
    return text[:end] + block.encode() + text[end:]


class Workspace:
    """The policy's files on disk, and the policy they make with the page's unsaved text over them.

    Unsaved text is loaded from a mirror of the policy's folder, which the lock guards: a `Policy` reads its templates
    and generated files from its folder.
    """

    def __init__(self, path: Path, classifier: Callable[[Policy], Classifier] | None):
        policy = load(path)
        profile_dir = path.resolve()
        self.base = Path(os.path.commonpath([policy.root, profile_dir]))
        self.profile = profile_dir.relative_to(self.base)
        names = [policy.root / STRUCTURE, profile_dir / PROFILE, *sorted(profile_dir.glob("lexicons/*.yaml"))]
        self.names = [str(p.relative_to(self.base)) for p in names]
        self.classifier = classifier
        directory = tempfile.TemporaryDirectory(prefix="rulegrid-editor-")
        self.mirror = Path(directory.name) / self.base.name
        weakref.finalize(self, directory.cleanup)
        self.lock = threading.Lock()
        self.head: tuple[str, Policy, dict[str, str]] | None = None

    def files(self) -> dict[str, str]:
        return {name: (self.base / name).read_text() for name in self.names}

    def _texts(self, texts: Mapping[str, str]) -> dict[str, str]:
        if unknown := [name for name in texts if name not in self.names]:
            raise ValueError(f"not a file of this policy: {', '.join(unknown)}")
        return dict(texts)

    def save(self, texts: Mapping[str, str]) -> None:
        with self.lock:
            for name, text in self._texts(texts).items():
                (self.base / name).write_text(text)

    def load(self, texts: Mapping[str, str]) -> Policy:
        """The policy with `texts` over the files on disk. Call it with the lock held."""
        texts = self._texts(texts)
        shutil.copytree(self.base, self.mirror, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".*", "__pycache__"))
        for name, text in texts.items():
            (self.mirror / name).write_text(text)
        return load(self.mirror / self.profile)

    def changes(self, policy: Policy, texts: Mapping[str, str]) -> dict[str, Any]:
        """What changed from git `HEAD`: the articles, and each file's lines."""
        git = ["git", "-C", str(self.base)]
        try:
            sha = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
            if self.head is None or self.head[0] != sha:
                show = [*git, "show"]
                old = {n: subprocess.check_output([*show, f"{sha}:./{n}"], text=True) for n in self.names}
                self.head = sha, load(self.base / self.profile, revision=sha), old
        except (subprocess.CalledProcessError, OSError, PolicyError):
            return {"error": "no version at git HEAD to compare with"}
        _, before, old = self.head
        lines = {
            n: list(difflib.unified_diff(old[n].splitlines(), t.splitlines(), "HEAD", "now", lineterm=""))[2:]
            for n, t in texts.items()
        }
        return {"articles": str(diff(before, policy)), "files": {n: ls for n, ls in lines.items() if ls}}

    def view(self, texts: Mapping[str, str]) -> dict[str, Any]:
        with self.lock:
            try:
                policy = self.load(texts)
            except PolicyError as error:
                return {"problems": [str(p) for p in error.problems]}
            current = {**self.files(), **texts}
            return {
                "problems": [str(p) for p in check(policy)],
                "policy": _outline(policy),
                "changes": self.changes(policy, current),
                "schemas": _schemas(policy),
                "data": {name: yamlrocks.loads(text) for name, text in current.items()},
            }

    def edit(self, texts: Mapping[str, str], file: str, path: Path_, value: Any) -> str:
        self._texts({file: ""})
        with self.lock:
            return edit(texts[file] if file in texts else (self.base / file).read_text(), path, value)

    def attempt(self, texts: Mapping[str, str], request: dict[str, Any]) -> dict[str, Any]:
        """Read a turn and maybe a response: classified from their text, or from the values the page sets."""
        turn_text, response_text = request.get("turn", ""), request.get("response", "")
        with self.lock:
            policy = self.load(texts)
            classifier = self.classifier(policy) if self.classifier else None
        hits = match(policy.lexicons, turn_text)
        convo = [Message("user", turn_text)]

        async def read(of: Literal["turn", "response"], values: dict[str, Any] | None) -> Classification:
            if values is not None:
                return Classification({k: frozenset(v) if isinstance(v, list) else v for k, v in values.items()})
            if classifier is None:
                raise ValueError("no classifier: set the values, or start the editor with --classifier")
            if of == "turn":
                return await classifier.classify(convo, "turn", hits)
            return await classifier.classify([*convo, Message("assistant", response_text)], "response")

        async def both() -> tuple[Classification, Classification | None]:
            turn = read("turn", request.get("turn_values"))
            if request.get("response_values") is None and not response_text:
                return await turn, None
            return await asyncio.gather(turn, read("response", request.get("response_values")))

        turn, response = asyncio.run(both())
        with self.lock:
            note = nudge(policy, turn, hits)
        prescription = prescribe(policy, turn)
        return {
            "turn": _classification(turn),
            "hits": [{"text": h.text, "meaning": h.entry.meaning, "reminds": h.reminds} for h in hits],
            "prescription": prescription and asdict(prescription),
            "nudge": note,
            "response": response and _classification(response),
            "compliance": response and asdict(comply(policy, turn, response)),
        }


def _schemas(policy: Policy) -> dict[str, Any]:
    """The JSON Schemas the page builds its forms from: the profile's, and a lexicon file's."""
    lexicon = {
        "type": "object",
        "properties": {
            "reminds": {"title": "Reminds", "enum": list(policy.prohibitions)},
            "entries": {"title": "Entries", "type": "array", "items": Entry.model_json_schema()},
        },
        "required": ["reminds", "entries"],
    }
    return {"profile": profile_schema(policy), "lexicon": lexicon}


def _classification(c: Classification) -> dict[str, Any]:
    values = {k: sorted(v) if isinstance(v, frozenset) else v for k, v in c.values.items()}
    return {**asdict(c), "values": values}


def _json(value: Any) -> Any:
    """The policy's dataclasses as objects, sets and tuples as lists."""
    return list(value) if isinstance(value, set | frozenset | tuple) else asdict(value)


def _outline(policy: Policy) -> dict[str, Any]:
    """The policy as JSON: everything the page draws, from the document to the grids and the previews of every id."""
    return {
        "name": f"{policy.root.name} · {policy.name}",
        "context": policy.context,
        "principles": list(policy.principles.values()),
        "turn_axes": list(policy.turn_axes.values()),
        "response_axes": list(policy.response_axes.values()),
        "tiers": [
            {
                "id": t.id,
                "label": t.label,
                "definition": t.definition,
                "instruction": t.instruction,
                "condition": t.condition,
                "cells": {c.id: {"allowed": c.allowed, "examples": c.examples} for c in t.cells.values()},
            }
            for t in policy.tiers.values()
        ],
        "prohibitions": list(policy.prohibitions.values()),
        "lexicons": [{"name": x.name, "reminds": x.reminds, "size": len(x.entries)} for x in policy.lexicons],
    }


def _handler(workspace: Workspace) -> type[BaseHTTPRequestHandler]:
    static = package_files("rulegrid_editor").joinpath("static")

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, kind: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/api/files":
                body = {"files": workspace.files(), "classifier": workspace.classifier is not None}
                return self._send(200, json.dumps(body).encode())
            name = "index.html" if self.path == "/" else self.path.removeprefix("/static/")
            file = static.joinpath(*name.split("/"))
            if ".." in name or not file.is_file():
                return self._send(404, b"{}")
            kind = mimetypes.guess_type(name)[0] or "application/octet-stream"
            self._send(200, file.read_bytes(), f"{kind}; charset=utf-8")

        def do_POST(self) -> None:
            # A cross-origin form or no-CORS fetch cannot send application/json without a preflight.
            if self.headers.get_content_type() != "application/json":
                return self._send(415, b'{"error": "Expected application/json"}')
            try:
                request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                texts = request.pop("files", {})
                routes: dict[str, Callable[[], Any]] = {
                    "/api/view": lambda: workspace.view(texts),
                    "/api/save": lambda: workspace.save(texts),
                    "/api/edit": lambda: {"text": workspace.edit(texts, **request)},
                    "/api/try": lambda: workspace.attempt(texts, request),
                }
                if self.path not in routes:
                    return self._send(404, b"{}")
                self._send(200, json.dumps(routes[self.path](), default=_json).encode())
            except Exception as error:  # the page shows any failure, such as a classifier's, next to what caused it
                self._send(400, json.dumps({"error": f"{type(error).__name__}: {error}"}).encode())

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return Handler


def serve(path: str | Path, port: int = 8765, classifier: Callable[[Policy], Classifier] | None = None) -> None:
    """Serve the editor for the profile at `path` on `http://127.0.0.1:{port}`, until interrupted.

    Args:
        path: a profile directory, such as `examples/rbr/profiles/default`.
        port: the local port.
        classifier: makes the try panel's classifier from the policy being edited. Without it, the try panel reads
            the values set by hand.

    Raises:
        PolicyError: when the profile does not load.
    """
    with ThreadingHTTPServer(("127.0.0.1", port), _handler(Workspace(Path(path), classifier))) as server:
        print(f"rulegrid editor on http://127.0.0.1:{server.server_port}", flush=True)
        with contextlib.suppress(KeyboardInterrupt):
            server.serve_forever()
