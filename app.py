import concurrent.futures
import csv
import io
import os

import anthropic
import pandas as pd
import streamlit as st
from PIL import Image

from claude_parser import PageExtractionError, optimize_image, process_book_page

st.set_page_config(page_title="Ukrainian Book to Anki", page_icon="📚", layout="wide")

# The nine columns of the Capybara note type, in the order the #columns header
# below declares them. Built explicitly so a column added to the review table
# (like "source") cannot leak into the export and shift every field right.
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

MAX_WORKERS = 3


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


def read_secret(name: str) -> str:
    """Read a Streamlit secret, tolerating the absence of a secrets file.

    `st.secrets` raises rather than returning a default when no secrets.toml
    exists anywhere on disk — even via `.get()` — which is the normal state of a
    fresh clone or Codespace. Falling back to the environment keeps the app
    usable there, with the sidebar as the last resort.
    """
    try:
        return st.secrets.get(name, "") or ""
    except Exception:  # noqa: BLE001 - any secrets-loading failure is non-fatal
        return ""


# --- Sidebar API Key Setup ---
st.sidebar.header("Configuration")
secret_key = read_secret("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
api_key_input = st.sidebar.text_input(
    "Claude API Key",
    value=secret_key,
    type="password",
    help="Enter your Anthropic API key",
)
api_key = api_key_input or secret_key

# --- State Management ---
if "image_queue" not in st.session_state:
    st.session_state.image_queue = []  # List of tuples: (filename, PIL_Image)
if "queue_signature" not in st.session_state:
    st.session_state.queue_signature = None
if "cards" not in st.session_state:
    st.session_state.cards = []

st.title("📚 Ukrainian Book Highlight Scanner for Anki")
st.write("Upload multiple book page photos at once to extract vocabulary directly into your **Capybara** Anki CSV format using **Claude Sonnet 5**.")

# --- File Uploader ---
st.subheader("1. Upload Book Pages")
uploaded_files = st.file_uploader(
    "Select page photos (select multiple files from your device gallery or storage)",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True,
)

# Streamlit reruns this script top to bottom on every interaction — every button
# click, every cell edited in the table below. Decoding and resampling each photo
# unconditionally would redo that work on all of them each time, so the queue is
# rebuilt only when the selection itself changes.
if uploaded_files:
    signature = tuple((file.name, file.size) for file in uploaded_files)
    if signature != st.session_state.queue_signature:
        queue = []
        for file in uploaded_files:
            # Downscale once, here, to the size the API will actually use: it
            # caps RAM while several photos are queued, and hands the model the
            # most legible image it can accept.
            queue.append((file.name, optimize_image(Image.open(file))))
        st.session_state.image_queue = queue
        st.session_state.queue_signature = signature
elif st.session_state.queue_signature is not None:
    st.session_state.image_queue = []
    st.session_state.queue_signature = None

queue_len = len(st.session_state.image_queue)

# --- Processing Section ---
if queue_len > 0:
    st.divider()
    st.subheader(f"2. Process Queue ({queue_len} photos selected)")

    col_submit, col_clear = st.columns([2, 1])

    with col_submit:
        process_disabled = not bool(api_key)
        if process_disabled:
            st.info("Add your Claude API key in the sidebar to start.")
        if st.button(f"🚀 Process {queue_len} Photos with Claude", type="primary", disabled=process_disabled):
            st.session_state.cards = []
            progress_bar = st.progress(0)
            extracted_cards = []
            failures = []
            auth_failed = False

            with st.spinner(f"Processing {queue_len} pages concurrently..."):
                with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                    future_to_label = {
                        executor.submit(process_book_page, img, api_key, label): label
                        for label, img in st.session_state.image_queue
                    }

                    for completed_count, future in enumerate(
                        concurrent.futures.as_completed(future_to_label), start=1
                    ):
                        label = future_to_label[future]
                        try:
                            found = future.result()
                            extracted_cards.extend(found)
                            st.toast(f"✅ {label}: {len(found)} words")
                        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
                            # The key is wrong for every page, so report it once
                            # instead of stacking one identical error per photo.
                            auth_failed = True
                        except PageExtractionError as e:
                            failures.append((label, str(e)))
                        except Exception as e:  # noqa: BLE001 - surfaced to the user below
                            failures.append((label, f"Unexpected error: {e}"))

                        progress_bar.progress(completed_count / queue_len)

            if auth_failed:
                st.error("Your Claude API key was rejected. Check it in the sidebar and try again.")

            for label, message in failures:
                st.error(f"{label}: {message}")

            deduped, duplicates = dedupe_cards(extracted_cards)
            st.session_state.cards = deduped

            if deduped:
                note = f" ({duplicates} repeat{'s' if duplicates != 1 else ''} merged)" if duplicates else ""
                st.success(f"Extracted {len(deduped)} unique cards{note}.")
            elif not auth_failed and not failures:
                st.warning("No highlighted words were found in these photos.")

    with col_clear:
        if st.button("🗑️ Clear Selection"):
            st.session_state.image_queue = []
            st.session_state.queue_signature = None
            st.session_state.cards = []
            st.rerun()

    # Thumbnail Preview Rack
    with st.expander("Preview Selected Photos", expanded=False):
        grid_cols = st.columns(min(queue_len, 6))
        for idx, (label, img) in enumerate(st.session_state.image_queue):
            with grid_cols[idx % 6]:
                st.image(img, caption=label, use_container_width=True)

# --- Review & Export Section ---
if st.session_state.cards:
    st.divider()
    st.subheader("3. Export Anki Cards")
    st.caption("Edit any cell before downloading. The \"source\" column shows which photo each word came from and is not exported.")
    df = pd.DataFrame(st.session_state.cards)

    edited_df = st.data_editor(
        df,
        key="card_editor",
        num_rows="dynamic",
        column_order=EXPORT_COLUMNS + ["source"],
        column_config={"source": st.column_config.TextColumn("source", disabled=True)},
        use_container_width=True,
    )

    final_csv, row_count = build_csv(edited_df)

    st.download_button(
        label=f"📥 Download Anki CSV ({row_count} cards)",
        data=final_csv.encode("utf-8"),
        file_name="ukrainian_vocab_capybara.csv",
        mime="text/csv",
        disabled=row_count == 0,
    )
