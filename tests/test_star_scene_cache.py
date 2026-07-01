from __future__ import annotations

import asyncio

from shenyu_gateway.stars import _scene


class CountingEmbeddingClient:
    """Fake embedding client that records how many times each text is embedded."""

    def __init__(self, model: str = "test-model", dim: int = 4):
        self.model = model
        self.expected_dim = dim
        self.calls: list[str] = []

    async def embed(self, text: str):
        self.calls.append(text)
        # Deterministic pseudo-vector from the text so cosine sim is stable.
        seed = sum(ord(c) for c in text) or 1
        vec = [((seed * (i + 1)) % 7) / 7.0 for i in range(self.expected_dim)]
        return vec, None


def _reset_cache():
    _scene._DESC_VECTOR_CACHE.clear()


def test_scene_description_vectors_are_cached_across_calls():
    _reset_cache()
    client = CountingEmbeddingClient()
    descriptions = dict(_scene._DEFAULT_SCENE_DESCRIPTIONS)

    async def run():
        await _scene._classify_scene_by_embedding("随便一句不含关键词的话", descriptions, client)
        await _scene._classify_scene_by_embedding("另一句同样普通的话", descriptions, client)

    asyncio.run(run())

    # Each of the 6 descriptions must be embedded at most once total across both
    # calls (cache hit on the second pass); only the two queries embed each time.
    desc_texts = set(descriptions.values())
    for desc in desc_texts:
        assert client.calls.count(desc) == 1, f"description re-embedded: {desc!r}"

    # Both queries were embedded (queries are never cached).
    assert client.calls.count("随便一句不含关键词的话") == 1
    assert client.calls.count("另一句同样普通的话") == 1


def test_scene_cache_key_includes_model():
    _reset_cache()
    descriptions = {"daily": "生活碎片、吃饭、天气"}
    client_a = CountingEmbeddingClient(model="model-a")
    client_b = CountingEmbeddingClient(model="model-b")

    async def run():
        await _scene._embed_scene_description(client_a, "生活碎片、吃饭、天气")
        await _scene._embed_scene_description(client_a, "生活碎片、吃饭、天气")  # cache hit
        await _scene._embed_scene_description(client_b, "生活碎片、吃饭、天气")  # different model -> miss

    asyncio.run(run())

    assert client_a.calls.count("生活碎片、吃饭、天气") == 1  # second call cached
    assert client_b.calls.count("生活碎片、吃饭、天气") == 1  # separate model key
