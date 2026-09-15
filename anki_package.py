"""Turning extracted cards into an Anki deck package (.apkg).

The CSV export is the right thing on a desktop, where you can point Anki's file
picker at it. On a phone it is a dead end: AnkiDroid does not register itself
as a handler for `text/csv`, so a downloaded CSV just sits in the download
folder and the only way in is to hunt it down through AnkiDroid's own import
screen. AnkiDroid *does* register for `.apkg`, so a deck package downloaded
from the browser can be opened straight into Anki from the download
notification — one tap, no field mapping.

Kept apart from anki_export.py because it needs a third-party dependency
(genanki) that the CSV path deliberately does not.
"""

from __future__ import annotations

import hashlib
import io
import re

import pandas as pd

from anki_export import export_rows

try:  # genanki is optional: without it the app still offers the CSV export.
    import genanki
except ImportError:  # pragma: no cover - exercised by the availability check
    genanki = None

NOTE_TYPE_NAME = "Capybara"

# The seven content fields of a Capybara note. "deck" and "tags" are not fields
# — a package carries the deck in its own structure and the tags on each note —
# so they are handled separately rather than written into the note.
APKG_FIELDS = [
    "lemma",
    "gloss",
    "lemma_translation",
    "part_of_speech",
    "language",
    "example",
    "example_translation",
]

CARD_CSS = """
.card {
  font-family: -apple-system, system-ui, sans-serif;
  font-size: 22px;
  text-align: center;
  color: #1b1b1b;
  background-color: #fdfdfd;
}
.pos { font-size: 15px; color: #777; font-style: italic; }
.gloss { font-size: 18px; color: #555; }
.example { font-size: 18px; margin-top: 14px; }
.example-translation { font-size: 16px; color: #555; }
"""

FRONT_TEMPLATE = "<div class=\"lemma\">{{lemma}}</div>"

BACK_TEMPLATE = """{{FrontSide}}
<hr id="answer">
<div class="translation">{{lemma_translation}}</div>
<div class="gloss">{{gloss}}</div>
<div class="pos">{{part_of_speech}}</div>
<div class="example">{{example}}</div>
<div class="example-translation">{{example_translation}}</div>
"""


class PackageUnavailableError(RuntimeError):
    """genanki is not installed, so no .apkg can be built."""


def is_available() -> bool:
    return genanki is not None


def stable_id(seed: str) -> int:
    """A deck/note-type id derived from a name rather than drawn at random.

    Anki identifies a note type by id, not by name. genanki's documented
    recipe is to pick a random id once and hard-code it, which is the same
    thing as hashing a fixed string — except that hashing keeps the id visible
    and reproducible, so two exports a month apart land in the same note type
    and the same deck instead of stacking up copies named "Capybara-a3f1".
    """
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    # Anki ids live in the 32-bit range genanki documents: [1<<30, 1<<31).
    return (1 << 30) + int.from_bytes(digest[:8], "big") % (1 << 30)


def split_tags(value: str) -> list[str]:
    """Split a tags cell the way Anki would.

    Anki separates tags on whitespace and cannot represent a tag containing a
    space, so "capybara::vocab book" is two tags. Commas are accepted too,
    because a comma is what a person typing into the review table reaches for.
    """
    return [tag for tag in re.split(r"[,\s]+", value) if tag]


def build_model():
    return genanki.Model(
        model_id=stable_id(f"note-type:{NOTE_TYPE_NAME}"),
        name=NOTE_TYPE_NAME,
        fields=[{"name": name} for name in APKG_FIELDS],
        templates=[{
            "name": "Recognition",
            "qfmt": FRONT_TEMPLATE,
            "afmt": BACK_TEMPLATE,
        }],
        css=CARD_CSS,
    )


def build_apkg(df: pd.DataFrame) -> tuple[bytes, int]:
    """Render the edited table as an Anki deck package.

    Returns the raw .apkg bytes and the number of notes in it — the same rows
    `build_csv` would export, so the two buttons never disagree about the
    count.
    """
    if genanki is None:
        raise PackageUnavailableError(
            "genanki is not installed, so the .apkg export is unavailable. "
            "Install it with `pip install genanki`, or use the CSV export."
        )

    rows = export_rows(df)
    model = build_model()

    # A row's deck is editable, so several decks can come out of one table.
    # Group rather than assuming one, and keep first-seen order so the package
    # reads the same way the review table does.
    decks: dict[str, "genanki.Deck"] = {}
    for row in rows:
        deck_name = row["deck"] or "Capybara::Ukrainian"
        deck = decks.get(deck_name)
        if deck is None:
            deck = genanki.Deck(deck_id=stable_id(f"deck:{deck_name}"), name=deck_name)
            decks[deck_name] = deck

        deck.add_note(genanki.Note(
            model=model,
            fields=[row[name] for name in APKG_FIELDS],
            tags=split_tags(row["tags"]),
            # Identity is the word, not the whole note. genanki's default guid
            # hashes every field, which would make a card you re-exported after
            # fixing its translation import as a second, unrelated note.
            guid=genanki.guid_for(
                row["lemma"].casefold(),
                row["part_of_speech"].casefold(),
            ),
        ))

    buffer = io.BytesIO()
    genanki.Package(list(decks.values())).write_to_file(buffer)
    return buffer.getvalue(), len(rows)
