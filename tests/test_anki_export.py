"""Export rules: what makes a row survive the trip into Anki intact."""

import csv
import datetime as dt

import pandas as pd
import pytest

from anki_export import (
    ANKI_HEADER,
    EXPORT_COLUMNS,
    build_csv,
    clean_field,
    dedupe_cards,
    export_filename,
    export_rows,
    export_stamp,
)


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


def body_of(csv_text: str) -> str:
    assert csv_text.startswith(ANKI_HEADER)
    return csv_text[len(ANKI_HEADER):]


def rows_of(csv_text: str) -> list[list[str]]:
    return list(csv.reader(body_of(csv_text).strip("\n").splitlines()))


# --- dedupe_cards -------------------------------------------------------------

def test_same_word_on_two_pages_becomes_one_card():
    merged, duplicates = dedupe_cards([
        card(lemma="читати", part_of_speech="verb", source="page1.jpg"),
        card(lemma="читати", part_of_speech="verb", source="page9.jpg"),
    ])
    assert len(merged) == 1
    assert duplicates == 1
    assert merged[0]["source"] == "page1.jpg, page9.jpg"


def test_dedup_ignores_case_and_surrounding_space():
    merged, duplicates = dedupe_cards([
        card(lemma="Читати", part_of_speech="Verb"),
        card(lemma="читати ", part_of_speech=" verb"),
    ])
    assert len(merged) == 1 and duplicates == 1


def test_same_spelling_different_part_of_speech_stays_separate():
    merged, duplicates = dedupe_cards([
        card(lemma="добре", part_of_speech="adverb"),
        card(lemma="добре", part_of_speech="adjective"),
    ])
    assert len(merged) == 2 and duplicates == 0


def test_repeated_page_is_not_listed_twice_in_source():
    merged, _ = dedupe_cards([card(source="page1.jpg"), card(source="page1.jpg")])
    assert merged[0]["source"] == "page1.jpg"


# --- build_csv ----------------------------------------------------------------

def test_every_row_has_exactly_the_nine_capybara_columns():
    csv_text, count = build_csv(pd.DataFrame([card(), card(lemma="слово")]))
    assert count == 2
    assert all(len(row) == len(EXPORT_COLUMNS) == 9 for row in rows_of(csv_text))


def test_source_column_is_not_exported():
    csv_text, _ = build_csv(pd.DataFrame([card(source="page1.jpg")]))
    assert "page1.jpg" not in csv_text


def test_lemma_starting_with_hash_is_not_read_as_an_anki_directive():
    # Anki treats a line beginning with "#" as an import directive and drops it.
    # Quoting every field keeps the line starting with a quote instead.
    csv_text, count = build_csv(pd.DataFrame([card(lemma="#хештег")]))
    assert count == 1
    assert not body_of(csv_text).startswith("#")
    assert rows_of(csv_text)[0][0] == "#хештег"


def test_newline_in_a_sentence_does_not_split_the_note():
    # Anki reads one note per line, so an embedded newline would halve the card.
    csv_text, _ = build_csv(pd.DataFrame([card(example="Перший рядок.\nДругий рядок.")]))
    assert len(body_of(csv_text).strip("\n").splitlines()) == 1
    assert rows_of(csv_text)[0][5] == "Перший рядок. Другий рядок."


def test_embedded_comma_and_quote_survive_a_round_trip():
    text = 'She wrote "a book", then left.'
    csv_text, _ = build_csv(pd.DataFrame([card(example_translation=text)]))
    assert rows_of(csv_text)[0][6] == text


def test_blank_row_added_in_the_editor_is_dropped():
    blank = {column: "" for column in EXPORT_COLUMNS}
    csv_text, count = build_csv(pd.DataFrame([card(), blank]))
    assert count == 1


def test_missing_cells_export_as_empty_not_nan():
    csv_text, _ = build_csv(pd.DataFrame([card(gloss=None)]))
    assert rows_of(csv_text)[0][1] == ""
    assert "nan" not in csv_text.lower()


