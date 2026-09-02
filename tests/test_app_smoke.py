"""The app renders.

A Streamlit script only executes when a session connects, so an import check —
or an HTTP request to the port — will not notice a crash at render time. The
StreamlitSecretNotFoundError this guards against shipped to main and broke the
documented Codespaces flow for exactly that reason. AppTest runs the script the
way a browser session does, headlessly.
"""

import pathlib

import pytest
from streamlit.testing.v1 import AppTest

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
    [download] = at.download_button
    assert "1 cards" in download.label
