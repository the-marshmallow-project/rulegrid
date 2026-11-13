"""The `rulegrid` command: create, check, generate, render, diff and evaluate policies.

POLICY is a profile directory, such as `examples/rbr/profiles/default`. The built-in classifiers read their endpoint and
key from the environment: `RULEGRID_SYSTEMONE_URL` and `RULEGRID_SYSTEMONE_KEY`, or `RULEGRID_LLM_URL` and
`RULEGRID_LLM_KEY`.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import shutil
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from rulegrid.check import check
from rulegrid.diff import diff
from rulegrid.evaluate import Dataset, evaluate
from rulegrid.generate import generate
from rulegrid.judge import Judge, openai_compatible
from rulegrid.policy import Policy, PolicyError, load
from rulegrid.render import render
from rulegrid.systemone import SystemOne
from rulegrid.types import Classifier

TOYS = ("three_laws", "rbr")


def _init(name: str, toy: str) -> int:
    """Copy a toy policy to the new directory `name`. The toys ship in the package, or sit in a checkout's examples."""
    here = Path(__file__).parent
    source = next(p for root in (here / "examples", here.parents[1] / "examples") if (p := root / toy).is_dir())
    try:
        shutil.copytree(source, name, ignore=shutil.ignore_patterns("__pycache__"))
    except FileExistsError:
        print(f"{name} already exists", file=sys.stderr)
        return 1
    profile = Path(name, "profiles", "default")
    print(f"wrote {name}, a copy of the {toy} policy. Edit its structure.yaml and {profile / 'profile.yaml'}, then:")
    print(f"  rulegrid check {profile}")
    return 0


def _load_at(spec: str) -> Policy:
    """A profile directory, or `DIR@REV` for the same directory at a git revision, such as `profiles/fr@HEAD~1`."""
    if "@" not in spec:
        return load(spec)
    path, revision = spec.rsplit("@", 1)
    return load(path, revision=revision)


def classifier(
    spec: str, thresholds: dict[str, float], breach: float = 0.5, examples: bool = True
) -> Callable[[Policy], Classifier]:
    """`systemone[:MODEL]`, `judge:MODEL`, or `module:attr`, a factory taking the policy.

    `examples=False` keeps the policy's examples out of SystemOne's questions, to evaluate it on them.
    """
    kind, _, model = spec.partition(":")
    needed = {
        "systemone": ("RULEGRID_SYSTEMONE_URL", "RULEGRID_SYSTEMONE_KEY"),
        "judge": ("RULEGRID_LLM_URL", "RULEGRID_LLM_KEY"),
    }.get(kind, ())
    if missing := [name for name in needed if name not in os.environ]:
        raise SystemExit(f"--classifier {kind} needs {' and '.join(missing)} in the environment")
    if kind == "systemone":
        url, key = os.environ["RULEGRID_SYSTEMONE_URL"], os.environ["RULEGRID_SYSTEMONE_KEY"]
        return lambda p: SystemOne(p, url, key, model or None, thresholds=thresholds, breach=breach, examples=examples)
    if kind == "judge":
        url, key = os.environ["RULEGRID_LLM_URL"], os.environ["RULEGRID_LLM_KEY"]
        return lambda p: Judge(p, openai_compatible(url, key, model))
    sys.path.insert(0, os.getcwd())  # a module beside the caller's files, as `python -m` would find it
    return getattr(importlib.import_module(kind), model)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rulegrid", description=(__doc__ or "").split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    i = commands.add_parser("init", help="a new policy, copied from a toy policy")
    i.add_argument("name", help="the directory to create")
    i.add_argument("--from", dest="toy", choices=TOYS, default=TOYS[0])
    commands.add_parser("check", help="static checks; exit 1 on any problem").add_argument("policy")
    commands.add_parser(
        "generate", help="profile.schema.json and structure_types.py, from structure.yaml"
    ).add_argument("policy")
    r = commands.add_parser("render", help="the policy as text")
    r.add_argument("policy")
    r.add_argument("--rendering", choices=["document", "prompt", "judge"], default="document")
    r.add_argument("-o", "--output", help="a file, stdout by default")
    d = commands.add_parser("diff", help="what changed between two versions; DIR@REV reads a git revision")
    d.add_argument("old")
    d.add_argument("new")
    e = commands.add_parser("eval", help="a classifier on a dataset, the policy's own examples by default")
    e.add_argument("policy")
    e.add_argument("--data", help="a JSONL dataset")
    e.add_argument("--classifier", required=True, help="systemone[:MODEL], judge:MODEL or module:attr")
    e.add_argument("--json", action="store_true", help="the agreement per label as JSON")
    e.add_argument("--breach", type=float, default=0.5, metavar="P", help="SystemOne's breach threshold")
    e.add_argument("--threshold", action="append", default=[], metavar="TIER=P", help="SystemOne tiers")
    args = parser.parse_args(argv)

    if args.command == "init":
        return _init(args.name, args.toy)
    thresholds = {t: float(p) for t, p in (t.split("=") for t in getattr(args, "threshold", []))}
    try:
        if args.command == "diff":
            print(diff(_load_at(args.old), _load_at(args.new)))
            return 0
        policy = load(args.policy)
    except PolicyError as error:
        print(error, file=sys.stderr)
        return 1
    if args.command == "check":
        problems = check(policy)
        for problem in problems:
            print(problem)
        return 1 if problems else 0
    if args.command == "generate":
        for name in generate(policy):
            print(f"wrote {policy.root / name}")
        return 0
    if args.command == "render":
        text = render(policy, args.rendering)
        if args.output:
            Path(args.output).write_text(text)
        else:
            print(text, end="")
        return 0
    data = Dataset.load(args.data) if args.data else Dataset.from_policy(policy)
    # On the policy's own examples, the questions leave them out: a classifier shown an example would only echo it.
    implementation = classifier(args.classifier, thresholds, args.breach, examples=bool(args.data))(policy)
    report = asyncio.run(evaluate(policy, data, implementation))
    print(json.dumps(report.agreement()) if args.json else report.markdown(), end="")
    return 0 if all(r.ok for r in report.results) else 1


if __name__ == "__main__":
    sys.exit(main())
