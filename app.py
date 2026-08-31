import concurrent.futures
import os
import pandas as pd
from PIL import Image, ImageOps
import streamlit as st
from claude_parser import process_book_page

st.set_page_config(page_title="Ukrainian Book to Anki", page_icon="📚", layout="wide")

def prep_for_queue(img: Image.Image) -> Image.Image:
    """Downscales uploaded photos immediately to prevent high RAM usage during multi-file processing."""
    img = ImageOps.exif_transpose(img)
    img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
    return img

# --- Sidebar API Key Setup ---
st.sidebar.header("Configuration")
secret_key = st.secrets.get("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", ""))
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

if uploaded_files:
    new_queue = []
    for file in uploaded_files:
        raw_img = Image.open(file)
        compressed_img = prep_for_queue(raw_img)
        new_queue.append((file.name, compressed_img))
    st.session_state.image_queue = new_queue

queue_len = len(st.session_state.image_queue)

# --- Processing Section ---
if queue_len > 0:
    st.divider()
    st.subheader(f"2. Process Queue ({queue_len} photos selected)")

    col_submit, col_clear = st.columns([2, 1])

    with col_submit:
        process_disabled = not bool(api_key)
        if st.button(f"🚀 Process {queue_len} Photos with Claude", type="primary", disabled=process_disabled):
            st.session_state.cards = []
            progress_bar = st.progress(0)

            with st.spinner(f"Processing {queue_len} pages concurrently..."):
                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                    future_to_label = {
                        executor.submit(process_book_page, img, api_key): label
                        for label, img in st.session_state.image_queue
                    }

                    completed_count = 0
                    for future in concurrent.futures.as_completed(future_to_label):
                        label = future_to_label[future]
                        try:
                            extracted = future.result()
                            st.session_state.cards.extend(extracted)
                            st.toast(f"✅ {label}: Extracted {len(extracted)} words")
                        except Exception as e:
                            st.error(f"Error on {label}: {e}")

                        completed_count += 1
                        progress_bar.progress(completed_count / queue_len)

            st.success(f"Processing complete! Extracted {len(st.session_state.cards)} total cards.")

    with col_clear:
        if st.button("🗑️ Clear Selection"):
            st.session_state.image_queue = []
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
    df = pd.DataFrame(st.session_state.cards)

    edited_df = st.data_editor(
        df,
        num_rows="dynamic",
        column_order=[
            "lemma",
            "gloss",
            "lemma_translation",
            "part_of_speech",
            "example",
            "example_translation",
            "language",
            "deck",
            "tags",
        ],
        use_container_width=True,
    )

    header_comments = (
        "#separator:Comma\n"
        "#html:false\n"
        "#notetype:Capybara\n"
        "#columns:lemma,gloss,lemma_translation,part_of_speech,language,example,example_translation,deck,tags\n"
        "#deck column:8\n"
        "#tags column:9\n"
    )

    csv_body = edited_df.to_csv(index=False, header=False)
    final_csv = header_comments + csv_body

    st.download_button(
        label="📥 Download Anki CSV",
        data=final_csv.encode("utf-8"),
        file_name="ukrainian_vocab_capybara.csv",
        mime="text/csv",
    )
