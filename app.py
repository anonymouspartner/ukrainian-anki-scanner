import streamlit as st
import pandas as pd
from PIL import Image
import os
from gemini_parser import process_book_page

st.set_page_config(page_title="Ukrainian Book to Anki", page_icon="📚", layout="wide")

st.title("📚 Ukrainian Book Highlight Scanner for Anki")
st.write("Upload photos of highlighted book pages to extract vocabulary directly into your **Capybara** Anki CSV format.")

# Sidebar API Key Setup
st.sidebar.header("Configuration")
api_key_input = st.sidebar.text_input("Gemini API Key", type="password", help="Get a free key at aistudio.google.com")
api_key = api_key_input or os.environ.get("GEMINI_API_KEY")

if "cards" not in st.session_state:
    st.session_state.cards = []

# File uploader
uploaded_files = st.file_uploader("Upload Page Photos", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

if uploaded_files:
    if not api_key:
        st.error("Please enter a Gemini API Key in the sidebar to proceed.")
    else:
        if st.button("Process Images"):
            st.session_state.cards = []
            progress_bar = st.progress(0)
            
            for idx, uploaded_file in enumerate(uploaded_files):
                try:
                    image = Image.open(uploaded_file)
                    st.info(f"Processing image: {uploaded_file.name}...")
                    extracted = process_book_page(image, api_key)
                    st.session_state.cards.extend(extracted)
                except Exception as e:
                    st.error(f"Error processing {uploaded_file.name}: {e}")
                
                progress_bar.progress((idx + 1) / len(uploaded_files))
            
            st.success(f"Processing complete! Found {len(st.session_state.cards)} vocabulary words.")

# Review and Download Section
if st.session_state.cards:
    st.subheader("Edit & Review Flashcards")
    df = pd.DataFrame(st.session_state.cards)
    
    # Editable table for fine-tuning translations or typos
    edited_df = st.data_editor(
        df,
        num_rows="dynamic",
        column_order=["lemma", "gloss", "lemma_translation", "part_of_speech", "example", "example_translation", "language", "deck", "tags"],
        use_container_width=True
    )

    # Generate CSV formatted matching Capybara note-type header
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
        data=final_csv.encode('utf-8'),
        file_name="ukrainian_vocab_capybara.csv",
        mime="text/csv"
    )
