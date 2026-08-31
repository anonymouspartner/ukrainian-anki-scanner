# 📚 Ukrainian Book Highlight Scanner for Anki

An automated Streamlit web application that scans photos of physical Ukrainian book pages, extracts yellow-highlighted vocabulary using **Claude Sonnet**, lemmatizes words, extracts full context example sentences, and generates an **Anki-ready CSV file** formatted for the Capybara note type.

---

## ✨ Features

* 📸 **Bulk Upload**: Select and process multiple book page photos simultaneously.
* 🔍 **OCR & Lemmatization**: Automatically identifies highlighted yellow text, extracts the full context sentence, lemmatizes words into their dictionary base forms, tags parts of speech, and provides accurate English translations.
* ⚡ **Concurrent Processing**: Leverages Python's `ThreadPoolExecutor` to process multi-page uploads in parallel for fast processing.
* 🖼️ **Image Optimization**: Auto-corrects EXIF orientation and downscales large camera images before transmission to minimize RAM overhead and API latency.
* ✏️ **Interactive Review**: Edit or adjust extracted card fields directly inside an inline Streamlit data editor before downloading.
* 📑 **Native Anki Export**: Generates a CSV complete with pre-configured header directives (`#separator:Comma`, `#notetype:Capybara`, `#deck column`, etc.) for seamless Anki imports.

---

## 🛠️ Project Structure

```text
.
├── app.py              # Main Streamlit UI and batch execution logic
├── claude_parser.py    # Image downscaling, Claude API integration, and Pydantic schema validation
├── requirements.txt    # Python dependencies
└── README.md           # Documentation
# ukrainian-anki-scanner