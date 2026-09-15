"""The .apkg export: the file AnkiDroid can actually open.

A downloaded CSV is inert on a phone — nothing registers a handler for
`text/csv`, so it sits in the download folder. These tests read the package
back out the way Anki would: it is a zip holding an SQLite collection.
"""

import io
import json
import sqlite3
import zipfile

import pandas as pd
import pytest

from anki_export import EXPORT_COLUMNS
from anki_package import (
    APKG_FIELDS,
    NOTE_TYPE_NAME,
    build_apkg,
    is_available,
    split_tags,
    stable_id,
)

pytestmark = pytest.mark.skipif(not is_available(), reason="genanki is not installed")

FIELD_SEPARATOR = "\x1f"


def card(**overrides) -> dict:
    base = {
        "lemma": "книга",
        "gloss": "book",
        "lemma_translation": "book",
        "part_of_speech": "noun",
        "language": "uk",
        "example": "Книга тут.",
        "example_translation": "The book is here.",
        "deck": "Capybara::Ukrainian",
        "tags": "capybara::vocab",
        "source": "page1.jpg",
    }
    base.update(overrides)
    return base


def collection_of(data: bytes, tmp_path) -> sqlite3.Connection:
    """Open the SQLite collection inside a .apkg, as Anki does on import."""
    archive = zipfile.ZipFile(io.BytesIO(data))
    archive.extract("collection.anki2", tmp_path)
    return sqlite3.connect(tmp_path / "collection.anki2")


def notes_in(con: sqlite3.Connection) -> list[tuple[str, str, list[str]]]:
    return [
        (guid, tags, fields.split(FIELD_SEPARATOR))
        for guid, tags, fields in con.execute("SELECT guid, tags, flds FROM notes")
    ]


def test_the_package_is_a_zip_holding_a_collection(tmp_path):
    data, count = build_apkg(pd.DataFrame([card()]))
    assert data[:2] == b"PK"
    assert count == 1
    assert "collection.anki2" in zipfile.ZipFile(io.BytesIO(data)).namelist()


def test_a_note_carries_the_seven_capybara_fields_in_order(tmp_path):
    data, _ = build_apkg(pd.DataFrame([card()]))
    [(_, _, fields)] = notes_in(collection_of(data, tmp_path))
    assert fields == ["книга", "book", "book", "noun", "uk", "Книга тут.", "The book is here."]
    assert len(APKG_FIELDS) == 7


def test_deck_and_tags_are_not_written_into_the_note_as_fields(tmp_path):
    # They are structure, not content: the deck is the package's own, the tags
    # are the note's. Writing them as fields would shift every field right.
    data, _ = build_apkg(pd.DataFrame([card()]))
    [(_, tags, fields)] = notes_in(collection_of(data, tmp_path))
    assert "Capybara::Ukrainian" not in fields
    assert tags.split() == ["capybara::vocab"]


def test_the_note_type_is_named_capybara_with_the_expected_fields(tmp_path):
    data, _ = build_apkg(pd.DataFrame([card()]))
    con = collection_of(data, tmp_path)
    models = json.loads(con.execute("SELECT models FROM col").fetchone()[0])
    [model] = models.values()
    assert model["name"] == NOTE_TYPE_NAME
    assert [field["name"] for field in model["flds"]] == APKG_FIELDS


def test_rows_with_different_decks_become_different_decks(tmp_path):
    data, count = build_apkg(pd.DataFrame([
        card(),
        card(lemma="слово", deck="Capybara::Other"),
    ]))
    assert count == 2
    con = collection_of(data, tmp_path)
    decks = json.loads(con.execute("SELECT decks FROM col").fetchone()[0])
    names = {deck["name"] for deck in decks.values()}
    assert {"Capybara::Ukrainian", "Capybara::Other"} <= names
    assert len({did for _, did in con.execute("SELECT id, did FROM cards")}) == 2


def test_source_column_is_not_exported(tmp_path):
    data, _ = build_apkg(pd.DataFrame([card(source="page1.jpg")]))
    [(_, _, fields)] = notes_in(collection_of(data, tmp_path))
    assert "page1.jpg" not in fields


def test_blank_row_added_in_the_editor_is_dropped(tmp_path):
    blank = {column: "" for column in EXPORT_COLUMNS}
    data, count = build_apkg(pd.DataFrame([card(), blank]))
    assert count == 1
    assert len(notes_in(collection_of(data, tmp_path))) == 1


def test_missing_cells_export_as_empty_not_nan(tmp_path):
    data, _ = build_apkg(pd.DataFrame([card(gloss=None)]))
    [(_, _, fields)] = notes_in(collection_of(data, tmp_path))
    assert fields[1] == ""


def test_newline_in_a_sentence_is_collapsed(tmp_path):
    data, _ = build_apkg(pd.DataFrame([card(example="Перший.\nДругий.")]))
    [(_, _, fields)] = notes_in(collection_of(data, tmp_path))
    assert fields[5] == "Перший. Другий."


def test_an_empty_table_produces_a_package_with_no_notes(tmp_path):
    data, count = build_apkg(pd.DataFrame(columns=EXPORT_COLUMNS))
    assert count == 0
    assert notes_in(collection_of(data, tmp_path)) == []


# --- Re-import behaviour ------------------------------------------------------

def test_reexporting_an_edited_card_updates_it_rather_than_duplicating_it(tmp_path):
    # genanki's default guid hashes every field, so fixing a translation and
    # re-exporting would import as a second, unrelated note. Identity here is
    # the word itself.
    original, _ = build_apkg(pd.DataFrame([card()]))
    edited, _ = build_apkg(pd.DataFrame([card(lemma_translation="tome", example="Інше.")]))
    [(first_guid, _, _)] = notes_in(collection_of(original, tmp_path / "a"))
    [(second_guid, _, _)] = notes_in(collection_of(edited, tmp_path / "b"))
    assert first_guid == second_guid


def test_the_same_spelling_with_a_different_part_of_speech_is_a_separate_note(tmp_path):
    data, _ = build_apkg(pd.DataFrame([
        card(lemma="добре", part_of_speech="adverb"),
        card(lemma="добре", part_of_speech="adjective"),
    ]))
    guids = {guid for guid, _, _ in notes_in(collection_of(data, tmp_path))}
    assert len(guids) == 2


def test_two_exports_land_in_the_same_note_type_and_deck(tmp_path):
    # Anki matches a note type by id, not by name. A fresh random id per export
    # would stack up copies called "Capybara-a3f1" in the collection.
    first = json.loads(collection_of(build_apkg(pd.DataFrame([card()]))[0], tmp_path / "a")
                       .execute("SELECT models FROM col").fetchone()[0])
    second = json.loads(collection_of(build_apkg(pd.DataFrame([card()]))[0], tmp_path / "b")
                        .execute("SELECT models FROM col").fetchone()[0])
    assert list(first) == list(second)


def test_ids_sit_in_the_range_anki_expects():
    for seed in ("note-type:Capybara", "deck:Capybara::Ukrainian", ""):
        assert 1 << 30 <= stable_id(seed) < 1 << 31


# --- split_tags ---------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("capybara::vocab", ["capybara::vocab"]),
    # Anki separates tags on whitespace and cannot hold a tag with a space in it.
    ("capybara::vocab book", ["capybara::vocab", "book"]),
    # A person editing the table reaches for a comma; Anki would not split on it.
    ("capybara::vocab, book", ["capybara::vocab", "book"]),
    ("", []),
    ("   ", []),
])
def test_split_tags(value, expected):
    assert split_tags(value) == expected
