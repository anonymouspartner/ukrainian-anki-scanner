# 📚 Ukrainian Book Highlight Scanner for Anki

A Streamlit web app that scans photos of physical Ukrainian book pages, extracts
yellow-highlighted vocabulary using **Claude Sonnet 5**, lemmatizes the words,
pulls the full context sentence, and exports them for the Capybara note type as
either a **ready-to-import Anki deck** (`.apkg`) or a **CSV**.

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
* 📑 **Native Anki export** — a `.apkg` deck package that AnkiDroid opens with one
  tap, or a CSV carrying the header directives (`#separator:Comma`,
  `#notetype:Capybara`, `#deck column`, …) Anki needs to import without mapping.
* 📱 **Collision-free filenames** — every download is timestamped, so Android
  stops asking "Download file again?" on each export.

---

## 🛠️ Project structure

```text
.
├── app.py                    # Streamlit UI and batch execution
├── anki_export.py            # Dedup, export filenames, Capybara CSV rendering
├── anki_package.py           # .apkg deck-package rendering (genanki)
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

## 📤 Getting the cards into Anki

Two buttons, because the two platforms want different files. Both contain
exactly the same cards.

### 📦 Deck package (`.apkg`) — use this on a phone

AnkiDroid registers itself as a handler for `.apkg` but **not** for `text/csv`.
A downloaded CSV therefore just sits in the download folder, and the only way in
is to hunt it down from inside AnkiDroid's import screen. Tapping a downloaded
`.apkg` — from the download notification, the browser's download list, or Files
— hands it straight to AnkiDroid, which shows its own import dialog. No field
mapping, no file picker.

The package brings a `Capybara` note type with it, since a package has to carry
the note type it uses. Two details make repeat exports behave:

* **The note type and deck ids are derived from their names**, not drawn at
  random. Anki matches a note type by id, so a fresh id per export would stack
  up copies called `Capybara-a3f1` in your collection.
* **A note's identity is its lemma and part of speech.** Fix a translation and
  re-export and Anki updates the existing note, rather than importing a second
  one. (genanki's default is to hash every field, which does the opposite.)
* **The build is hermetic.** genanki stamps both the ids it generates and the
  zip entries it writes with the wall clock, so the same cards would otherwise
  come out as different bytes every time. `build_apkg` pins both, making the
  package a pure function of the cards it holds — which is also what keeps
  Streamlit from re-registering the download on every rerun (see "Filenames").

That id matching cuts the other way too: if you *already* have a Capybara note
type, this one is a different id and so imports beside it under the same name.
Take the CSV if you want the notes to land in the note type you already have.

### 📥 CSV — use this on a desktop

Nine columns, matching the Capybara note type:

```text
lemma, gloss, lemma_translation, part_of_speech, language, example, example_translation, deck, tags
```

Every field is quoted on export. Besides handling embedded commas and quotes,
that prevents a card whose first field starts with `#` from being read as an
Anki import directive and silently dropped. Newlines inside a sentence are
collapsed to spaces, since Anki reads one note per line.

### Filenames

Both downloads are named `ukrainian_vocab_capybara_<YYYYMMDD-HHMMSS>.<ext>`. The
name used to be fixed, which meant every export after the first collided with
the copy already in the download folder — and Android Chrome answers a collision
with a **"Download file again?"** dialog on every single tap. The timestamp also
keeps several scanning sessions apart in the folder.

The timestamp is taken **once per distinct export**, not per render, and both
files share it. This is load-bearing, not cosmetic. Streamlit identifies a
download by hashing its bytes together with its filename and serves it at a URL
derived from that hash; it reruns the whole script on every interaction, and
garbage-collects files the current run no longer references. A name holding the
current time therefore registers a *new* file on each rerun and orphans the one
the on-screen button still points at — so the next tap fetches a URL that now
404s, and the browser reports nothing at all. The same trap applies to the
bytes, which is why the package build is hermetic (see above).

The cost of that stability: re-downloading an export you have not changed reuses
its name, so Android asks "Download file again?" in that one case — correctly,
since it is the identical file. Change or add a single card and the name moves
on.

### The `source` column

The review table shows a **source** column naming the photo each word came from.
It is deliberately *not* exported, by either exporter — it exists so a suspicious
card can be checked against the original page.

---

## 🧪 Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite mocks the Anthropic transport, so it needs **no API key** and makes no
network request. It covers four things:

* **Export rules** (`tests/test_anki_export.py`) — the ways a row can be
  silently mangled on the way into Anki: a lemma starting with `#` read as an
  import directive, a newline splitting one note across two lines, a blank row
  added in the editor, cross-page duplicates. Plus that two exports never share
  a filename.
* **The deck package** (`tests/test_anki_package.py`) — unzips the `.apkg` and
  reads its SQLite collection back the way Anki would: the seven fields in
  order, deck and tags kept out of the fields, a row per deck, a re-export
  updating a note instead of duplicating it, and two builds of the same table
  coming out byte-identical.
* **The model call** (`tests/test_claude_parser.py`) — the request shape and
  schema, plus each failure mode: a truncated response, a rejected key, a server
  error, a rate limit.
* **That the app renders, and its downloads still work** (`tests/test_app_smoke.py`)
  — a Streamlit script only executes when a session connects, so importing
  `app.py` or curling the port will not notice a crash at render time. This runs
  the script the way a browser session does. It also pins the bug that shipped
  once already: a download button's URL must survive a rerun. That check
  advances the clock deliberately, because two runs inside the same second hide
  the fault — which is exactly how it got past the suite the first time.

CI runs the same commands on every push and pull request.

---

## ⚠️ Known issues

* **`gemini_parser.py` is not wired up.** Nothing imports it, and its dependency
  (`google-genai`) is not in `requirements.txt`, so it cannot currently be
  imported. It is kept for reference; delete it or restore it behind a provider
  switch.
