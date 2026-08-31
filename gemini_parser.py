import time
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import List
from PIL import Image, ImageOps

class ExtractedCard(BaseModel):
    lemma: str = Field(description="Dictionary base form of the highlighted Ukrainian word (e.g., 'письменниця' instead of 'письменницею')")
    gloss: str = Field(description="Short English definition or gloss")
    lemma_translation: str = Field(description="Primary direct English translation of the base word")
    part_of_speech: str = Field(description="Part of speech in lowercase: noun, verb, adjective, adverb, expression, etc.")
    example: str = Field(description="Complete original Ukrainian sentence from the page containing the highlighted word")
    example_translation: str = Field(description="Accurate English translation of the full example sentence")

class PageExtractionResult(BaseModel):
    cards: List[ExtractedCard]

def optimize_image(img: Image.Image) -> Image.Image:
    """Corrects EXIF orientation and downscales large camera photos to speed up transfer."""
    img = ImageOps.exif_transpose(img)
    img.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    return img

def process_book_page(image: Image.Image, api_key: str) -> List[dict]:
    """
    Sends optimized page image to Gemini 3.6 Flash with retry handling for Free Tier limits.
    """
    client = genai.Client(api_key=api_key)
    optimized_image = optimize_image(image)
    
    prompt = """
    Analyze this photo of a Ukrainian book page.
    1. Identify every word or phrase highlighted in yellow ink.
    2. Extract the complete original sentence containing each highlighted word.
    3. Lemmatize the highlighted word into its dictionary base form (lemma).
    4. Provide short English glosses, translations, and part of speech tags.
    """

    max_retries = 4
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=[optimized_image, prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=PageExtractionResult,
                    temperature=0.1
                )
            )
            break
        except Exception as e:
            error_msg = str(e)
            # Catch both 503 capacity errors and 429 Rate Limit errors
            if any(err in error_msg for err in ["503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED"]) and attempt < max_retries - 1:
                time.sleep(12) # Wait out the 10-second penalty from the Free Tier
                continue
            raise e

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
