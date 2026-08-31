import time
import base64
import io
from anthropic import Anthropic
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
    """Corrects EXIF orientation and minimizes dimensions for optimized document OCR.
    
    Tighter constraints save significant input token costs and transmission bandwidth
    from Streamlit to Claude, while maintaining legibility for OCR.
    """
    img = ImageOps.exif_transpose(img)
    # Claude can handle much smaller images for OCR. 1200px is usually plenty.
    img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
    return img

def process_book_page(image: Image.Image, api_key: str) -> List[dict]:
    """
    Sends optimized page image to Claude with retry handling and thinking block bypass.
    """
    client = Anthropic(api_key=api_key)
    optimized_image = optimize_image(image)
    
    # Convert PIL Image to base64 JPEG bytes
    buffered = io.BytesIO()
    # JPEG format and lower quality (60-70 range) dramatically reduces payload size
    optimized_image.save(buffered, format="JPEG", quality=60)
    img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
    
    prompt = """
    Analyze this photo of a Ukrainian book page. Identifies words or phrases highlighted 
    in yellow ink. Lemmatize them and provide accurate translations and examples.

    You must output your response strictly as a JSON object matching this exact schema:
    {
      "cards": [
        {
          "lemma": "...",
          "gloss": "...",
          "lemma_translation": "...",
          "part_of_speech": "...",
          "example": "...",
          "example_translation": "..."
        }
      ]
    }
    Return ONLY the raw JSON block with no markdown formatting wrappers or conversational text.
    """

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                # Fixed to official model ID string
                model='claude-sonnet-5',
                max_tokens=2048,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": img_base64,
                                },
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ],
                    }
                ]
            )
            
            # Skip ThinkingBlocks and isolate the actual text response
            response_text = ""
            for block in response.content:
                if block.type == 'text':
                    response_text = block.text
                    break
                    
            break
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            raise e

    # Clean potential markdown block wrappers if present
    cleaned_text = response_text.strip()
    if cleaned_text.startswith("```json"):
        cleaned_text = cleaned_text[7:]
    if cleaned_text.startswith("```"):
        cleaned_text = cleaned_text[3:]
    if cleaned_text.endswith("```"):
        cleaned_text = cleaned_text[:-3]
    cleaned_text = cleaned_text.strip()

    parsed_result = PageExtractionResult.model_validate_json(cleaned_text)
    
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
