"""The app renders.

A Streamlit script only executes when a session connects, so an import check —
or an HTTP request to the port — will not notice a crash at render time. The
StreamlitSecretNotFoundError this guards against shipped to main and broke the
documented Codespaces flow for exactly that reason. AppTest runs the script the
way a browser session does, headlessly.
"""

import datetime as dt
import pathlib
import types

import pytest
from streamlit.testing.v1 import AppTest

import anki_export

APP = str(pathlib.Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def app(monkeypatch, tmp_path):
    # No secrets.toml and no key in the environment: the state of a fresh clone.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    return AppTest.from_file(APP, default_timeout=60).run()


def test_app_renders_without_a_secrets_file_or_api_key(app):
    assert not app.exception, app.exception[0].value if app.exception else ""


def test_first_step_is_offered(app):
    assert any("Upload Book Pages" in header.value for header in app.subheader)


def test_api_key_box_is_present_and_empty(app):
    assert app.sidebar.text_input[0].value == ""


def test_nothing_to_export_before_any_photo_is_processed(app):
    assert not app.button  # no process/clear buttons with an empty queue
    assert not app.download_button


def test_environment_key_is_picked_up_when_present(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert at.sidebar.text_input[0].value == "sk-ant-from-env"


def _app_with_one_card(monkeypatch, tmp_path) -> AppTest:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["cards"] = [{
        "lemma": "книга", "gloss": "book", "lemma_translation": "book",
        "part_of_speech": "noun", "language": "uk", "example": "Книга тут.",
        "example_translation": "The book is here.",
        "deck": "Capybara::Ukrainian", "tags": "capybara::vocab",
        "source": "page1.jpg",
    }]
    at.run()
    assert not at.exception, at.exception[0].value if at.exception else ""
    return at


def test_review_table_and_export_appear_once_cards_exist(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["cards"] = [{
        "lemma": "книга", "gloss": "book", "lemma_translation": "book",
        "part_of_speech": "noun", "language": "uk", "example": "Книга тут.",
        "example_translation": "The book is here.",
        "deck": "Capybara::Ukrainian", "tags": "capybara::vocab",
        "source": "page1.jpg",
    }]
    at.run()
    assert not at.exception, at.exception[0].value if at.exception else ""
    assert any("Export Anki Cards" in header.value for header in at.subheader)
    labels = [download.label for download in at.download_button]
    assert len(labels) == 2, labels
    assert all("1 cards" in label for label in labels)


def test_a_deck_package_is_offered_alongside_the_csv(monkeypatch, tmp_path):
    # AnkiDroid handles .apkg but not text/csv, so the phone route only exists
    # if the deck package is actually served.
    at = _app_with_one_card(monkeypatch, tmp_path)
    extensions = {d.proto.url.rsplit(".", 1)[-1] for d in at.download_button}
    assert extensions == {"apkg", "csv"}


def test_neither_export_is_disabled_when_there_is_a_card(monkeypatch, tmp_path):
    at = _app_with_one_card(monkeypatch, tmp_path)
    assert not any(d.proto.disabled for d in at.download_button)


def test_a_downloads_url_survives_a_rerun(monkeypatch, tmp_path):
    """The bug that shipped: tapping a download button did nothing at all.

    Streamlit identifies a download file by hashing its bytes together with its
    filename, and serves it at a URL derived from that hash. Both inputs were
    moving on every rerun — the filename held the current time, and genanki
    stamped the .apkg with the wall clock — so each rerun registered a new file
    and orphaned the one the on-screen button still pointed at. Streamlit's
    media garbage collector then deleted it, and the tap fetched a 404, which
    the browser reports as nothing whatsoever.

    The clock is advanced between runs on purpose. Without that this test
    passes against the bug, because two runs land in the same second and the
    filename happens not to change — which is exactly why the bug survived the
    original suite and shipped.
    """
    ticking = iter(dt.datetime(2026, 9, 15, 18, 49, 3) + dt.timedelta(minutes=n)
                   for n in range(100))
    monkeypatch.setattr(
        anki_export, "dt",
        types.SimpleNamespace(datetime=types.SimpleNamespace(now=lambda: next(ticking))),
    )

    at = _app_with_one_card(monkeypatch, tmp_path)
    before = [download.proto.url for download in at.download_button]

    at.run()  # any interaction at all re-executes the script
    after = [download.proto.url for download in at.download_button]

    assert before == after, "download URL changed across a rerun; the old one is now a 404"
