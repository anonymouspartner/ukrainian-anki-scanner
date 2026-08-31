import concurrent.futures
import streamlit as st
import pandas as pd
from PIL import Image
import os
from gemini_parser import process_book_page

st.set_page_config(page_title="Ukrainian Book to Anki", page_icon="📚", layout="wide")

st.title("📚 Ukrainian Book Highlight Scanner for Anki")
st.write("Upload photos of highlighted book pages to extract vocabulary directly into your **Capybara** Anki CSV format.")

# Sidebar API Key Setup (Checks st.secrets for persistence)
st.sidebar.header("Configuration")
secret_key = ""
if "GEMINI_API_KEY" in st.secrets:
    secret_key = st.secrets["GEMINI_API_KEY"]
elif os.environ.get("GEMINI_API_KEY"):
    secret_key = os.environ.get("GEMINI_API_KEY")

api_key_input = st.sidebar.text_input("Gemini API Key", value=secret_key, type="password", help="Get a free key at aistudio.google.com")
api_key = api_key_input or secret_key

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
            
            with st.spinner("Processing images concurrently..."):
                # max_workers=2 prevents triggering the Gemini Free Tier 429 rate limit
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                    # Submit all image processing tasks
                    future_to_file = {
                        executor.submit(process_book_page, Image.open(file), api_key): file 
                        for file in uploaded_files
                    }
                    
                    completed_count = 0
                    total_files = len(uploaded_files)
                    
                    # Gather results as each thread finishes
                    for future in concurrent.futures.as_completed(future_to_file):
                        file = future_to_file[future]
                        try:
                            extracted = future.result()
                            st.session_state.cards.extend(extracted)
                            st.success(f"Processed {file.name}: Found {len(extracted)} vocabulary words.")
                        except Exception as e:
                            st.error(f"Error processing {file.name}: {e}")
                        
                        # Update progress bar
                        completed_count += 1
                        progress_bar.progress(completed_count / total_files)
            
            st.success(f"Processing complete! Found {len(st.session_state.cards)} total vocabulary words.")

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
