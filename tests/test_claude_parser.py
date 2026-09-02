"""The model call: what we send, and how each failure mode surfaces.

Every test runs against a mock transport, so the suite needs no API key and
makes no network request.
"""

import json
from unittest import mock

import anthropic
import httpx2
import pytest
from PIL import Image

import claude_parser
from claude_parser import (
    MAX_IMAGE_EDGE,
    PageExtractionError,
    encode_image,
    optimize_image,
    process_book_page,
)

CARD = {
    "lemma": "письменниця",
    "gloss": "female writer",
    "lemma_translation": "writer",
    "part_of_speech": "noun",
    "example": "Вона була відомою письменницею.",
    "example_translation": "She was a famous writer.",
}


def respond(*, cards=(CARD,), stop_reason="end_turn"):
    """A handler returning a well-formed structured-output response."""
    def handler(request):
        handler.body = json.loads(request.content)
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant",
            "model": claude_parser.MODEL, "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "content": [{"type": "text",
                         "text": json.dumps({"cards": list(cards)}, ensure_ascii=False)}],
        })
    return handler


def error(status, payload):
    return lambda request: httpx2.Response(status, json=payload)


def run(handler, image=None, source=None, max_retries=0):
    client = anthropic.Anthropic(
        api_key="test", max_retries=max_retries,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    with mock.patch.object(anthropic, "Anthropic", return_value=client):
        return process_book_page(image or Image.new("RGB", (800, 600), "white"),
                                 "test", source)


# --- image preparation --------------------------------------------------------

def test_oversized_photo_is_capped_at_the_edge_the_api_accepts():
    # Above this the API resamples server-side, so sending more is wasted bytes.
    out = optimize_image(Image.new("RGB", (4000, 3000), "white"))
    assert max(out.size) == MAX_IMAGE_EDGE


def test_small_photo_is_not_upscaled():
    assert optimize_image(Image.new("RGB", (640, 480), "white")).size == (640, 480)


def test_transparent_png_can_be_encoded():
    # The uploader accepts PNG, and JPEG cannot encode an alpha channel, so
    # without the RGB conversion this raises before any request is made.
    assert encode_image(Image.new("RGBA", (300, 200), (255, 0, 0, 128)))


def test_repeated_optimize_is_stable():
    once = optimize_image(Image.new("RGB", (4000, 3000), "white"))
    assert optimize_image(once).size == once.size


# --- request shape ------------------------------------------------------------

def test_request_carries_the_image_and_a_validating_schema():
    handler = respond()
    run(handler)
    body = handler.body

    assert body["model"] == claude_parser.MODEL
    assert body["max_tokens"] == claude_parser.MAX_TOKENS

    content = body["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/jpeg"

    schema = body["output_config"]["format"]["schema"]
    card_schema = schema["$defs"]["ExtractedCard"]
    # additionalProperties:false plus a full required list is what makes the
    # response schema-valid rather than merely JSON-shaped.
    assert card_schema["additionalProperties"] is False
    assert set(card_schema["required"]) == set(CARD)


# --- successful extraction ----------------------------------------------------

def test_extracted_card_carries_the_capybara_note_fields():
    [row] = run(respond(), source="page3.jpg")
    assert row["lemma"] == CARD["lemma"]
    assert row["language"] == claude_parser.CARD_LANGUAGE
    assert row["deck"] == claude_parser.CARD_DECK
    assert row["tags"] == claude_parser.CARD_TAGS
    assert row["source"] == "page3.jpg"


def test_page_with_no_highlights_yields_no_cards():
    assert run(respond(cards=())) == []


def test_missing_source_is_recorded_as_empty_not_none():
    assert run(respond())[0]["source"] == ""


# --- failure modes ------------------------------------------------------------

def test_truncated_response_is_reported_rather_than_silently_short():
    # Thinking tokens count against max_tokens; a page that hits the cap has
    # lost cards, and returning it as if complete is the dangerous outcome.
    with pytest.raises(PageExtractionError, match="token limit"):
        run(respond(stop_reason="max_tokens"))


def test_bad_api_key_propagates_so_the_caller_can_report_it_once():
    # Not wrapped: app.py distinguishes this to avoid one identical error per photo.
    with pytest.raises(anthropic.AuthenticationError):
        run(error(401, {"type": "error", "error": {
            "type": "authentication_error", "message": "invalid x-api-key"}}))


def test_server_error_becomes_a_readable_message():
    with pytest.raises(PageExtractionError, match="500"):
        run(error(500, {"type": "error", "error": {
            "type": "api_error", "message": "boom"}}))


def test_rate_limit_after_retries_explains_what_to_do():
    with pytest.raises(PageExtractionError, match="Rate limited"):
        run(error(429, {"type": "error", "error": {
            "type": "rate_limit_error", "message": "slow down"}}))
