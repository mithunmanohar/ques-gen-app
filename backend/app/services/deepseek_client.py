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
import time
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
        logger.error("DeepSeek reply is not valid JSON (%s). First 2000 characters:\n%s", e, raw_text[:2000])
        raise DeepSeekError(f"DeepSeek did not return valid JSON: {e}\n---\n{raw_text[:2000]}") from e


def _log_usage(kind: str, model: str, started: float, response) -> None:
    usage = getattr(response, "usage", None)
    logger.info(
        "DeepSeek %s reply from %s in %.1fs%s, finish_reason=%s",
        kind,
        model,
        time.perf_counter() - started,
        f" ({usage.prompt_tokens} prompt + {usage.completion_tokens} completion tokens)" if usage else "",
        response.choices[0].finish_reason if response.choices else "?",
    )


# DeepSeek's JSON mode "may occasionally return empty content"; one retry is cheap.
EMPTY_REPLY_RETRIES = 1


def _complete_json(kind: str, model: str, messages: list[dict], temperature: float, started: float) -> dict:
    client = _client()
    for attempt in range(1, EMPTY_REPLY_RETRIES + 2):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=temperature,
            )
        except Exception as e:  # noqa: BLE001 — surface any SDK/network error uniformly
            logger.error(
                "DeepSeek %s request failed after %.1fs: %s: %s", kind, time.perf_counter() - started, type(e).__name__, e
            )
            hint = ""
            if "model" in str(e).lower():
                hint = (
                    f" The model '{model}' may not exist on DeepSeek any more — check the model names on "
                    "https://api-docs.deepseek.com and set DEEPSEEK_TEXT_MODEL / DEEPSEEK_VISION_MODEL in .env."
                )
            raise DeepSeekError(f"DeepSeek {kind} request failed ({type(e).__name__}): {e}.{hint}") from e

        _log_usage(kind, model, started, response)
        choice = response.choices[0] if response.choices else None
        content = (choice.message.content if choice else "") or ""
        logger.debug("Reply (%d chars):\n%s", len(content), content[:4000])
        if choice is not None and choice.finish_reason == "length":
            raise DeepSeekError(
                f"DeepSeek's {kind} reply was cut off (it hit the output length limit) before the JSON was complete. "
                "Try a smaller question set or fewer/smaller photos."
            )
        if content.strip():
            return _extract_json(content)
        logger.warning("DeepSeek returned an empty reply (attempt %d) — retrying", attempt)
    raise DeepSeekError(f"DeepSeek returned an empty {kind} reply {EMPTY_REPLY_RETRIES + 1} times in a row. Try again.")


def chat_json(system_prompt: str, user_prompt: str, *, mock_response: dict) -> dict:
    settings = get_settings()
    if settings.effective_mock_mode:
        logger.info("MOCK MODE (no DEEPSEEK_API_KEY): returning placeholder data instead of calling DeepSeek")
        return mock_response

    logger.info(
        "Calling DeepSeek %s at %s: system prompt %d chars, user prompt %d chars",
        settings.deepseek_text_model,
        settings.deepseek_base_url,
        len(system_prompt),
        len(user_prompt),
    )
    logger.debug("User prompt:\n%s", user_prompt[:4000])
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
    return _complete_json("chat", settings.deepseek_text_model, messages, 0.7, time.perf_counter())


def _image_to_data_url(image_path: Path) -> str:
    suffix = image_path.suffix.lower().lstrip(".") or "jpeg"
    mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix
    b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:image/{mime};base64,{b64}"


def vision_json(system_prompt: str, user_prompt: str, image_paths: list[Path], *, mock_response: dict) -> dict:
    settings = get_settings()
    if settings.effective_mock_mode:
        logger.info(
            "MOCK MODE (no DEEPSEEK_API_KEY): returning placeholder grading for %d image(s) instead of calling DeepSeek",
            len(image_paths),
        )
        return mock_response

    content: list[dict] = [{"type": "text", "text": user_prompt}]
    total_bytes = 0
    for image_path in image_paths:
        total_bytes += image_path.stat().st_size
        logger.debug("  attaching image %s (%.0f KB)", image_path.name, image_path.stat().st_size / 1024)
        content.append({"type": "image_url", "image_url": {"url": _image_to_data_url(image_path)}})
    logger.info(
        "Calling DeepSeek vision %s at %s: prompt %d chars, %d image(s), %.1f MB",
        settings.deepseek_vision_model,
        settings.deepseek_base_url,
        len(user_prompt),
        len(image_paths),
        total_bytes / 1e6,
    )
    # Images are only allowed in user messages (DeepSeek returns 400 otherwise).
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": content}]
    return _complete_json("vision", settings.deepseek_vision_model, messages, 0.2, time.perf_counter())
