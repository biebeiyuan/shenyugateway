from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from shenyu_gateway.middleware import register_middlewares


def test_pwa_worker_and_build_info_bypass_browser_and_cdn_caches():
    app = FastAPI()

    @app.get("/chat/sw.js")
    async def worker():
        return {"worker": True}

    @app.get("/chat/build-info.json")
    async def build_info():
        return {"build": True}

    @app.get("/chat/assets/index.js")
    async def hashed_bundle():
        return {"bundle": True}

    register_middlewares(app, SimpleNamespace(gateway_key=""))
    client = TestClient(app)

    for path in ("/chat/sw.js", "/chat/build-info.json"):
        response = client.get(path)
        assert response.headers["cache-control"] == "no-store, max-age=0"
        assert response.headers["cdn-cache-control"] == "no-store"

    assert "cache-control" not in client.get("/chat/assets/index.js").headers
