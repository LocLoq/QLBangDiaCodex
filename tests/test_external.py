from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np

from normastore.infrastructure.external import GeminiSearch, TmdbClient


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self.payload = payload or {}
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class FakeHttpClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def get(self, *_args, **_kwargs):
        self.calls += 1
        return next(self.responses)

    def close(self):
        pass


def test_tmdb_client_retries_rate_limit(monkeypatch):
    client = TmdbClient("test-key")
    fake = FakeHttpClient([FakeResponse(429), FakeResponse(200, {"results": []})])
    client.client = fake
    monkeypatch.setattr("normastore.infrastructure.external.time.sleep", lambda _delay: None)

    assert client.discover_movies(1) == []
    assert fake.calls == 2


def test_gemini_embedding_without_key_and_zero_vector_are_safe():
    assert GeminiSearch(None).embed("phim gia đình") is None
    scores = GeminiSearch.cosine(np.zeros(2, dtype=np.float32), np.zeros((1, 2), dtype=np.float32))
    assert scores.tolist() == [0.0]


def test_gemini_embedding_uses_requested_dimension(monkeypatch):
    captured = {}

    class FakeModels:
        def embed_content(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.2, 0.4])])

    fake_genai = SimpleNamespace(Client=lambda **_kwargs: SimpleNamespace(models=FakeModels()))
    monkeypatch.setitem(__import__("sys").modules, "google", SimpleNamespace(genai=fake_genai))

    vector = GeminiSearch("test-key", embedding_dimensions=768).embed("phim phiêu lưu")

    assert np.allclose(vector, [0.2, 0.4])
    assert captured["config"] == {"output_dimensionality": 768}


def test_gemini_rate_limit_reason_is_safe():
    provider = GeminiSearch("test-key")
    provider.last_error = "429 RESOURCE_EXHAUSTED"

    assert "quota limit" in provider.unavailable_reason()


def test_vietnam_timezone_is_available_for_windows_builds():
    assert ZoneInfo("Asia/Ho_Chi_Minh").key == "Asia/Ho_Chi_Minh"


def test_tmdb_localized_detail_uses_english_only_for_missing_fields(monkeypatch):
    client = TmdbClient("test-key")
    responses = iter([
        {"name": "Tên Việt", "overview": "", "seasons": []},
        {"name": "English title", "overview": "English overview", "seasons": [{"season_number": 1}]},
    ])
    monkeypatch.setattr(client, "show_detail", lambda *_args: next(responses))

    detail = client.localized_show_detail(1)

    assert detail["name"] == "Tên Việt"
    assert detail["overview"] == "English overview"