def test_empty_table_produces_no_rows_but_keeps_the_header():
    csv_text, count = build_csv(pd.DataFrame(columns=EXPORT_COLUMNS))
    assert count == 0
    assert csv_text == ANKI_HEADER


def test_header_declares_the_columns_in_export_order():
    assert "#columns:" + ",".join(EXPORT_COLUMNS) in ANKI_HEADER
    # Anki's deck/tags column directives are 1-indexed positions.
    assert EXPORT_COLUMNS[8 - 1] == "deck"
    assert EXPORT_COLUMNS[9 - 1] == "tags"


@pytest.mark.parametrize("value,expected", [
    (None, ""),
    (float("nan"), ""),
    ("  padded  ", "padded"),
    ("two\nlines", "two lines"),
    ("tab\tseparated", "tab separated"),
])
def test_clean_field(value, expected):
    assert clean_field(value) == expected


# --- export_stamp / export_filename -------------------------------------------

def test_the_name_does_not_change_while_the_export_does_not():
    # The regression this exists for: Streamlit identifies a download by
    # hashing its bytes *and* its filename, so a name holding the current time
    # mints a new file on every rerun, orphans the previous one, and leaves the
    # on-screen button pointing at a URL its GC has deleted. The tap then does
    # nothing at all.
    cache = {}
    csv_text, _ = build_csv(pd.DataFrame([card()]))
    first = export_stamp(csv_text, cache, dt.datetime(2026, 9, 15, 18, 49, 3))
    later = export_stamp(csv_text, cache, dt.datetime(2026, 9, 15, 19, 30, 0))
    assert first == later == "20260915-184903"


def test_the_name_changes_once_the_cards_change():
    # And the reason it is a timestamp at all: a repeated name collides with
    # the copy already in the download folder, which is what makes Android
    # Chrome ask "Download file again?" on every tap.
    cache = {}
    one, _ = build_csv(pd.DataFrame([card()]))
    two, _ = build_csv(pd.DataFrame([card(), card(lemma="слово")]))
    first = export_stamp(one, cache, dt.datetime(2026, 9, 15, 18, 49, 3))
    second = export_stamp(two, cache, dt.datetime(2026, 9, 15, 18, 55, 12))
    assert first != second


def test_an_edit_in_the_review_table_earns_a_new_name():
    cache = {}
    before, _ = build_csv(pd.DataFrame([card()]))
    after, _ = build_csv(pd.DataFrame([card(lemma_translation="tome")]))
    assert export_stamp(before, cache, dt.datetime(2026, 9, 15, 1, 0, 0)) != \
        export_stamp(after, cache, dt.datetime(2026, 9, 15, 1, 0, 1))


def test_the_stamp_store_holds_one_entry_however_long_the_session_runs():
    # It lives in session state and is touched on every rerun, so it must not
    # grow a row per keystroke.
    cache = {}
    for n in range(50):
        csv_text, _ = build_csv(pd.DataFrame([card(lemma=f"слово{n}")]))
        export_stamp(csv_text, cache)
    assert set(cache) == {"key", "stamp"}


def test_filename_keeps_the_extension_it_is_given():
    assert export_filename("csv", "20260915-184903") == "ukrainian_vocab_capybara_20260915-184903.csv"
    assert export_filename(".apkg", "20260915-184903").endswith("_20260915-184903.apkg")


def test_filenames_sort_chronologically_in_a_download_folder():
    assert export_filename("csv", "20260915-090500") < export_filename("csv", "20260915-184900")


# --- export_rows --------------------------------------------------------------

def test_both_exporters_see_the_same_rows():
    blank = {column: "" for column in EXPORT_COLUMNS}
    rows = export_rows(pd.DataFrame([card(), blank, card(lemma="слово")]))
    _, csv_count = build_csv(pd.DataFrame([card(), blank, card(lemma="слово")]))
    assert len(rows) == csv_count == 2
    assert [row["lemma"] for row in rows] == ["книга", "слово"]
