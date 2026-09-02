"""Turning extracted cards into a Capybara-note-type Anki CSV.

Kept apart from app.py so the export rules can be tested without executing a
Streamlit script.
"""

from __future__ import annotations

import csv
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


def build_csv(df: pd.DataFrame) -> tuple[str, int]:
    """Render the edited table as a Capybara-note-type CSV.

    Every field is quoted. Besides making embedded commas and quotes
    unambiguous, that keeps a row whose first field starts with "#" from being
    read as an import directive and silently dropped.
    """
    rows = []
    for _, row in df.iterrows():
        fields = [clean_field(row.get(column)) for column in EXPORT_COLUMNS]
        if not fields[0]:
            continue  # A row with no lemma is an empty row the editor added.
        rows.append(fields)

    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerows(rows)
    return ANKI_HEADER + buffer.getvalue(), len(rows)
