from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import List
from PIL import Image

class ExtractedCard(BaseModel):
    lemma: str = Field(description="Dictionary base form of the highlighted Ukrainian word (e.g., 'письменниця' instead of 'письменницею')")
    gloss: str = Field(description="Short English definition or gloss")
    lemma_translation: str = Field(description="Primary direct English translation of the base word")
    part_of_speech: str = Field(description="Part of speech in lowercase: noun, verb, adjective, adverb, expression, etc.")
    example: str = Field(description="Complete original Ukrainian sentence from the page containing the highlighted word")
    example_translation: str = Field(description="Accurate English translation of the full example sentence")

class PageExtractionResult(BaseModel):
    cards: List[ExtractedCard]

def process_book_page(image: Image.Image, api_key: str) -> List[dict]:
    """
    Sends page image to Gemini 3.6 Flash to locate yellow-highlighted Ukrainian words,
    extract context sentences, lemmatize words, and return structured JSON.
    """
    client = genai.Client(api_key=api_key)
    
    prompt = """
    Analyze this photo of a Ukrainian book page.
    1. Identify every word or phrase highlighted in yellow ink.
    2. Extract the complete original sentence containing each highlighted word.
    3. Lemmatize the highlighted word into its dictionary base form (lemma).
    4. Provide short English glosses, translations, and part of speech tags.
    """

    response = client.models.generate_content(
        model='gemini-3.6-flash',
        contents=[image, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=PageExtractionResult,
            temperature=0.1
        )
    )

    # Parse output into list of dicts with fixed Capybara deck defaults
    parsed_result = PageExtractionResult.model_validate_json(response.text)
    
    cards_data = []
    for card in parsed_result.cards:
        cards_data.append({
            "lemma": card.lemma,
            "gloss": card.gloss,
            "lemma_translation": card.lemma_translation,
            "part_of_speech": card.part_of_speech,
            "language": "uk",
            "example": card.example,
            "example_translation": card.example_translation,
            "deck": "Capybara::Ukrainian",
            "tags": "capybara::vocab"
        })
        
    return cards_data
