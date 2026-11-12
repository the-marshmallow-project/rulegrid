"""rulegrid: behavior policies as code.

A policy classifies a user's turn on its turn axes; its tiers, tried in order, prescribe the values a response may take
on each response axis; a response complies when it takes allowed values and breaches no prohibition.
"""

from rulegrid.check import check
from rulegrid.diff import diff
from rulegrid.evaluate import Dataset, compare, evaluate
from rulegrid.judge import Judge, openai_compatible
from rulegrid.lexicon import Lexicon, match
from rulegrid.policy import Policy, load
from rulegrid.render import nudge, render
from rulegrid.rules import comply, prescribe
from rulegrid.systemone import SystemOne
from rulegrid.types import (
    Article,
    Breach,
    Classification,
    Classifier,
    Complete,
    Compliance,
    Decide,
    Hit,
    Message,
    Prescription,
    Problem,
)

__all__ = [
    "Article",
    "Breach",
    "Classification",
    "Classifier",
    "Complete",
    "Compliance",
    "Dataset",
    "Decide",
    "Hit",
    "Judge",
    "Lexicon",
    "Message",
    "Policy",
    "Prescription",
    "Problem",
    "SystemOne",
    "check",
    "compare",
    "comply",
    "diff",
    "evaluate",
    "load",
    "match",
    "nudge",
    "openai_compatible",
    "prescribe",
    "render",
]
