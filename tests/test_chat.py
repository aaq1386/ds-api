import pytest
from unittest.mock import patch
from app.providers.base import StreamEvent


@pytest.fixture()
def fake_provider():
    async def fake_chat(self, prompt, history=None, thinking=True, search=False):
        yield StreamEvent(type="thinking", content="t1 ")
        yield StreamEvent(type="thinking", content="t2")
        yield StreamEvent(type="text", content="Hello ")
        yield StreamEvent(type="text", content="world")
        yield StreamEvent(type="done")

    async def fake_ensure_session(self):
        return "fake"

    async def fake_close(self):
        pass

    with patch("app.providers.deepseek.DeepSeekProvider.ensure_session", fake_ensure_session), \
         patch("app.providers.deepseek.DeepSeekProvider.chat", fake_chat), \
         patch("app.providers.deepseek.DeepSeekProvider.close", fake_close):
        yield


def test_chat_non_stream(client, fake_provider):
    r = client.post("/api/conversations", json={"title": "C"})
    cid = r.json()["id"]
    r = client.post("/api/chat", json={"conversation_id": cid, "prompt": "hi", "thinking": False})
    assert r.status_code == 200
    assert r.json()["text"] == "Hello world"
    assert r.json()["thinking"] == "t1 t2"
