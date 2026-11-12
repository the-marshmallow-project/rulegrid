"""rulegrid-editor: browse, edit and try a rulegrid policy in the browser.

POLICY is a profile directory, such as `examples/rbr/profiles/default`. The try panel's classifier reads its endpoint
and key from the environment, as `rulegrid eval` does.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from rulegrid.cli import classifier
from rulegrid.policy import PolicyError
from rulegrid_editor.server import edit, serve

__all__ = ["edit", "main", "serve"]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rulegrid-editor", description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("policy")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--classifier", help="the try panel's: systemone[:MODEL], judge:MODEL or module:attr")
    parser.add_argument("--threshold", action="append", default=[], metavar="TIER=P", help="SystemOne tiers")
    args = parser.parse_args(argv)
    thresholds = {t: float(p) for t, p in (t.split("=") for t in args.threshold)}
    try:
        serve(args.policy, args.port, args.classifier and classifier(args.classifier, thresholds))
    except PolicyError as error:
        print(error, file=sys.stderr)
        return 1
    return 0
