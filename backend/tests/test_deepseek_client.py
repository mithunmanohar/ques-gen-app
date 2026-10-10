"""DeepSeek client behaviour against a fake API client (no network): retries, truncation, request shape."""
import io
from types import SimpleNamespace

import pytest

from app.config import get_settings
from app.services import deepseek_client


class FakeCompletions:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        content, finish_reason = reply
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish_reason)],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )


@pytest.fixture()
def fake_api(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "mock_mode", False)
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")

    def install(*replies):
        completions = FakeCompletions(replies)
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        monkeypatch.setattr(deepseek_client, "_client", lambda: client)
        return completions

    return install


def test_defaults_use_current_deepseek_models():
    from app.config import Settings

    assert Settings.model_fields["deepseek_text_model"].default == "deepseek-flash"
    assert Settings.model_fields["deepseek_vision_model"].default == "deepseek-flash"


def test_empty_reply_is_retried_once(fake_api):
    api = fake_api(("", "stop"), ('{"ok": true}', "stop"))
    assert deepseek_client.chat_json("Reply in JSON.", "hi", mock_response={}) == {"ok": True}
    assert len(api.calls) == 2


def test_repeated_empty_reply_fails_clearly(fake_api):
    fake_api(("", "stop"), ("", "stop"))
    with pytest.raises(deepseek_client.DeepSeekError, match="empty chat reply 2 times"):
        deepseek_client.chat_json("Reply in JSON.", "hi", mock_response={})


def test_truncated_reply_fails_clearly(fake_api):
    fake_api(('{"items": [', "length"))
    with pytest.raises(deepseek_client.DeepSeekError, match="cut off"):
        deepseek_client.chat_json("Reply in JSON.", "hi", mock_response={})


def test_unknown_model_error_explains_the_fix(fake_api):
    fake_api(RuntimeError("Model Not Exist"))
    with pytest.raises(deepseek_client.DeepSeekError, match="DEEPSEEK_VISION_MODEL"):
        deepseek_client.chat_json("Reply in JSON.", "hi", mock_response={})


def test_vision_request_shape(fake_api, tmp_path, monkeypatch):
    photo = tmp_path / "sheet.png"
    photo.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    monkeypatch.setattr(get_settings(), "deepseek_vision_model", "deepseek-flash")
    api = fake_api(('{"items": []}', "stop"))
    assert deepseek_client.vision_json("Grade it. JSON only.", "paper", [photo], mock_response={}) == {"items": []}
    call = api.calls[0]
    assert call["model"] == "deepseek-flash"
    assert call["response_format"] == {"type": "json_object"}
    system, user = call["messages"]
    assert system["role"] == "system" and isinstance(system["content"], str)  # images only in the user message
    assert user["content"][0] == {"type": "text", "text": "paper"}
    assert user["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_heic_and_unsupported_photos_are_rejected_on_upload(client):
    pattern = client.post(
        "/api/patterns",
        json={
            "name": "P",
            "config_json": {
                "name": "P",
                "subject": "S",
                "grade": "1",
                "sections": [{"name": "A", "question_type": "MCQ", "num_questions": 1, "marks_per_question": 1}],
            },
        },
    ).json()
    qs = client.post("/api/question-sets/generate", json={"pattern_id": pattern["id"]}).json()[0]

    def upload(name, data):
        return client.post(
            "/api/submissions",
            data={"question_set_id": qs["id"]},
            files={"images": (name, io.BytesIO(data), "application/octet-stream")},
        )

    heic_bytes = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00"
    by_name = upload("IMG_0001.HEIC", b"whatever")
    assert by_name.status_code == 400 and "HEIC" in by_name.json()["detail"]
    by_content = upload("IMG_0001.jpg", heic_bytes)  # renamed but still HEIC inside
    assert by_content.status_code == 400 and "Most Compatible" in by_content.json()["detail"]
    pdf = upload("answers.pdf", b"%PDF-1.7")
    assert pdf.status_code == 400 and "JPEG, PNG, GIF or WebP" in pdf.json()["detail"]
    assert upload("answers.jpeg", b"\xff\xd8\xff\xe0 fake jpeg").status_code == 200
