# 📚 Ukrainian Book Highlight Scanner for Anki

A Streamlit web app that scans photos of physical Ukrainian book pages, extracts
yellow-highlighted vocabulary using **Claude Sonnet 5**, lemmatizes the words,
pulls the full context sentence, and generates an **Anki-ready CSV** formatted for
the Capybara note type.

---

## ✨ Features

* 📸 **Bulk upload** — select and process many book page photos at once.
* 🔍 **OCR & lemmatization** — finds yellow-highlighted text, extracts the full
  context sentence, reduces each word to its dictionary base form, tags part of
  speech, and translates both the word and its sentence.
* ⚡ **Concurrent processing** — pages are processed in parallel via a thread pool.
* 🖼️ **Image optimization** — corrects EXIF rotation and downscales to the largest
  size the API actually uses, so no detail is wasted and none is thrown away.
* 🔁 **Cross-page dedup** — a word highlighted on several pages becomes one card,
  annotated with every page it appeared on.
* ✏️ **Interactive review** — edit any extracted field in an inline data editor
  before downloading.
* 📑 **Native Anki export** — CSV with the header directives (`#separator:Comma`,
  `#notetype:Capybara`, `#deck column`, …) Anki needs to import without mapping.

---

## 🛠️ Project structure

```text
.
├── app.py                    # Streamlit UI and batch execution
├── anki_export.py            # Dedup and Capybara-note-type CSV rendering
├── claude_parser.py          # Image prep, Claude API call, schema validation
├── gemini_parser.py          # Unused alternate backend (see "Known issues")
├── tests/                    # pytest suite (no API key needed)
├── requirements.txt          # Runtime dependencies
├── requirements-dev.txt      # Adds pytest
└── .github/workflows/        # CI: byte-compile + tests on 3.11 and 3.12
```

---

## 🚀 Running it

```bash
pip install -r requirements.txt
streamlit run app.py
```

Supply an Anthropic API key in one of three ways (checked in this order):

1. `.streamlit/secrets.toml` with `ANTHROPIC_API_KEY = "sk-ant-..."`
2. an `ANTHROPIC_API_KEY` environment variable
3. the **Claude API Key** box in the sidebar

None of the three is required to start the app — it boots with an empty key box
and simply disables the process button until a key is present.

---

## 📤 Export format

Nine columns, matching the Capybara note type:

```text
lemma, gloss, lemma_translation, part_of_speech, language, example, example_translation, deck, tags
```

Every field is quoted on export. Besides handling embedded commas and quotes,
that prevents a card whose first field starts with `#` from being read as an
Anki import directive and silently dropped. Newlines inside a sentence are
collapsed to spaces, since Anki reads one note per line.

The review table also shows a **source** column naming the photo each word came
from. It is deliberately *not* exported — it exists so a suspicious card can be
checked against the original page.

---

## 🧪 Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite mocks the Anthropic transport, so it needs **no API key** and makes no
network request. It covers three things:

* **Export rules** (`tests/test_anki_export.py`) — the ways a row can be
  silently mangled on the way into Anki: a lemma starting with `#` read as an
  import directive, a newline splitting one note across two lines, a blank row
  added in the editor, cross-page duplicates.
* **The model call** (`tests/test_claude_parser.py`) — the request shape and
  schema, plus each failure mode: a truncated response, a rejected key, a server
  error, a rate limit.
* **That the app renders** (`tests/test_app_smoke.py`) — a Streamlit script only
  executes when a session connects, so importing `app.py` or curling the port
  will not notice a crash at render time. This runs the script the way a browser
  session does.

CI runs the same commands on every push and pull request.

---

## ⚠️ Known issues

* **`gemini_parser.py` is not wired up.** Nothing imports it, and its dependency
  (`google-genai`) is not in `requirements.txt`, so it cannot currently be
  imported. It is kept for reference; delete it or restore it behind a provider
  switch.
