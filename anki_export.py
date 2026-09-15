"""Turning extracted cards into a Capybara-note-type Anki CSV.

Kept apart from app.py so the export rules can be tested without executing a
Streamlit script.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io

import pandas as pd

# The nine columns of the Capybara note type, in the order the #columns header
# declares them. Built explicitly so a column added to the review table (like
# "source") cannot leak into the export and shift every field right.
EXPORT_COLUMNS = [
    "lemma",
    "gloss",
    "lemma_translation",
    "part_of_speech",
    "language",
    "example",
    "example_translation",
    "deck",
    "tags",
]

ANKI_HEADER = (
    "#separator:Comma\n"
    "#html:false\n"
    "#notetype:Capybara\n"
    "#columns:" + ",".join(EXPORT_COLUMNS) + "\n"
    "#deck column:8\n"
    "#tags column:9\n"
)


def clean_field(value) -> str:
    """Collapse a cell to a single line of text.

    Anki reads one note per line, so a stray newline inside an example sentence
    would split a card in half. Also normalises NaN, which `st.data_editor`
    leaves behind in any row the user adds but does not fill in.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return " ".join(str(value).split())


def dedupe_cards(cards: list[dict]) -> tuple[list[dict], int]:
    """Merge cards for the same word, keeping the first sighting of each.

    A word highlighted on three pages is one thing to learn, not three. The
    surviving row records every page it appeared on, so the count on screen
    matches the number of notes Anki will actually create.
    """
    merged: dict[tuple[str, str], dict] = {}
    duplicates = 0
    for card in cards:
        key = (card["lemma"].strip().casefold(), card["part_of_speech"].strip().casefold())
        existing = merged.get(key)
        if existing is None:
            merged[key] = dict(card)
            continue
        duplicates += 1
        source = card.get("source", "")
        if source and source not in existing.get("source", ""):
            existing["source"] = f"{existing['source']}, {source}".strip(", ")
    return list(merged.values()), duplicates


def export_rows(df: pd.DataFrame) -> list[dict]:
    """Clean the edited table down to the rows worth exporting.

    Shared by both exporters so the CSV and the .apkg always contain the same
    cards: same cleaning, same dropped rows, same count on the button label.
    """
    rows = []
    for _, row in df.iterrows():
        fields = {column: clean_field(row.get(column)) for column in EXPORT_COLUMNS}
        if not fields["lemma"]:
            continue  # A row with no lemma is an empty row the editor added.
        rows.append(fields)
    return rows


def build_csv(df: pd.DataFrame) -> tuple[str, int]:
    """Render the edited table as a Capybara-note-type CSV.

    Every field is quoted. Besides making embedded commas and quotes
    unambiguous, that keeps a row whose first field starts with "#" from being
    read as an import directive and silently dropped.
    """
    rows = export_rows(df)

    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerows([[row[column] for column in EXPORT_COLUMNS] for row in rows])
    return ANKI_HEADER + buffer.getvalue(), len(rows)


def export_stamp(content: str, cache: dict, now: dt.datetime | None = None) -> str:
    """A timestamp that changes when the export changes, and only then.

    It is tempting to just call `datetime.now()` at render time, but that is a
    trap. Streamlit reruns this script on every interaction, and it identifies
    a download button's file by hashing the bytes *and the filename* together.
    A filename holding the current time therefore mints a brand-new file on
    every rerun and orphans the previous one — which Streamlit's media garbage
    collector then deletes, leaving the button the user is looking at pointing
    at a URL that 404s. The tap does nothing and reports nothing.

    So the clock is read once per distinct export and held until the cards
    change. `cache` is a single-entry store the caller owns (session state),
    which keeps this a plain function and keeps the store from growing with
    every keystroke in the review table.
    """
    key = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if cache.get("key") != key:
        cache["key"] = key
        cache["stamp"] = (now or dt.datetime.now()).strftime("%Y%m%d-%H%M%S")
    return cache["stamp"]


def export_filename(extension: str, stamp: str) -> str:
    """The name a download lands under in the phone's download folder.

    A fixed name collides with the copy already there, and Android Chrome
    meets a collision with a "Download file again?" dialog on every single
    tap. The stamp comes from `export_stamp`, so successive exports differ
    while repeated renders of the same export do not.
    """
    return f"ukrainian_vocab_capybara_{stamp}.{extension.lstrip('.')}"
