"""Extract yellow-highlighted vocabulary from a photo of a Ukrainian book page.

One page in, a list of Anki-ready card dicts out. The model call uses structured
outputs (`messages.parse`), so the response is schema-validated by the SDK and
there is no JSON to hand-parse.
"""

from __future__ import annotations

import base64
import io
from typing import List, Optional

import anthropic
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

# --- Model / request tuning ---------------------------------------------------

MODEL = "claude-sonnet-5"

# Thinking is adaptive by default on this model and its tokens count against
# max_tokens, so a tight cap truncates the answer rather than shortening it.
# The old 2048 could cut a densely highlighted page off mid-JSON and lose the
# whole page; 16000 leaves room for both the reasoning and ~100 cards.
MAX_TOKENS = 16000

# The API downscales any image whose long edge exceeds 1568px, so sending
# anything larger just costs upload time and gets resampled twice. Sitting
# exactly at the limit keeps the most detail available for OCR of small print
# and Cyrillic diacritics.
MAX_IMAGE_EDGE = 1568
JPEG_QUALITY = 85

# Transport-level retries (429s honour the server's retry-after, 5xx and
# connection errors back off exponentially). Handled by the SDK so this module
# does not reimplement it; auth and bad-request errors are not retried.
MAX_RETRIES = 4

# --- Capybara note-type defaults ----------------------------------------------
# These four values are what make a row importable as a Capybara note. Change
# them here rather than at the call sites.

CARD_LANGUAGE = "uk"
CARD_DECK = "Capybara::Ukrainian"
CARD_TAGS = "capybara::vocab"


class ExtractedCard(BaseModel):
    lemma: str = Field(description="Dictionary base form of the highlighted Ukrainian word (e.g. 'письменниця', not 'письменницею'). For a highlighted multi-word expression, the whole expression in its base form.")
    gloss: str = Field(description="Short English definition or gloss, a few words at most")
    lemma_translation: str = Field(description="Primary direct English translation of the base form")
    part_of_speech: str = Field(description="Lowercase part of speech: noun, verb, adjective, adverb, pronoun, preposition, conjunction, particle, numeral, or expression")
    example: str = Field(description="The complete sentence containing the highlighted word, copied verbatim from the page in its original inflected form")
    example_translation: str = Field(description="Accurate English translation of the full example sentence")


class PageExtractionResult(BaseModel):
    cards: List[ExtractedCard]


class PageExtractionError(RuntimeError):
    """A page could not be turned into cards. Message is safe to show a user."""


SYSTEM_PROMPT = (
    "You are a meticulous Ukrainian lexicographer building flashcards from photos "
    "of printed book pages. You read Ukrainian orthography accurately, including "
    "the letters і, ї, є and the apostrophe, and you never invent a word that is "
    "not visible on the page."
)

PROMPT = """Find every word or phrase marked with YELLOW highlighter on this book page.

For each one:
- Give its lemma (dictionary base form), not the inflected form printed on the page.
- Copy the full sentence it appears in, verbatim from the page, keeping the inflected form.
- Translate that sentence, and gloss the lemma.
- If a highlighted run spans several words that work as one unit (a fixed phrase or
  idiom), treat it as a single card with part_of_speech "expression".

Rules:
- Only yellow-highlighted text. Ignore underlining, margin notes, and unmarked text.
- If a word is highlighted more than once on the page, return it once.
- Transcribe exactly what is printed. If a highlighted word is cut off or illegible,
  leave it out rather than guessing.
- If nothing on the page is highlighted, return an empty list of cards."""


def optimize_image(img: Image.Image) -> Image.Image:
    """Normalise a camera photo for OCR: upright, opaque RGB, at most MAX_IMAGE_EDGE.

    `exif_transpose` applies the camera's rotation tag so a portrait photo is not
    sent sideways, and the RGB conversion keeps PNG uploads (which may carry an
    alpha channel, and which JPEG cannot encode) from failing at save time.
    """
    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        img = img.convert("RGB")
    # thumbnail() is a no-op when the image is already within bounds, so this is
    # safe to call on an image the caller has already downscaled.
    img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
    return img


def encode_image(img: Image.Image) -> str:
    """Base64 JPEG, ready for an image content block."""
    buffer = io.BytesIO()
    optimize_image(img).save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return base64.standard_b64encode(buffer.getvalue()).decode("utf-8")


def process_book_page(
    image: Image.Image,
    api_key: str,
    source: Optional[str] = None,
) -> List[dict]:
    """Extract highlighted vocabulary from one page photo.

    `source` is recorded on each card so a suspect row can be traced back to the
    photo it came from. Raises PageExtractionError with a readable message on
    failure; anthropic.AuthenticationError is left to propagate so the caller can
    report a bad key once rather than once per page.
    """
    client = anthropic.Anthropic(api_key=api_key, max_retries=MAX_RETRIES)

    try:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": encode_image(image),
                            },
                        },
                        {"type": "text", "text": PROMPT},
                    ],
                }
            ],
            output_format=PageExtractionResult,
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
        # Retrying these is pointless and only delays the error the user needs.
        raise
    except anthropic.RateLimitError as e:
        raise PageExtractionError(
            "Rate limited by the API even after retrying. Process fewer pages at "
            "once, or wait a minute and try again."
        ) from e
    except anthropic.APIConnectionError as e:
        raise PageExtractionError(f"Could not reach the API: {e}") from e
    except anthropic.APIStatusError as e:
        raise PageExtractionError(f"API error {e.status_code}: {e.message}") from e

    # A truncated response is the one failure that can look like success: the
    # parse would raise on half-written JSON, but a page that legitimately ends
    # on the cap loses its tail silently. Say so instead.
    if response.stop_reason == "max_tokens":
        raise PageExtractionError(
            "The response hit the token limit, so this page's cards are incomplete. "
            "Try photographing fewer highlights per page."
        )

    result = response.parsed_output
    if result is None:
        raise PageExtractionError("The model returned no structured output for this page.")

    return [
        {
            "lemma": card.lemma,
            "gloss": card.gloss,
            "lemma_translation": card.lemma_translation,
            "part_of_speech": card.part_of_speech,
            "language": CARD_LANGUAGE,
            "example": card.example,
            "example_translation": card.example_translation,
            "deck": CARD_DECK,
            "tags": CARD_TAGS,
            "source": source or "",
        }
        for card in result.cards
    ]
