"""Lexicons: the enumerated wording of a prohibition, matched deterministically in a turn.

A lexicon lists words the agent must not repeat or accept, often ones a model does not know, each with its meaning. A
hit reminds the lexicon's prohibition, as a classifier's reminder does.
"""

from __future__ import annotations

import functools
import re
import unicodedata
from collections.abc import Sequence
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from rulegrid.types import Hit


class Entry(BaseModel):
    """A word or a phrase and its meaning.

    It matches whole words, ignoring case, accents and spacing or hyphenation. `forms` lists additional spellings,
    including inflections: the matcher adds none. `prefix` matches any ending. `languages` restricts an entry to
    conversations in those languages, for a word that is innocent in another one.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    word: str
    meaning: str
    forms: tuple[str, ...] = ()
    prefix: bool = False
    languages: tuple[str, ...] | None = None

    @model_validator(mode="after")
    def searchable(self) -> Self:
        if any(not _fold(word).strip() for word in (self.word, *self.forms)):
            raise ValueError("each word and form must contain a letter or digit")
        return self


class Lexicon(BaseModel):
    """A word list, named after its file, whose hits remind the prohibition `reminds`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    reminds: str
    entries: tuple[Entry, ...]


def _fold(text: str) -> str:
    """Lowercase, strip accents and blank out anything but letters and digits, one character for one."""
    folded = []
    for char in text:
        base = unicodedata.normalize("NFKD", char)[:1].lower()[:1] or char
        folded.append(base if base.isalnum() else " ")
    return "".join(folded)


@functools.cache
def _pattern(word: str, prefix: bool) -> re.Pattern[str]:
    words = _fold(word).split()
    ending = r"\w*" if prefix else ""
    return re.compile(r"(?<!\w)" + r"\s+".join(map(re.escape, words)) + ending + r"(?!\w)")


def match(
    lexicons: Sequence[Lexicon],
    text: str,
    language: str | None = None,
) -> list[Hit]:
    """The lexicon entries found in `text`, in order of first appearance, each entry once.

    A phrase wins over a word it overlaps: "hot dog" is not also "dog".

    Args:
        lexicons: the word lists, such as `policy.lexicons`.
        text: what to search, such as the turn's last message.
        language: the conversation's language, which leaves out entries restricted to others; every entry if None.
    """
    folded = _fold(text)
    found: list[tuple[int, int, Hit]] = []
    for lexicon in lexicons:
        for entry in lexicon.entries:
            if language is not None and entry.languages is not None and language not in entry.languages:
                continue
            for word in (entry.word, *entry.forms):
                for m in _pattern(word, entry.prefix).finditer(folded):
                    found.append((m.start(), m.end(), Hit(text[m.start() : m.end()], entry, lexicon.reminds)))
    found.sort(key=lambda f: f[0] - f[1])
    kept: list[tuple[int, int, Hit]] = []
    for f in found:
        if not any(k[0] < f[1] and f[0] < k[1] for k in kept):
            kept.append(f)
    kept.sort(key=lambda f: f[0])
    unique: dict[tuple[str, str], Hit] = {}
    for _, _, hit in kept:
        unique.setdefault((hit.reminds, hit.entry.word), hit)
    return list(unique.values())
