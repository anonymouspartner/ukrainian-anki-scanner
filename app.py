import concurrent.futures
import os
import pandas as pd
from PIL import Image
import streamlit as st
from claude_parser import process_book_page

st.set_page_config(page_title="Ukrainian Book to Anki", page_icon="📚", layout="wide")

st.title("📚 Ukrainian Book Highlight Scanner for Anki")
st.write(
    "Upload photos or snap pages directly to build a processing queue. Extract vocabulary into your **Capybara** Anki CSV format using **Claude Sonnet 5**."
)

# Sidebar API Key Setup
st.sidebar.header("Configuration")
secret_key = ""
if "ANTHROPIC_API_KEY" in st.secrets:
    secret_key = st.secrets["ANTHROPIC_API_KEY"]
elif os.environ.get("ANTHROPIC_API_KEY"):
    secret_key = os.environ.get("ANTHROPIC_API_KEY")

api_key_input = st.sidebar.text_input(
    "Claude API Key",
    value=secret_key,
    type="password",
    help="Enter your Anthropic API key",
)
api_key = api_key_input or secret_key

# --- Initialize Session State for Image Queue ---
if "image_queue" not in st.session_state:
    st.session_state.image_queue = [] # List of tuples: (label, PIL_Image)

if "cards" not in st.session_state:
    st.session_state.cards = [] # List of dicts (parsed cards)


# --- Section 1: Add Pages to Queue (Batch Mode) ---
st.subheader("1. Build Processing Queue (Mobile Snap or Upload)")
col1, col2 = st.columns([1, 1])

with col1:
    camera_file = st.camera_input("Snap a photo to queue")
    # Streamlit reloads the app upon taking a photo. 
    # If a new photo exists and isn't the most recent one added, queue it.
    if camera_file is not None:
        new_camera_img = Image.open(camera_file)
        # Use simple duplication check within the session to prevent loops
        if not st.session_state.image_queue or camera_file.name != st.session_state.image_queue[-1][0]:
            st.session_state.image_queue.append((f"Camera Snap {camera_file.name}", new_camera_img))
            st.success("✅ Photo snapped and added to queue.")
            # Trick to force camera input to clear/reset without complex UI
            st.rerun() 

with col2:
    uploaded_files = st.file_uploader(
        "Or upload multiple page photos",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
        help="Mobile users: tapping upload may open your camera for batch snapping within the system dialog."
    )
    if uploaded_files:
        for file in uploaded_files:
            new_img = Image.open(file)
            # Add unless name/label already exists in queue
            existing_labels = [label for label, _ in st.session_state.image_queue]
            if file.name not in existing_labels:
                st.session_state.image_queue.append((file.name, new_img))
        st.success(f"✅ Added {len(uploaded_files)} image(s) from upload to queue.")

# --- Section 2: Manage and Process Queue ---
if st.session_state.image_queue:
    st.divider()
    queue_count = len(st.session_state.image_queue)
    st.subheader(f"2. Manage Queue ({queue_count} images ready)")
    
    # Display queue thumbnails in grid
    thumb_cols = st.columns(min(queue_count, 8))
    for i, (label, img) in enumerate(st.session_state.image_queue):
        with thumb_cols[i % 8]:
            thumb = img.copy()
            thumb.thumbnail((150, 150))
            st.image(thumb, caption=f"Img {i+1}")

    col_btn1, col_btn2, _ = st.columns([1.5, 1, 3])
    with col_btn1:
        if not api_key:
            st.warning("👈 Enter API Key first")
            process_btn = st.button("Process Queue", disabled=True)
        else:
            process_btn = st.button("🚀 Process Queue with Concurrent Claude")
            
    with col_btn2:
        if st.button("🗑️ Clear Queue"):
            st.session_state.image_queue = []
            st.session_state.cards = []
            st.rerun()

    # Handling the Processing Task
    if process_btn and st.session_state.image_queue:
        progress_bar = st.progress(0)
        
        # Clear old results before starting batch
        st.session_state.cards = []

        with st.spinner(f"Processing {queue_count} images concurrently with Claude Sonnet 5..."):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                future_to_label = {
                    executor.submit(process_book_page, img, api_key): label
                    for label, img in st.session_state.image_queue
                }

                completed_count = 0
                total_files = len(st.session_state.image_queue)

                for future in concurrent.futures.as_completed(future_to_label):
                    label = future_to_label[future]
                    try:
                        extracted = future.result()
                        st.session_state.cards.extend(extracted)
                        st.success(
                            f"Processed {label}: Found {len(extracted)} vocabulary words."
                        )
                    except Exception as e:
                        st.error(f"Error processing {label}: {e}")

                    completed_count += 1
                    progress_bar.progress(completed_count / total_files)

        st.success(
            f"Processing complete! Found {len(st.session_state.cards)} total vocabulary words."
        )

# --- Section 3: Review and Download ---
if st.session_state.cards:
    st.divider()
    st.subheader("3. Edit & Review Flashcards")
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
