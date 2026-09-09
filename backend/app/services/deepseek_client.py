"""
Thin wrapper around the DeepSeek API (OpenAI-compatible).

Two capabilities are used elsewhere in the app:
  - chat_json(...)   text-in, JSON-out — used for generating question sets.
  - vision_json(...)  image(s)+text-in, JSON-out — used for grading a
                       photographed answer sheet directly (no local OCR
                       step, per the chosen architecture).

Both fall back to deterministic mock data when no API key is configured
(or MOCK_MODE=true), so the rest of the app can be built/demoed/tested
without a DeepSeek account. That's controlled centrally in config.py —
nothing else in the app needs to know whether it's talking to the real
API or not.

NOTE on the vision model: DeepSeek's vision-capable offering and its exact
model name have shifted over time. `deepseek_vision_model` in config.py is
the one knob to update if grading calls start failing with a
"model not found"/unsupported-modality style error — check DeepSeek's
current API docs. Everything downstream of this module (evaluation.py)
only depends on getting back JSON shaped the way it asks for, so a model
swap is a one-line config change, not a code change.
"""
import base64
import json
import logging
from pathlib import Path

from openai import OpenAI

from ..config import get_settings

logger = logging.getLogger(__name__)


class DeepSeekError(RuntimeError):
    pass


def _client() -> OpenAI:
    settings = get_settings()
    return OpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)


def _extract_json(raw_text: str) -> dict:
    """DeepSeek is asked to return pure JSON, but strip a ```json fence if it adds one anyway."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise DeepSeekError(f"DeepSeek did not return valid JSON: {e}\n---\n{raw_text[:2000]}") from e


def chat_json(system_prompt: str, user_prompt: str, *, mock_response: dict) -> dict:
    settings = get_settings()
    if settings.effective_mock_mode:
        logger.info("MOCK_MODE active (no DEEPSEEK_API_KEY set) — returning mock generation response.")
        return mock_response

    client = _client()
    try:
        response = client.chat.completions.create(
            model=settings.deepseek_text_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
        )
    except Exception as e:  # noqa: BLE001 — surface any SDK/network error uniformly
        raise DeepSeekError(f"DeepSeek chat request failed: {e}") from e

    content = response.choices[0].message.content or ""
    return _extract_json(content)


def _image_to_data_url(image_path: Path) -> str:
    suffix = image_path.suffix.lower().lstrip(".") or "jpeg"
    mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix
    b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:image/{mime};base64,{b64}"


def vision_json(system_prompt: str, user_prompt: str, image_paths: list[Path], *, mock_response: dict) -> dict:
    settings = get_settings()
    if settings.effective_mock_mode:
        logger.info("MOCK_MODE active (no DEEPSEEK_API_KEY set) — returning mock evaluation response.")
        return mock_response

    client = _client()
    content: list[dict] = [{"type": "text", "text": user_prompt}]
    for image_path in image_paths:
        content.append({"type": "image_url", "image_url": {"url": _image_to_data_url(image_path)}})

    try:
        response = client.chat.completions.create(
            model=settings.deepseek_vision_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
    except Exception as e:  # noqa: BLE001
        raise DeepSeekError(
            f"DeepSeek vision request failed: {e}. If this mentions an unknown/unsupported model, "
            f"double-check DEEPSEEK_VISION_MODEL in your .env against DeepSeek's current docs."
        ) from e

    response_content = response.choices[0].message.content or ""
    return _extract_json(response_content)
